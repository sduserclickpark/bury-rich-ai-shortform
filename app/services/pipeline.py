"""영상 제작 파이프라인: 분석 → 음성 인식 → 기획 → 렌더링 → 저장."""
from __future__ import annotations

import logging
import shutil
import subprocess
from pathlib import Path

from .. import config, db
from . import analyzer, asr, benchmark, copywriter, costs, editor, planner
from .catalog import STYLES

log = logging.getLogger(__name__)


def ensure_analysis(media: dict, progress) -> dict:
    a = db.jload(media["analysis_json"])
    if a.get("segments") is not None and a:
        return a
    if media["kind"] == "image":
        a = analyzer.analyze_image(media["path"])
    else:
        a = analyzer.analyze_video(media["path"])
    db.run("UPDATE media SET analysis_json=?, probe_json=? WHERE id=?",
           (db.jdump(a), db.jdump(a.get("probe", {})), media["id"]))
    return a


def ensure_transcript(media: dict) -> list[dict]:
    a = media.get("analysis") or db.jload(media["analysis_json"])
    if "transcript" in a:
        return a["transcript"].get("segments", [])
    if media["kind"] != "video" or not a.get("overall", {}).get("has_audio"):
        a["transcript"] = {"available": False, "segments": [], "error": "음성 없음"}
    elif a["overall"].get("sound_ratio", 0) < 0.1:
        a["transcript"] = {"available": False, "segments": [], "error": "말소리가 거의 없음"}
    else:
        a["transcript"] = asr.transcribe(media["path"])
        t = a["transcript"]
        db.run("INSERT INTO settings(key,value) VALUES ('asr_status',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
               ("정상 작동 (" + db.now()[:10] + ")" if t.get("available") else (t.get("error") or "실패"),))
    db.run("UPDATE media SET analysis_json=? WHERE id=?", (db.jdump(a), media["id"]))
    return a["transcript"].get("segments", [])


def _frame_jpg(path: str, t: float, out: Path) -> None:
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-ss", f"{t:.2f}", "-i", path, "-frames:v", "1",
                    "-vf", "scale=512:-2", "-q:v", "4", str(out)], timeout=60)


def pick_music(style: str, mood: str) -> dict | None:
    want = STYLES.get(style, {}).get("music", "")
    if style == "asmr":
        return None
    rows = db.q("SELECT * FROM music WHERE active=1 AND commercial_ok=1")
    if not rows:
        return None
    for key in (mood, want):
        m = [r for r in rows if key and key in (r["mood"] or "")]
        if m:
            return m[0]
    return rows[0]


def produce(job_id: int, payload: dict, progress) -> dict:
    order = db.q1("SELECT * FROM orders WHERE id=?", (payload["order_id"],))
    if not order:
        raise ValueError("주문을 찾을 수 없습니다.")
    biz = db.q1("SELECT * FROM businesses WHERE id=?", (order["business_id"],))
    style = payload.get("style") or order["style"] or "trend"
    duration = int(payload.get("duration") or order["duration"] or 30)
    if duration not in config.ALLOWED_DURATIONS:
        duration = 30
    db.run("UPDATE orders SET status='processing', updated_at=? WHERE id=?", (db.now(), order["id"]))

    media_rows = db.q("SELECT * FROM media WHERE order_id=? ORDER BY id", (order["id"],))
    if not media_rows:
        raise ValueError("업로드된 영상/사진이 없습니다.")

    usage = None
    if payload.get("plan"):  # 관리자 수정본 다시 렌더링
        plan = payload["plan"]
        if payload.get("duration") and int(payload["duration"]) != plan["duration"]:
            plan = planner.retime(plan, int(payload["duration"]))
    else:
        mlist = []
        for i, m in enumerate(media_rows):
            progress(5 + int(30 * i / len(media_rows)), f"원본 분석 중 ({i + 1}/{len(media_rows)})")
            a = ensure_analysis(m, progress)
            mlist.append({**m, "analysis": a})
        progress(38, "음성 인식 중")
        transcripts = {}
        for m in mlist:
            if m["kind"] == "video":
                transcripts[str(m["id"])] = ensure_transcript(m)
        progress(42, "인기 숏폼 패턴 적용·기획 중")
        pattern = benchmark.industry_pattern(biz["industry"])
        if style == "auto":
            style = pattern.get("template_style") or "trend"
        # 장면 수 추정을 위해 규칙 기반 기획을 먼저 만든다
        order_d = {**order, "duration": duration}
        st = STYLES.get(style, STYLES["trend"])
        n_scenes = max(2, round((duration - 3) / st["cut"]))
        copy = copywriter.rule_based(biz, order_d, n_scenes)
        if config.ANTHROPIC_API_KEY:
            try:
                work = config.WORK_DIR / f"job{job_id}_frames"
                work.mkdir(parents=True, exist_ok=True)
                frames = {}
                cands = sorted(planner._candidates(mlist), key=lambda c: -c["score"])[:8]
                for c in cands:
                    p = work / f"{c['key']}.jpg"
                    if c["kind"] == "image":
                        _frame_jpg(c["path"], 0, p)
                    else:
                        _frame_jpg(c["path"], (c["start"] + c["end"]) / 2, p)
                    if p.exists():
                        frames[c["key"]] = str(p)
                copy, usage = copywriter.claude_copy(biz, order_d, n_scenes, frames, pattern, st["name"])
            except Exception as e:  # API 장애 시 무료 엔진으로 계속 진행
                log.warning("Claude copy failed, fallback to rule: %s", e)
                copy["fallback_reason"] = f"Claude 사용 실패 → 기본 문구 사용 ({type(e).__name__})"
        music = pick_music(style, order.get("mood", ""))
        plan = planner.build_plan(order=order_d, biz=biz, media_list=mlist, style=style, duration=duration,
                                  pattern=pattern, copy=copy, music=music, transcripts=transcripts)
        if copy.get("fallback_reason"):
            plan["notes"].append(copy["fallback_reason"])
        plan["sns"] = copywriter.sns_pack(biz, copy)
        # 관리자가 바꾼 문구 우선 적용
        for k in ("hook_text", "cta_text"):
            if payload.get(k):
                plan[k] = payload[k]

    last = db.q1("SELECT MAX(version) v FROM renders WHERE order_id=?", (order["id"],))
    version = (last["v"] or 0) + 1
    out = config.OUTPUT_DIR / f"order{order['id']}" / f"v{version}_{plan['style']}_{plan['duration']}s.mp4"
    work = config.WORK_DIR / f"job{job_id}"
    if work.exists():
        shutil.rmtree(work, ignore_errors=True)
    result = editor.render(plan, work, out, log=progress)
    shutil.rmtree(work, ignore_errors=True)
    shutil.rmtree(config.WORK_DIR / f"job{job_id}_frames", ignore_errors=True)

    product = db.q1("SELECT price FROM products WHERE code=?", (order["product_code"],))
    price = order["price"] or (product["price"] if product else 0)
    cost = costs.actual_job_cost(usage, result["render_seconds"],
                                 out.stat().st_size, price)
    if usage:
        cost["claude_usage"] = usage
    rid = db.run(
        "INSERT INTO renders(order_id,version,style,duration,plan_json,output_path,thumb_path,sns_json,cost_json,created_at)"
        " VALUES (?,?,?,?,?,?,?,?,?,?)",
        (order["id"], version, plan["style"], plan["duration"], db.jdump(plan), str(out), result["thumb"],
         db.jdump(plan.get("sns", {})), db.jdump(cost), db.now()),
    )
    db.run("UPDATE orders SET status='review', updated_at=? WHERE id=?", (db.now(), order["id"]))
    return {"render_id": rid, "version": version, "output": result["output"], "render_seconds": result["render_seconds"]}
