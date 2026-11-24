import os
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

_TMP = tempfile.mkdtemp(prefix="brs_test_")
os.environ["DATA_DIR"] = _TMP
os.environ["ADMIN_PASSWORD"] = "admin-pass-123"
os.environ["ADMIN_EMAIL"] = "admin@test.local"
os.environ["WHISPER_MODEL"] = ""          # 테스트에서는 음성 인식 모델 다운로드 안 함
os.environ["ANTHROPIC_API_KEY"] = ""
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def ff(*args):
    subprocess.run(["ffmpeg", "-y", "-v", "error", *args], check=True)


@pytest.fixture(scope="session")
def media_dir():
    d = Path(_TMP) / "fixtures"
    d.mkdir(exist_ok=True)
    enc = ["-c:v", "libx264", "-pix_fmt", "yuv420p", "-r", "30", "-c:a", "aac", "-shortest"]
    parts = []
    for name, src, vf in [
        ("ok1", "mandelbrot=s=960x540:r=30", "null"),
        ("dark", "mandelbrot=s=960x540:r=30", "eq=brightness=-0.7"),
        ("blur", "gradients=s=960x540:r=30:speed=0.05", "boxblur=20:3"),
        ("ok2", "cellauto=s=960x540:r=30:rule=110", "null"),
        ("ok3", "testsrc2=s=960x540:r=30", "null"),
    ]:
        p = d / f"{name}.mp4"
        ff("-f", "lavfi", "-t", "3", "-i", src, "-f", "lavfi", "-t", "3", "-i", "sine=f=440", "-vf", vf, *enc, str(p))
        parts.append(p)
    (d / "list.txt").write_text("".join(f"file '{p.name}'\n" for p in parts))
    ff("-f", "concat", "-safe", "0", "-i", str(d / "list.txt"), "-c", "copy", str(d / "clip.mp4"))
    from PIL import Image
    Image.new("RGB", (800, 600), (200, 150, 80)).save(d / "photo.jpg")
    return d
