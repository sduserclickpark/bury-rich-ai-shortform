"""인기 숏폼 벤치마킹: 관리자가 등록한 참고 영상/링크/패턴 + (키가 있을 때) YouTube 공식 API.

원칙
- 확인할 수 없는 수치는 만들지 않는다. 모든 수치에 출처(api / manual / measured)를 붙인다.
- 참고 영상은 '패턴(컷 길이, 길이, 구성 등)'만 추출하며 영상 자체를 고객 영상에 복제하지 않는다.
- 조회수만으로 성공 원인을 단정하지 않도록 게시 기간·채널 규모를 함께 계산한다.
"""
from __future__ import annotations

import json
import re
import urllib.parse
import urllib.request
from collections import Counter
from datetime import datetime, timezone

from .. import config, db
from .analyzer import analyze_video


def detect_platform(url: str) -> str:
    u = url.lower()
    if "youtube.com" in u or "youtu.be" in u:
        return "youtube"
    if "instagram.com" in u:
        return "instagram"
    if "tiktok.com" in u:
        return "tiktok"
    return "other" if u else "manual"


def youtube_id(url: str) -> str | None:
    m = re.search(r"(?:shorts/|v=|youtu\.be/|embed/)([A-Za-z0-9_-]{11})", url)
    return m.group(1) if m else None


def _get_json(url: str) -> dict:
    with urllib.request.urlopen(url, timeout=20) as r:
        return json.loads(r.read().decode())


def fetch_youtube(url: str) -> dict:
    """YouTube Data API v3 (무료 할당량: 하루 10,000 단위, videos.list 1회 = 1단위)."""
    if not config.YOUTUBE_API_KEY:
        raise RuntimeError("YOUTUBE_API_KEY가 설정되지 않았습니다. 관리자 설정 안내를 참고하세요.")
    vid = youtube_id(url)
    if not vid:
        raise ValueError("유튜브 영상 ID를 찾을 수 없는 링크입니다.")
    key = urllib.parse.quote(config.YOUTUBE_API_KEY)
    v = _get_json(f"https://www.googleapis.com/youtube/v3/videos?part=snippet,statistics,contentDetails&id={vid}&key={key}")
    if not v.get("items"):
        raise ValueError("영상을 찾을 수 없습니다(비공개/삭제 가능).")
    it = v["items"][0]
    st, sn = it.get("statistics", {}), it.get("snippet", {})
    ch = _get_json(f"https://www.googleapis.com/youtube/v3/channels?part=statistics&id={sn.get('channelId')}&key={key}")
    subs = None
    if ch.get("items"):
        cst = ch["items"][0].get("statistics", {})
        if not cst.get("hiddenSubscriberCount"):
            subs = int(cst.get("subscriberCount", 0))
    published = sn.get("publishedAt")
    days = None
    if published:
        dt = datetime.fromisoformat(published.replace("Z", "+00:00"))
        days = max(1.0, (datetime.now(timezone.utc) - dt).total_seconds() / 86400)
    views = int(st["viewCount"]) if "viewCount" in st else None
    m = {
        "source": "youtube_api", "fetched_at": db.now(),
        "views": views, "likes": int(st["likeCount"]) if "likeCount" in st else None,
        "comments": int(st["commentCount"]) if "commentCount" in st else None,
        "shares": None,  # 공식 API 미제공 → 확인 불가
        "published_at": published, "channel_subscribers": subs,
        "views_per_day": round(views / days, 1) if views is not None and days else None,
        "views_per_subscriber": round(views / subs, 2) if views is not None and subs else None,
        "ad_promoted": None,  # 광고 집행 여부는 API로 확인 불가
        "duration_iso": it.get("contentDetails", {}).get("duration"),
    }
    return {"title": sn.get("title", ""), "metrics": m}


def iso_duration_sec(s: str | None) -> float | None:
    if not s:
        return None
    m = re.match(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", s)
    if not m:
        return None
    h, mi, se = (int(x) if x else 0 for x in m.groups())
    return float(h * 3600 + mi * 60 + se)


def analyze_reference_video(ref_id: int, path: str) -> dict:
    """관리자가 적법하게 확보한 참고 영상 파일에서 편집 패턴을 측정한다."""
    a = analyze_video(path)
    ov = a["overall"]
    dur = ov["duration"]
    cuts = ov["scene_cuts"]
    avg_cut = round(dur / (cuts + 1), 2) if dur else None
    segs = a["segments"]
    first3 = [s for s in segs if s["start"] < 3.0]
    hook_motion = round(sum(s["motion"] for s in first3) / len(first3), 2) if first3 else None
    measured = {
        "source": "measured", "duration": dur, "scene_cuts": cuts, "avg_cut_sec": avg_cut,
        "first3s_motion": hook_motion, "first3s_cuts": len([s for s in segs if 0 < s["start"] < 3.0]),
        "avg_brightness": ov["avg_brightness"], "has_audio": ov["has_audio"],
        "orientation": ov["orientation"],
    }
    ref = db.q1("SELECT metrics_json FROM references_db WHERE id=?", (ref_id,))
    metrics = db.jload(ref["metrics_json"]) if ref else {}
    metrics["measured"] = measured
    db.run(
        "UPDATE references_db SET duration_sec=?, cut_count=?, avg_cut_sec=?, metrics_json=?, analyzed_at=? WHERE id=?",
        (dur, cuts, avg_cut, db.jdump(metrics), db.now(), ref_id),
    )
    return measured


def compute_reliability(ref: dict) -> str:
    m = db.jload(ref.get("metrics_json"))
    pts = 0
    if m.get("source") == "youtube_api" or m.get("views") is not None:
        pts += 1
    if m.get("measured"):
        pts += 1
    if ref.get("hook_type") and ref.get("story_structure"):
        pts += 1
    return {0: "low", 1: "low", 2: "medium"}.get(pts, "high")


def industry_pattern(industry: str) -> dict:
    """업종별 등록된 참고 패턴을 요약한다. 없으면 빈 패턴(스타일 기본값 사용)."""
    refs = db.q("SELECT * FROM references_db WHERE active=1 AND industry=?", (industry,))
    scope = "industry"
    if not refs:
        refs = db.q("SELECT * FROM references_db WHERE active=1")
        scope = "all"
    if not refs:
        return {"count": 0, "scope": "none"}
    cuts = [r["avg_cut_sec"] for r in refs if r["avg_cut_sec"]]
    durs = [r["duration_sec"] for r in refs if r["duration_sec"]]

    def mode(field):
        c = Counter(r[field] for r in refs if r[field])
        return c.most_common(1)[0][0] if c else ""

    hooks = [r["hook_text"] for r in refs if r["hook_text"]]
    return {
        "count": len(refs), "scope": scope, "ref_ids": [r["id"] for r in refs],
        "avg_cut_sec": round(sum(cuts) / len(cuts), 2) if cuts else None,
        "avg_duration": round(sum(durs) / len(durs), 1) if durs else None,
        "hook_type": mode("hook_type"), "caption_position": mode("caption_position"),
        "caption_style": mode("caption_style"), "music_mood": mode("music_mood"),
        "story_structure": mode("story_structure"), "cta_type": mode("cta_type"),
        "template_style": mode("template_style"), "edit_pattern": mode("edit_pattern"),
        "hook_examples": hooks[:5],
    }
