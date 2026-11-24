"""숏폼 기획: 분석 결과 + 스타일 + 벤치마킹 패턴 → 편집 계획(plan).

plan 은 JSON 으로 저장되며, 관리자가 문구/길이/스타일을 고친 뒤 그대로 다시 렌더링할 수 있다
(향후 자연어 수정 기능도 이 plan 을 수정하는 방식으로 확장).
"""
from __future__ import annotations

import math

from .catalog import CAPTION_STYLES, STYLES

END_CARD_SEC = 3.0
HOOK_SEC = 2.6


def _candidates(media_list: list[dict]) -> list[dict]:
    """사용 가능한 구간(span) 목록. 같은 촬영 컷(shot) 안의 연속된 양호 구간은 하나로 합친다.
    중복·불량(어두움/흐림/흔들림) 구간은 제외."""
    def build(allow_bad: bool) -> list[dict]:
        cands = []
        for order_idx, m in enumerate(media_list):
            a = m["analysis"]
            if m["kind"] == "image":
                sg = a["segments"][0]
                cands.append({"media_id": m["id"], "kind": "image", "path": m["path"], "start": 0.0,
                              "end": 999.0, "len": 999.0, "score": sg["score"], "motion": 0.0,
                              "center_x": sg["center_x"], "order": order_idx, "key": f"m{m['id']}s0",
                              "brightness": sg["brightness"]})
                continue
            cur = None
            for sg in a["segments"]:
                ok = allow_bad or (sg.get("usable") and "duplicate_of" not in sg)
                if ok and cur and cur["shot"] == sg.get("shot") and abs(cur["end"] - sg["start"]) < 0.01:
                    w0, w1 = cur["len"], sg["end"] - sg["start"]
                    cur["score"] = (cur["score"] * w0 + sg["score"] * w1) / (w0 + w1)
                    cur["motion"] = (cur["motion"] * w0 + sg["motion"] * w1) / (w0 + w1)
                    cur["brightness"] = (cur["brightness"] * w0 + sg["brightness"] * w1) / (w0 + w1)
                    cur["end"] = sg["end"]
                    cur["len"] = cur["end"] - cur["start"]
                    continue
                if cur:
                    cands.append(cur)
                    cur = None
                if ok:
                    cur = {"media_id": m["id"], "kind": "video", "path": m["path"], "start": sg["start"],
                           "end": sg["end"], "len": sg["end"] - sg["start"], "score": sg["score"],
                           "motion": sg["motion"], "center_x": sg["center_x"], "order": order_idx,
                           "shot": sg.get("shot"), "key": f"m{m['id']}s{sg['idx']}", "brightness": sg["brightness"]}
            if cur:
                cands.append(cur)
        return cands

    cands = build(False)
    return cands if cands else build(True)  # 모두 불량이면 그나마 나은 구간이라도 사용


def build_plan(*, order: dict, biz: dict, media_list: list[dict], style: str, duration: int,
               pattern: dict, copy: dict, music: dict | None, transcripts: dict) -> dict:
    st = STYLES.get(style, STYLES["trend"])
    cut = st["cut"]
    notes = []
    # 벤치마킹 패턴 반영: 등록된 참고 영상의 평균 컷 길이를 스타일 기본값과 절반씩 섞는다
    if pattern.get("avg_cut_sec"):
        cut = round(min(4.0, max(0.8, (cut + pattern["avg_cut_sec"]) / 2)), 2)
        notes.append(f"참고 영상 {pattern['count']}개의 평균 컷 길이 {pattern['avg_cut_sec']}초를 반영")
    # 음악 박자가 있으면 컷 길이를 박자 단위로 맞춘다
    if music and music.get("bpm"):
        beat = 60.0 / music["bpm"]
        cut = max(beat, round(cut / beat) * beat)
        notes.append(f"배경음악 {music['bpm']}BPM 박자에 맞춰 컷 길이 {cut:.2f}초")

    end_sec = 2.5 if duration <= 15 else END_CARD_SEC
    body = duration - end_sec
    cands = _candidates(media_list)
    if not cands:
        raise ValueError("편집에 사용할 수 있는 영상/사진이 없습니다.")

    labels = copy.get("scene_labels") or {}

    def rank(c):
        v = c["score"] + min(15, c["motion"] * 1.5)
        if c["key"] in labels:
            v += labels[c["key"]]["value"] * 2
        return v

    # 1) 후킹 장면: 점수+움직임이 가장 높은 영상 구간
    vids = [c for c in cands if c["kind"] == "video"] or cands
    hook_c = max(vids, key=rank)
    hook_len = min(HOOK_SEC, body)
    used: dict[int, list[tuple[float, float]]] = {}

    def take(c: dict, want: float) -> dict | None:
        """구간 c에서 아직 쓰지 않은 want초(원본 기준) 창을 잘라낸다."""
        if c["kind"] == "image":
            n_used = len(used.get(c["media_id"], []))
            if n_used >= 1:
                return None
            used.setdefault(c["media_id"], []).append((0, 0))
            return {**c, "w_start": 0.0, "w_len": want, "variant": n_used}
        free_start = c["start"]
        for (u0, u1) in sorted(used.get(c["media_id"], [])):
            if u1 <= free_start or u0 >= c["end"]:
                continue
            if u0 - free_start >= min(want, 0.8):
                break
            free_start = max(free_start, u1)
        avail = c["end"] - free_start
        nxt = [u0 for (u0, u1) in used.get(c["media_id"], []) if u0 >= free_start and u0 < c["end"]]
        if nxt:
            avail = min(nxt) - free_start
        if avail < 0.8:
            return None
        w = min(want, avail)
        used.setdefault(c["media_id"], []).append((free_start, free_start + w))
        return {**c, "w_start": free_start, "w_len": w, "avail": avail, "variant": 0}

    hook_win = take(hook_c, hook_len) or {**hook_c, "w_start": hook_c["start"], "w_len": hook_c["len"], "variant": 0}

    # 2) 본문 장면: 점수 높은 구간부터 컷 길이만큼 잘라 필요한 개수를 채운 뒤, 촬영 순서대로 배치(스토리 흐름 유지)
    n_body = max(1, round((body - hook_len) / cut))
    ranked = sorted(cands, key=rank, reverse=True)
    wins: list[dict] = []
    for _round in range(6):
        added = False
        for c in ranked:
            if len(wins) >= n_body:
                break
            w = take(c, cut)
            if w:
                wins.append(w)
                added = True
        if len(wins) >= n_body or not added:
            break
    if not wins:
        wins = [hook_win]
    wins.sort(key=lambda w: (w["order"], w["w_start"]))

    # 장면별 길이 배분: 원본이 짧은 장면은 짧게, 남는 시간은 여유 있는 장면에 배분(과도한 슬로모션 방지)
    remaining = body - hook_len
    durs = [0.0] * len(wins)
    left = remaining
    phases = [
        [w["w_len"] if w["kind"] == "video" else max(3.0, cut * 1.5) for w in wins],          # 원래 속도
        [w["w_len"] / 0.8 if w["kind"] == "video" else max(4.5, cut * 2) for w in wins],      # 최대 0.8배속
    ]
    for caps in phases:
        open_idx = [i for i in range(len(wins)) if caps[i] - durs[i] > 1e-3]
        while open_idx and left > 1e-3:
            share = left / len(open_idx)
            nxt = []
            for i in open_idx:
                add = min(share, caps[i] - durs[i])
                durs[i] += add
                left -= add
                if caps[i] - durs[i] > 1e-3:
                    nxt.append(i)
            open_idx = nxt
    if left > 1e-3:  # 원본 영상이 전체적으로 부족 → 균등하게 늘림(느린 재생)
        durs = [d + left / len(durs) for d in durs]
        notes.append("원본 영상 길이가 부족해 일부 장면을 느리게 재생했습니다. 추가 촬영을 권장합니다.")
    if len(wins) < n_body:
        notes.append(f"사용 가능한 장면이 {len(wins)}개라 장면 수를 줄이고 컷 길이를 늘렸습니다.")

    scenes = [_scene(hook_win, hook_len, "hook", st)]
    for i, (w, d) in enumerate(zip(wins, durs)):
        scenes.append(_scene(w, d, "body", st, variant=i + w.get("variant", 0)))

    # 3) 자막 배치
    # 실제 장면 수에 맞춰 자막을 고르게 다시 배치(문구 손실·반복 방지)
    lines = [c for c in (copy.get("captions") or []) if c]
    body_scenes = scenes[1:]
    for s in body_scenes:
        s["caption"] = ""
    lines = lines[:len(body_scenes)]
    for i, line in enumerate(lines):
        body_scenes[min(len(body_scenes) - 1, round(i * len(body_scenes) / len(lines)))]["caption"] = line
    scenes[0]["caption"] = ""

    # 음성 자막: 선택된 원본 구간과 겹치는 음성 인식 결과를 출력 시간으로 옮긴다
    speech = []
    t = 0.0
    for s in scenes:
        segs = transcripts.get(str(s["media_id"]), [])
        src_len = s["dur"] * s["speed"]
        for g in segs:
            a, b = max(g["start"], s["src_start"]), min(g["end"], s["src_start"] + src_len)
            if b - a > 0.4:
                speech.append({"start": round(t + (a - s["src_start"]) / s["speed"], 2),
                               "end": round(t + (b - s["src_start"]) / s["speed"], 2), "text": g["text"]})
        t += s["dur"]

    cap_style = dict(CAPTION_STYLES[st["cap"]])
    if pattern.get("caption_position") in ("top", "middle", "bottom"):
        cap_style["pos"] = pattern["caption_position"]
        notes.append(f"참고 영상의 자막 위치({pattern['caption_position']}) 반영")

    plan = {
        "version": 1, "style": style, "style_name": st["name"], "duration": duration,
        "title": copy.get("title", ""), "concept": copy.get("concept", ""),
        "hook_text": copy.get("hook_text", ""), "cta_text": copy.get("cta_text", ""),
        "narration": copy.get("narration", ""), "hashtags": copy.get("hashtags", []),
        "copy_engine": copy.get("engine", "rule"),
        "story": st["story"], "transition": st["trans"], "color": list(st["color"]),
        "caption_style": cap_style, "scenes": scenes, "speech_captions": speech,
        "end_card": {"sec": end_sec, "name": biz["name"], "address": biz.get("address", ""),
                     "phone": biz.get("phone", ""), "website": biz.get("website", ""),
                     "logo": biz.get("logo_path", "")},
        "music": ({"id": music["id"], "title": music["title"], "path": music["path"],
                   "license": f"{music['license_source']} / {music['license_terms']}",
                   "volume": 0.18 if speech else 0.32} if music else None),
        "source_volume": 1.0 if (speech or style == "asmr" or not music) else 0.35,
        "benchmark": {k: pattern.get(k) for k in ("count", "scope", "ref_ids", "avg_cut_sec", "hook_type", "story_structure")},
        "notes": notes,
    }
    return plan


def _scene(w: dict, dur: float, role: str, st: dict, variant: int = 0) -> dict:
    speed = 1.0
    if w["kind"] == "video":
        if st["name"] in ("시네마틱형", "감성형") and w["w_len"] >= dur * 0.75:
            speed = 0.75  # 슬로모션 느낌
        if w["w_len"] < dur * speed:
            speed = max(0.5, w["w_len"] / dur)  # 원본이 짧으면 살짝 느리게 재생해 길이 확보
        start = w["w_start"]
    else:
        start = 0.0
    return {
        "media_id": w["media_id"], "kind": w["kind"], "path": w["path"], "key": w["key"],
        "src_start": round(start, 3), "dur": round(dur, 3), "speed": round(speed, 3),
        "center_x": w["center_x"], "role": role, "brightness": round(w.get("brightness", 120), 1),
        "zoom": st["zoom"] * (1.6 if w["kind"] == "image" else 1.0), "zoom_dir": "in" if variant % 2 == 0 else "out",
    }


def retime(plan: dict, new_duration: int) -> dict:
    """영상 길이 변경(장면 비율 유지)."""
    old = plan["duration"]
    end = plan["end_card"]["sec"]
    f = (new_duration - end) / max(1e-6, (old - end))
    for s in plan["scenes"]:
        s["dur"] = round(s["dur"] * f, 3)
    plan["duration"] = new_duration
    plan["speech_captions"] = [
        {**c, "start": round(c["start"] * f, 2), "end": round(c["end"] * f, 2)} for c in plan.get("speech_captions", [])
    ]
    return plan
