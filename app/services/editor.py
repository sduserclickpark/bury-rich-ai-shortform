"""FFmpeg 기반 숏폼 렌더링 엔진.

순서: 장면별 클립 제작(세로 크롭·색보정·확대/축소·배속) → 이어 붙이기(컷/페이드)
     → 자막(ASS)·로고·엔딩 카드·배경음악 합성 → 1080x1920 H.264 MP4
"""
from __future__ import annotations

import shutil
import time
from pathlib import Path

from .. import config
from .copywriter import wrap_ko
from .ffmpeg_util import probe, run

W, H, FPS = config.OUT_W, config.OUT_H, config.OUT_FPS
XF = 0.35  # 페이드 전환 길이(초)
X264 = ["-c:v", "libx264", "-preset", "veryfast", "-crf", "18", "-pix_fmt", "yuv420p", "-r", str(FPS)]
AAC = ["-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2"]


def _fesc(p) -> str:
    """필터 그래프 안에서 쓰는 경로 이스케이프."""
    return str(p).replace("\\", "/").replace(":", "\\:").replace("'", "\\'").replace(",", "\\,")


def _hdr_chain(info: dict) -> str:
    if info.get("hdr"):
        return ("zscale=t=linear:npl=100,format=gbrpf32le,zscale=p=bt709,tonemap=hable:desat=0,"
                "zscale=t=bt709:m=bt709:r=tv,format=yuv420p,")
    return ""


def _crop_chain(src_w: int, src_h: int, center_x: float, image: bool) -> str:
    """주요 피사체(center_x) 중심으로 9:16 크롭."""
    target = W / H
    aspect = src_w / max(1, src_h)
    if aspect > target:  # 가로가 넓음 → 좌우를 자름
        cw = int(src_h * target) // 2 * 2
        x = int(min(max(0, center_x * src_w - cw / 2), src_w - cw))
        return f"crop={cw}:{src_h // 2 * 2}:{x}:0,"
    if aspect < target * 0.98:  # 세로가 더 김 → 위아래를 자름(가운데)
        ch = int(src_w / target) // 2 * 2
        y = (src_h - ch) // 2
        return f"crop={src_w // 2 * 2}:{ch}:0:{y},"
    return ""


def _color_chain(color: list, brightness: float) -> str:
    b, c, s, g = color
    # 자동 노출 보정: 어두운 장면은 감마를 올리고 밝은 장면은 살짝 낮춘다
    if brightness < 90:
        g *= 1.0 + min(0.35, (90 - brightness) / 150)
    elif brightness > 200:
        g *= 0.92
    return f"eq=brightness={b:.3f}:contrast={c:.3f}:saturation={s:.3f}:gamma={g:.3f},"


def _zoom_chain(zoom: float, direction: str, dur: float) -> str:
    """부드러운 확대/축소: 프레임마다 크기를 키운 뒤 가운데를 1080x1920으로 잘라낸다."""
    if zoom <= 0:
        return f"scale={W}:{H}:flags=lanczos,"
    if direction == "in":
        z = f"(1+{zoom}*t/{dur:.3f})"
    else:
        z = f"(1+{zoom}-{zoom}*t/{dur:.3f})"
    return (f"scale={W}:{H}:flags=lanczos,"
            f"scale=w='trunc({W}*{z}/2)*2':h='trunc({H}*{z}/2)*2':eval=frame:flags=bicubic,"
            f"crop={W}:{H}:(in_w-out_w)/2:(in_h-out_h)/2,")


def render_scene(scene: dict, out: Path, color: list, extra: float = 0.0) -> None:
    dur = scene["dur"] + extra
    info = probe(scene["path"]) if scene["kind"] == "video" else None
    if scene["kind"] == "image":
        import cv2
        img = cv2.imread(scene["path"])
        sh, sw = img.shape[:2]
        vf = (_crop_chain(sw, sh, scene["center_x"], True) + _color_chain(color, scene["brightness"])
              + _zoom_chain(scene["zoom"], scene["zoom_dir"], dur) + f"fps={FPS},format=yuv420p,setsar=1")
        cmd = ["ffmpeg", "-y", "-v", "error", "-loop", "1", "-framerate", str(FPS), "-t", f"{dur:.3f}", "-i", scene["path"],
               "-f", "lavfi", "-t", f"{dur:.3f}", "-i", "anullsrc=r=48000:cl=stereo",
               "-filter_complex", f"[0:v]{vf}[v]", "-map", "[v]", "-map", "1:a", *X264, *AAC,
               "-t", f"{dur:.3f}", str(out)]
        run(cmd)
        return

    speed = scene["speed"]
    start = scene["src_start"]
    src_len = dur * speed
    total = info["duration"]
    if start + src_len > total:  # 원본 범위를 넘지 않도록 조정
        start = max(0.0, total - src_len)
        if start == 0.0 and src_len > total:
            speed = max(0.5, total / dur)
            src_len = dur * speed
    vf = (_hdr_chain(info) + _crop_chain(info["width"], info["height"], scene["center_x"], False)
          + _color_chain(color, scene["brightness"]) + _zoom_chain(scene["zoom"], scene["zoom_dir"], dur)
          + f"setpts=(PTS-STARTPTS)/{speed:.4f},fps={FPS},format=yuv420p,setsar=1")
    if info["has_audio"]:
        at = []
        sp = speed
        while sp < 0.5:
            at.append("atempo=0.5")
            sp /= 0.5
        at.append(f"atempo={sp:.4f}")
        af = f"[0:a]asetpts=PTS-STARTPTS,{','.join(at)},aresample=48000,aformat=channel_layouts=stereo,apad[a]"
        amap = ["-map", "[a]"]
        inputs = []
    else:
        af = None
        inputs = ["-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo"]
        amap = ["-map", "1:a"]
    fc = f"[0:v]{vf}[v]" + (f";{af}" if af else "")
    cmd = ["ffmpeg", "-y", "-v", "error", "-ss", f"{start:.3f}", "-t", f"{src_len + 0.05:.3f}", "-i", scene["path"],
           *inputs, "-filter_complex", fc, "-map", "[v]", *amap, *X264, *AAC, "-t", f"{dur:.3f}", str(out)]
    run(cmd)


def render_end_card(plan: dict, out: Path) -> None:
    dur = plan["end_card"]["sec"]
    cmd = ["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-t", f"{dur:.3f}",
           "-i", f"color=c=0x0B0B0B:s={W}x{H}:r={FPS}",
           "-f", "lavfi", "-t", f"{dur:.3f}", "-i", "anullsrc=r=48000:cl=stereo",
           "-vf", "format=yuv420p,setsar=1", "-map", "0:v", "-map", "1:a", *X264, *AAC, str(out)]
    run(cmd)


# ---------------- 자막(ASS) ----------------

def _ass_color(rgb: str, alpha: str = "00") -> str:
    rgb = rgb.lstrip("#")
    return f"&H{alpha}{rgb[4:6]}{rgb[2:4]}{rgb[0:2]}".upper()


def _ts(t: float) -> str:
    t = max(0.0, t)
    h = int(t // 3600)
    m = int(t % 3600 // 60)
    s = t % 60
    return f"{h}:{m:02d}:{s:05.2f}"


def _esc(text: str) -> str:
    return text.replace("\\", "＼").replace("{", "(").replace("}", ")").replace("\n", "\\N")


def build_ass(plan: dict, scene_starts: list[float]) -> str:
    cs = plan["caption_style"]
    font = config.FONT_NAME
    size = cs["size"]
    pos_y = {"top": 380, "middle": 1150, "bottom": 1480}[cs.get("pos", "middle")]
    box = 3 if cs.get("box") else 1
    white, accent, outline = _ass_color(cs["color"]), _ass_color(cs["accent"]), _ass_color(cs["outline"])
    back = "&H64000000" if cs.get("box") else "&H00000000"
    gold = _ass_color("C9A24B")
    hdr = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {W}
PlayResY: {H}
WrapStyle: 2
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Hook,{font},{int(size * 1.25)},{accent},{white},{outline},&H80000000,-1,0,0,0,100,100,0,0,1,7,3,8,60,60,330,1
Style: Cap,{font},{size},{white},{white},{outline},{back},-1,0,0,0,100,100,0,0,{box},5,2,5,70,70,0,1
Style: Speech,{font},{int(size * 0.72)},&H00FFFFFF,&H00FFFFFF,&H00000000,&H78000000,-1,0,0,0,100,100,0,0,3,4,0,2,60,60,170,1
Style: EndName,{font},96,{gold},{gold},&H00000000,&H00000000,-1,0,0,0,100,100,2,0,1,3,0,5,60,60,0,1
Style: EndInfo,{font},50,&H00FFFFFF,&H00FFFFFF,&H00000000,&H00000000,0,0,0,0,100,100,0,0,1,2,0,5,70,70,0,1
Style: EndCta,{font},62,&H00FFFFFF,&H00FFFFFF,&H00000000,&H00000000,-1,0,0,0,100,100,0,0,1,3,0,5,60,60,0,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    ev = []
    scenes = plan["scenes"]
    # 후킹 문구(첫 장면): 팝 애니메이션
    if plan.get("hook_text"):
        hook_end = scene_starts[1] if len(scene_starts) > 1 else scenes[0]["dur"]
        ev.append(f"Dialogue: 2,{_ts(0)},{_ts(hook_end)},Hook,,0,0,0,,"
                  f"{{\\fad(80,120)\\fscx130\\fscy130\\t(0,220,\\fscx100\\fscy100)}}{_esc(wrap_ko(plan['hook_text'], 11))}")
    has_speech = bool(plan.get("speech_captions"))
    for i, s in enumerate(scenes):
        if i == 0 or not s.get("caption"):
            continue
        st0 = scene_starts[i]
        st1 = st0 + s["dur"]
        y = pos_y if not has_speech or pos_y < 1300 else 1150
        ev.append(f"Dialogue: 1,{_ts(st0 + 0.08)},{_ts(st1 - 0.05)},Cap,,0,0,0,,"
                  f"{{\\an5\\pos({W // 2},{y})\\fad(100,100)\\fscx112\\fscy112\\t(0,160,\\fscx100\\fscy100)}}{_esc(wrap_ko(s['caption'], 12))}")
    for c in plan.get("speech_captions", []):
        ev.append(f"Dialogue: 0,{_ts(c['start'])},{_ts(c['end'])},Speech,,0,0,0,,{_esc(wrap_ko(c['text'], 18))}")

    # 엔딩 카드(브랜드)
    ec = plan["end_card"]
    t0 = sum(s["dur"] for s in scenes)
    t1 = t0 + ec["sec"]
    logo_shift = 200 if ec.get("logo") else 0
    ev.append(f"Dialogue: 3,{_ts(t0)},{_ts(t1)},EndName,,0,0,0,,{{\\an5\\pos({W // 2},{820 + logo_shift})\\fad(250,0)}}{_esc(wrap_ko(ec['name'], 10))}")
    ev.append(f"Dialogue: 3,{_ts(t0)},{_ts(t1)},EndInfo,,0,0,0,,{{\\an5\\pos({W // 2},{700 + logo_shift - 10})\\c{gold}\\fad(250,0)}}━━━━━━")
    info_lines = [x for x in [ec.get("address"), ec.get("phone"), ec.get("website")] if x]
    y = 1000 + logo_shift
    for line in info_lines:
        ev.append(f"Dialogue: 3,{_ts(t0 + 0.2)},{_ts(t1)},EndInfo,,0,0,0,,{{\\an5\\pos({W // 2},{y})\\fad(250,0)}}{_esc(wrap_ko(line, 22))}")
        y += 80 * (1 + wrap_ko(line, 22).count("\n"))
    if plan.get("cta_text"):
        ev.append(f"Dialogue: 3,{_ts(t0 + 0.4)},{_ts(t1)},EndCta,,0,0,0,,{{\\an5\\pos({W // 2},{y + 90})\\fad(250,0)}}{_esc(wrap_ko(plan['cta_text'], 16))}")
    ev.append(f"Dialogue: 3,{_ts(t0)},{_ts(t1)},EndInfo,,0,0,0,,{{\\an2\\pos({W // 2},1800)\\fs34\\c{gold}}}BURY RICH AI SHORTFORM STUDIO")
    return hdr + "\n".join(ev) + "\n"


# ---------------- 전체 렌더링 ----------------

def render(plan: dict, work: Path, out_path: Path, log=lambda p, m: None) -> dict:
    t_start = time.time()
    work.mkdir(parents=True, exist_ok=True)
    scenes = plan["scenes"]
    fade = plan.get("transition") == "fade"
    clips = []
    n = len(scenes)
    for i, s in enumerate(scenes):
        log(50 + int(30 * i / max(1, n)), f"장면 {i + 1}/{n} 편집 중")
        p = work / f"scene_{i:02d}.mp4"
        render_scene(s, p, plan["color"], extra=XF if fade else 0.0)
        clips.append(p)
    endp = work / "end.mp4"
    render_end_card(plan, endp)
    clips.append(endp)

    starts, t = [], 0.0
    for s in scenes:
        starts.append(t)
        t += s["dur"]
    total = t + plan["end_card"]["sec"]

    log(82, "장면 연결 중")
    joined = work / "joined.mp4"
    if fade:
        inputs, fc, prev_v, prev_a = [], [], "[0:v]", "[0:a]"
        for c in clips:
            inputs += ["-i", str(c)]
        acc = 0.0
        for i in range(1, len(clips)):
            acc += (scenes[i - 1]["dur"])
            off = acc  # 각 장면이 XF 만큼 길게 렌더링되어 있으므로 offset = 누적 길이
            fc.append(f"{prev_v}[{i}:v]xfade=transition=fade:duration={XF}:offset={off:.3f}[v{i}]")
            fc.append(f"{prev_a}[{i}:a]acrossfade=d={XF}:c1=tri:c2=tri[a{i}]")
            prev_v, prev_a = f"[v{i}]", f"[a{i}]"
        run(["ffmpeg", "-y", "-v", "error", *inputs, "-filter_complex", ";".join(fc),
             "-map", prev_v, "-map", prev_a, *X264, *AAC, str(joined)])
    else:
        lst = work / "list.txt"
        lst.write_text("".join(f"file '{c.name}'\n" for c in clips))
        run(["ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0", "-i", str(lst), "-c", "copy", str(joined)])

    log(88, "자막·로고·음악 합성 중")
    ass = work / "subs.ass"
    ass.write_text(build_ass(plan, starts), encoding="utf-8")
    ec = plan["end_card"]
    end_t0 = sum(s["dur"] for s in scenes)
    inputs = ["-i", str(joined)]
    fc = [f"[0:v]ass=filename={_fesc(ass)}:fontsdir={_fesc(config.FONT_DIR)}[vs]"]
    vlast = "[vs]"
    idx = 1
    if ec.get("logo") and Path(ec["logo"]).exists():
        inputs += ["-loop", "1", "-t", f"{total:.3f}", "-i", ec["logo"]]
        fc.append(f"[{idx}:v]scale=360:360:force_original_aspect_ratio=decrease,format=rgba[lg]")
        fc.append(f"{vlast}[lg]overlay=x=(W-w)/2:y=560-h/2:enable='gte(t,{end_t0:.2f})'[vl]")
        vlast = "[vl]"
        idx += 1
    fc.append(f"{vlast}format=yuv420p[vout]")
    src_vol = plan.get("source_volume", 1.0)
    music = plan.get("music")
    if music and Path(music["path"]).exists():
        inputs += ["-stream_loop", "-1", "-i", music["path"]]
        mv = music.get("volume", 0.3)
        fc.append(f"[0:a]volume={src_vol}[src]")
        fc.append(f"[{idx}:a]atrim=0:{total:.3f},asetpts=PTS-STARTPTS,volume={mv},"
                  f"afade=t=in:d=0.5,afade=t=out:st={max(0, total - 1.5):.3f}:d=1.5,aresample=48000,aformat=channel_layouts=stereo[bgm]")
        fc.append("[bgm][src]sidechaincompress=threshold=0.05:ratio=6:attack=20:release=300[duck]")
        fc.append("[duck][src]amix=inputs=2:duration=first:normalize=0,loudnorm=I=-14:TP=-1.5:LRA=11[aout]")
    else:
        fc.append(f"[0:a]volume={src_vol},loudnorm=I=-14:TP=-1.5:LRA=11[aout]")
    tmp_out = work / "final.mp4"
    run(["ffmpeg", "-y", "-v", "error", *inputs, "-filter_complex", ";".join(fc),
         "-map", "[vout]", "-map", "[aout]", "-c:v", "libx264", "-preset", "medium", "-crf", "20",
         "-maxrate", "10M", "-bufsize", "20M", "-profile:v", "high", "-level", "4.2", "-pix_fmt", "yuv420p", "-r", str(FPS),
         *AAC, "-t", f"{total:.3f}", "-movflags", "+faststart", str(tmp_out)], timeout=3600)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(tmp_out), out_path)
    thumb = out_path.with_suffix(".jpg")
    run(["ffmpeg", "-y", "-v", "error", "-ss", "1.0", "-i", str(out_path), "-frames:v", "1",
         "-vf", "scale=540:-2", "-q:v", "3", str(thumb)])
    final = probe(out_path)
    return {"render_seconds": round(time.time() - t_start, 1), "output": final, "thumb": str(thumb)}
