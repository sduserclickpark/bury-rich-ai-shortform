"""자동 음성 인식 (무료: faster-whisper, 서버 CPU 실행).

모델 파일은 최초 1회 인터넷(Hugging Face)에서 내려받는다. 내려받을 수 없거나
WHISPER_MODEL 이 비어 있으면 음성 인식을 건너뛰고 그 사실을 기록한다(가짜 자막을 만들지 않음).
"""
from __future__ import annotations

import logging
import threading

from .. import config

log = logging.getLogger(__name__)
_model = None
_model_error: str | None = None
_lock = threading.Lock()


def _load():
    global _model, _model_error
    with _lock:
        if _model is not None or _model_error is not None:
            return _model
        if not config.WHISPER_MODEL:
            _model_error = "음성 인식이 꺼져 있습니다(WHISPER_MODEL 미설정)."
            return None
        try:
            from faster_whisper import WhisperModel
            _model = WhisperModel(config.WHISPER_MODEL, device="cpu", compute_type="int8",
                                  download_root=str(config.DATA_DIR / "models"))
        except Exception as e:  # 네트워크 차단, 미설치 등
            _model_error = f"음성 인식 모델을 불러오지 못했습니다: {type(e).__name__}"
            log.warning("ASR unavailable: %s", e)
        return _model


def status() -> dict:
    return {"model": config.WHISPER_MODEL, "loaded": _model is not None, "error": _model_error}


def transcribe(path: str) -> dict:
    """반환: {"available": bool, "segments": [{"start","end","text"}], "error"}"""
    model = _load()
    if model is None:
        return {"available": False, "segments": [], "error": _model_error}
    try:
        segs, info = model.transcribe(path, language="ko", vad_filter=True, beam_size=1,
                                      condition_on_previous_text=False)
        out = []
        for s in segs:
            text = (s.text or "").strip()
            if text and (s.no_speech_prob or 0) < 0.6:
                out.append({"start": round(s.start, 2), "end": round(s.end, 2), "text": text})
        return {"available": True, "segments": out, "language": info.language}
    except Exception as e:
        return {"available": False, "segments": [], "error": f"음성 인식 실패: {e}"}
