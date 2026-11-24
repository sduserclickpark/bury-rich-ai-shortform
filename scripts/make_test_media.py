"""테스트용 원본 영상/사진 생성 (실제 스마트폰 영상이 없을 때 파이프라인 검증용).

- 가로 1920x1080 영상: 정상 장면, 어두운 장면, 흔들리는 장면, 흐린 장면, 중복 장면 포함 + 소리
- 세로 1080x1920 영상
- 사진 1장
사용: python scripts/make_test_media.py <출력폴더>
"""
import subprocess
import sys
from pathlib import Path

out = Path(sys.argv[1] if len(sys.argv) > 1 else "test_media")
out.mkdir(parents=True, exist_ok=True)


def ff(*args):
    subprocess.run(["ffmpeg", "-y", "-v", "error", *args], check=True)


parts = out / "_parts"
parts.mkdir(exist_ok=True)
enc = ["-c:v", "libx264", "-pix_fmt", "yuv420p", "-r", "30", "-c:a", "aac", "-ar", "48000", "-ac", "2"]
specs = [
    ("a", "mandelbrot=s=1920x1080:r=30", "", 4, 440),
    ("b", "testsrc2=s=1920x1080:r=30", "", 4, 523),
    ("c", "life=s=480x270:r=30:mold=10:ratio=0.2:death_color=#203040:life_color=#ffcc66,scale=1920:1080:flags=neighbor", "eq=brightness=-0.55", 3, 330),
    ("d", "mandelbrot=s=2200x1300:r=30", "crop=1920:1080:x='140+110*sin(t*23)+60*sin(t*41)':y='110+90*cos(t*19)+40*sin(t*53)'", 3, 600),
    ("e", "gradients=s=1920x1080:r=30:speed=0.05", "boxblur=20:3", 3, 700),
    ("f", "mandelbrot=s=1920x1080:r=30", "", 3, 440),
    ("g", "cellauto=s=1920x1080:r=30:rule=110", "", 3, 800),
]
lst = []
for name, src, vf, dur, freq in specs:
    p = parts / f"{name}.mp4"
    args = ["-f", "lavfi", "-t", str(dur), "-i", src, "-f", "lavfi", "-t", str(dur), "-i", f"sine=f={freq}:sample_rate=48000"]
    if vf:
        args += ["-vf", vf]
    ff(*args, *enc, "-shortest", str(p))
    lst.append(p)
(parts / "list.txt").write_text("".join(f"file '{p.name}'\n" for p in lst))
ff("-f", "concat", "-safe", "0", "-i", str(parts / "list.txt"), *enc, str(out / "phone_landscape.mp4"))

ff("-f", "lavfi", "-t", "8", "-i", "mandelbrot=s=1080x1920:r=30", "-f", "lavfi", "-t", "8", "-i",
   "sine=f=500:sample_rate=48000", "-vf", "hue=h=t*20", *enc, "-shortest", str(out / "phone_portrait.mp4"))

from PIL import Image, ImageDraw  # noqa: E402

img = Image.new("RGB", (1600, 1200), (40, 30, 20))
d = ImageDraw.Draw(img)
for i in range(0, 1200, 8):
    d.line([(0, i), (1600, i)], fill=(60 + i // 12, 40 + i // 20, 20))
d.ellipse([500, 300, 1100, 900], fill=(230, 180, 90), outline=(255, 255, 255), width=12)
d.ellipse([650, 450, 950, 750], fill=(180, 60, 40))
img.save(out / "photo.jpg", quality=92)

logo = Image.new("RGBA", (400, 400), (0, 0, 0, 0))
ld = ImageDraw.Draw(logo)
ld.ellipse([10, 10, 390, 390], fill=(201, 162, 75, 255))
ld.ellipse([60, 60, 340, 340], fill=(11, 11, 11, 255))
ld.rectangle([150, 120, 250, 280], fill=(201, 162, 75, 255))
logo.save(out / "logo.png")
for p in parts.iterdir():
    p.unlink()
parts.rmdir()
print("created:", sorted(x.name for x in out.iterdir()))
