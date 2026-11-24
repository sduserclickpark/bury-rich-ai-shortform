"""FFmpeg/FFprobe 공통 함수."""
import json
import subprocess
from pathlib import Path


class FFmpegError(RuntimeError):
    pass


def run(cmd: list[str], timeout: int = 1800) -> str:
    p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    if p.returncode != 0:
        tail = "\n".join(p.stderr.strip().splitlines()[-15:])
        raise FFmpegError(f"명령 실패: {' '.join(cmd[:3])} ...\n{tail}")
    return p.stdout


def probe(path: str | Path) -> dict:
    out = run([
        "ffprobe", "-v", "error", "-print_format", "json",
        "-show_format", "-show_streams", str(path),
    ], timeout=120)
    data = json.loads(out)
    v = next((s for s in data.get("streams", []) if s.get("codec_type") == "video"), None)
    a = next((s for s in data.get("streams", []) if s.get("codec_type") == "audio"), None)
    info = {
        "duration": float(data.get("format", {}).get("duration") or 0),
        "has_video": v is not None,
        "has_audio": a is not None,
        "size": int(data.get("format", {}).get("size") or 0),
    }
    if v:
        w, h = int(v.get("width") or 0), int(v.get("height") or 0)
        rot = 0
        for sd in v.get("side_data_list", []) or []:
            if "rotation" in sd:
                rot = int(float(sd["rotation"]))
        if "rotate" in (v.get("tags") or {}):
            rot = int(v["tags"]["rotate"])
        if abs(rot) % 180 == 90:
            w, h = h, w
        fr = v.get("avg_frame_rate") or "0/1"
        try:
            n, d = fr.split("/")
            fps = float(n) / float(d) if float(d) else 0.0
        except ValueError:
            fps = 0.0
        info.update({
            "width": w, "height": h, "rotation": rot, "fps": round(fps, 3),
            "codec": v.get("codec_name"), "pix_fmt": v.get("pix_fmt"),
            "color_transfer": v.get("color_transfer", ""),
            "hdr": v.get("color_transfer", "") in ("arib-std-b67", "smpte2084"),
        })
        if not info["duration"]:
            info["duration"] = float(v.get("duration") or 0)
    return info
