"""고객 원본 영상 분석 (무료, 서버 CPU에서 실행).

실제로 측정하는 항목:
- 밝기, 선명도(초점), 카메라 흔들림, 움직임 양, 장면 전환 지점
- 중복 장면(지각 해시 비교), 피사체 위치(시각적 주목도 지도) → 세로 크롭 중심
- 구간별 활용 점수, 불필요 구간(너무 어둡거나 흐리거나 흔들림)
- 음성 유무(음량) / 음성 인식(설치 시)

사물/음식/인물의 '의미' 인식(이것이 김치찌개인지 등)은 Claude 비전 API가 설정된 경우에만 수행하며,
설정되지 않은 경우 해당 항목은 '미분석'으로 표시한다(임의로 지어내지 않음).
"""
from __future__ import annotations

import subprocess
from pathlib import Path

import cv2
import numpy as np

from .ffmpeg_util import probe

SAMPLE_FPS = 4.0
AW = 192  # 분석용 프레임 가로 크기


def _read_frames(path: str, info: dict) -> tuple[np.ndarray, float]:
    """ffmpeg로 회전 보정된 저해상도 회색조 프레임을 읽는다."""
    w, h = info["width"], info["height"]
    ah = max(2, int(round(AW * h / max(w, 1) / 2)) * 2)
    vf = f"fps={SAMPLE_FPS},scale={AW}:{ah}:flags=area,format=gray"
    cmd = ["ffmpeg", "-v", "error", "-i", path, "-vf", vf, "-f", "rawvideo", "-"]
    raw = subprocess.run(cmd, capture_output=True, timeout=1800).stdout
    n = len(raw) // (AW * ah)
    frames = np.frombuffer(raw[: n * AW * ah], dtype=np.uint8).reshape(n, ah, AW)
    return frames, SAMPLE_FPS


def _audio_levels(path: str, duration: float) -> np.ndarray:
    """0.25초 단위 음량(RMS, dBFS)."""
    cmd = ["ffmpeg", "-v", "error", "-i", path, "-vn", "-ac", "1", "-ar", "8000", "-f", "s16le", "-"]
    raw = subprocess.run(cmd, capture_output=True, timeout=600).stdout
    if not raw:
        return np.array([])
    a = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
    win = 2000
    n = len(a) // win
    if n == 0:
        return np.array([])
    rms = np.sqrt(np.mean(a[: n * win].reshape(n, win) ** 2, axis=1) + 1e-12)
    return 20 * np.log10(rms + 1e-9)


def _saliency(gray: np.ndarray) -> np.ndarray:
    """Spectral Residual 방식의 시각적 주목도 지도."""
    img = cv2.resize(gray, (64, 64)).astype(np.float32)
    f = np.fft.fft2(img)
    log_amp = np.log(np.abs(f) + 1e-6)
    phase = np.angle(f)
    resid = log_amp - cv2.blur(log_amp, (3, 3))
    sal = np.abs(np.fft.ifft2(np.exp(resid + 1j * phase))) ** 2
    sal = cv2.GaussianBlur(sal, (9, 9), 2.5)
    return cv2.resize(sal, (gray.shape[1], gray.shape[0]))


def _dhash(gray: np.ndarray) -> int:
    small = cv2.resize(gray, (9, 8), interpolation=cv2.INTER_AREA)
    bits = (small[:, 1:] > small[:, :-1]).flatten()
    return int("".join("1" if b else "0" for b in bits), 2)


def hamming(a: int, b: int) -> int:
    return bin(a ^ b).count("1")


def detect_cuts(frames: np.ndarray, threshold: float = 0.45) -> list[int]:
    """히스토그램 차이 기반 장면 전환 프레임 인덱스."""
    cuts = []
    prev = None
    for i, f in enumerate(frames):
        hist = cv2.calcHist([f], [0], None, [32], [0, 256])
        cv2.normalize(hist, hist)
        if prev is not None:
            d = cv2.compareHist(prev, hist, cv2.HISTCMP_BHATTACHARYYA)
            if d > threshold:
                cuts.append(i)
        prev = hist
    return cuts


def analyze_video(path: str) -> dict:
    info = probe(path)
    if not info.get("has_video"):
        raise ValueError("영상 트랙이 없는 파일입니다.")
    frames, fps = _read_frames(path, info)
    if len(frames) == 0:
        raise ValueError("영상 프레임을 읽을 수 없습니다.")
    n = len(frames)

    brightness = frames.reshape(n, -1).mean(axis=1)
    sharp = np.array([cv2.Laplacian(f, cv2.CV_64F).var() for f in frames])

    # 흔들림: 연속 프레임 간 전역 이동량(위상 상관) / 움직임: 프레임 차이
    # 흔들림 = 전역 이동량 중 '불규칙한(고주파) 성분'. 천천히 움직이는 패닝은 흔들림으로 보지 않는다.
    dxy = np.zeros((n, 2))
    resp = np.zeros(n)
    motion = np.zeros(n)
    win = cv2.createHanningWindow((frames.shape[2], frames.shape[1]), cv2.CV_32F)
    for i in range(1, n):
        a, b = frames[i - 1].astype(np.float32), frames[i].astype(np.float32)
        (dx, dy), r = cv2.phaseCorrelate(a, b, win)
        dxy[i] = (dx, dy)
        resp[i] = r
        motion[i] = float(np.mean(np.abs(a - b)))
    k = np.ones(3) / 3
    smooth = np.stack([np.convolve(dxy[:, j], k, mode="same") for j in range(2)], axis=1)
    shake = np.hypot(*(dxy - smooth).T) / frames.shape[2] * 100  # 화면 폭 대비 %
    shake[resp < 0.15] = np.nan  # 장면 전환 등 신뢰도 낮은 측정값 제외

    # 피사체 중심(가로 위치 0~1)
    centers = np.zeros(n)
    for i, f in enumerate(frames):
        s = _saliency(f)
        col = s.sum(axis=0)
        col = col / (col.sum() + 1e-9)
        centers[i] = float((col * np.arange(len(col))).sum() / len(col))

    cuts = detect_cuts(frames)
    hashes = [_dhash(f) for f in frames]
    levels = _audio_levels(path, info["duration"]) if info["has_audio"] else np.array([])

    # 0.5초 이상의 구간(segment) 생성: 장면 전환으로 나누고 최대 3초로 분할
    bounds = [0] + cuts + [n]
    segs = []
    max_len = int(3.0 * fps)
    for shot, (s, e) in enumerate(zip(bounds[:-1], bounds[1:])):
        k = s
        while k < e:
            ke = min(e, k + max_len)
            if (ke - k) >= int(0.5 * fps):
                segs.append((k, ke, shot))
            k = ke

    # 선명도 기준: 같은 영상 안의 상위값과 비교하되, 너무 높은 기준이 되지 않도록 상한을 둔다
    sharp_ref = min(float(np.percentile(sharp, 90)), 600.0) + 1e-6
    segments = []
    for idx, (s, e, shot) in enumerate(segs):
        br = float(brightness[s:e].mean())
        sh = float(sharp[s:e].mean())
        sv = shake[s + 1:e]
        sv = sv[~np.isnan(sv)] if e - s > 1 else sv[:0]
        sk = float(np.median(sv)) if len(sv) else 0.0
        mo = float(motion[s + 1:e].mean()) if e - s > 1 else 0.0
        t0, t1 = s / fps, e / fps
        loud = None
        if len(levels):
            seg_l = levels[int(t0 * 4): max(int(t0 * 4) + 1, int(t1 * 4))]
            loud = float(np.mean(seg_l)) if len(seg_l) else None
        issues = []
        if br < 45:
            issues.append("너무 어두움")
        elif br > 225:
            issues.append("너무 밝음(노출 과다)")
        if sh < 25 or sh < sharp_ref * 0.08:
            issues.append("흐림(초점 불량)")
        if sk > 2.5:
            issues.append("카메라 흔들림 심함")
        # 활용 점수 0~100
        score = 50.0
        score += min(25.0, 25.0 * sh / sharp_ref)  # 기준 이상이면 만점
        score -= max(0.0, (sk - 1.0) * 8)
        score -= 20 if br < 45 or br > 225 else 0
        score += min(10.0, mo * 0.8)          # 적당한 움직임은 가산
        score -= 10 if mo < 0.3 else 0        # 완전 정지 화면은 감산
        score = float(np.clip(score, 0, 100))
        segments.append({
            "idx": idx, "start": round(t0, 2), "end": round(t1, 2),
            "brightness": round(br, 1), "sharpness": round(sh, 1),
            "shake": round(sk, 2), "motion": round(mo, 2),
            "loudness_db": None if loud is None else round(loud, 1),
            "center_x": round(float(np.median(centers[s:e])), 3),
            "hash": hashes[(s + e) // 2],
            "issues": issues, "score": round(score, 1), "shot": shot,
            # 어두움·흐림·흔들림은 사용하지 않음(노출 과다는 보정 가능하므로 사용)
            "usable": not any(i in issues for i in ("너무 어두움", "흐림(초점 불량)", "카메라 흔들림 심함")),
        })

    # 중복 장면 표시 (같은 장면을 여러 번 찍은 경우)
    for i, a in enumerate(segments):
        for b in segments[:i]:
            if b["shot"] != a["shot"] and "duplicate_of" not in b and hamming(a["hash"], b["hash"]) <= 6:
                a["duplicate_of"] = b["idx"]
                break

    speech_ratio = 0.0
    if len(levels):
        speech_ratio = float(np.mean(levels > -35))

    usable = [s for s in segments if s["usable"] and "duplicate_of" not in s]
    overall = {
        "duration": round(info["duration"], 2),
        "resolution": f'{info["width"]}x{info["height"]}',
        "orientation": "세로" if info["height"] > info["width"] else ("가로" if info["width"] > info["height"] else "정사각"),
        "avg_brightness": round(float(brightness.mean()), 1),
        "avg_sharpness": round(float(sharp.mean()), 1),
        "avg_shake": round(float(np.nanmedian(shake[1:])) if n > 1 and not np.all(np.isnan(shake[1:])) else 0.0, 2),
        "scene_cuts": len(cuts),
        "segments": len(segments),
        "usable_segments": len(usable),
        "duplicates": len([s for s in segments if "duplicate_of" in s]),
        "has_audio": info["has_audio"],
        "sound_ratio": round(speech_ratio, 2),
        "hdr": info.get("hdr", False),
    }
    overall["quality_score"] = round(float(np.mean([s["score"] for s in segments])) if segments else 0, 1)
    overall["guidance"] = shooting_guidance(overall, segments)
    return {"probe": info, "overall": overall, "segments": segments}


def shooting_guidance(overall: dict, segments: list[dict]) -> list[str]:
    """원본 품질이 부족할 때 고객에게 보여줄 추가 촬영 안내."""
    tips = []
    if overall["avg_brightness"] < 60:
        tips.append("영상이 어둡습니다. 조명을 켜거나 창가 쪽에서 밝게 촬영해 주세요.")
    shaky = [s for s in segments if "카메라 흔들림 심함" in s["issues"]]
    if overall["avg_shake"] > 2.0 or (segments and len(shaky) / len(segments) > 0.3):
        tips.append("카메라 흔들림이 큽니다. 두 손으로 잡거나 벽·테이블에 팔을 기대고 천천히 움직여 주세요.")
    blurry = [s for s in segments if "흐림(초점 불량)" in s["issues"]]
    if segments and len(blurry) / len(segments) > 0.3:
        tips.append("초점이 흐린 장면이 많습니다. 촬영 전 화면에서 주인공(상품/음식)을 한 번 눌러 초점을 맞춰 주세요.")
    if overall["orientation"] == "가로":
        tips.append("숏폼은 세로 화면입니다. 다음에는 스마트폰을 세로로 들고 촬영하면 더 많은 화면을 살릴 수 있습니다.")
    if overall["duration"] < 10:
        tips.append("원본 길이가 짧습니다. 매장 외관, 내부, 대표 상품 클로즈업, 손님/직원 모습을 각각 5초 이상 촬영해 주세요.")
    if overall["usable_segments"] < 4:
        tips.append("사용 가능한 장면이 부족합니다. 다양한 각도(정면·측면·위에서)로 추가 촬영해 주시면 완성도가 높아집니다.")
    return tips


def analyze_image(path: str) -> dict:
    img = cv2.imread(path, cv2.IMREAD_GRAYSCALE)
    if img is None:
        raise ValueError("이미지를 읽을 수 없습니다.")
    h, w = img.shape
    small = cv2.resize(img, (AW, max(2, int(AW * h / w))))
    sal = _saliency(small)
    col = sal.sum(axis=0)
    col = col / (col.sum() + 1e-9)
    cx = float((col * np.arange(len(col))).sum() / len(col))
    br = float(small.mean())
    sh = float(cv2.Laplacian(small, cv2.CV_64F).var())
    issues = []
    if br < 45:
        issues.append("너무 어두움")
    return {
        "probe": {"width": w, "height": h},
        "overall": {"resolution": f"{w}x{h}", "avg_brightness": round(br, 1), "avg_sharpness": round(sh, 1)},
        "segments": [{"idx": 0, "start": 0, "end": 0, "brightness": round(br, 1), "sharpness": round(sh, 1),
                      "shake": 0, "motion": 0, "center_x": round(cx, 3), "hash": _dhash(small),
                      "issues": issues, "score": 60.0, "usable": True}],
    }


def is_image(path: str) -> bool:
    return Path(path).suffix.lower() in {".jpg", ".jpeg", ".png", ".webp", ".bmp"}
