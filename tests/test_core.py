from app import auth
from app.services import analyzer, copywriter, planner


def test_password_hash():
    h = auth.hash_password("abcdefgh")
    assert auth.verify_password("abcdefgh", h)
    assert not auth.verify_password("wrong", h)


def test_region_and_wrap():
    assert copywriter.region_of("서울 마포구 망원동 1-2") == "망원동"
    assert copywriter.region_of("") == ""
    assert "\n" in copywriter.wrap_ko("아주 긴 문장을 여러 줄로 나눠서 보여줍니다", 8)


def test_rule_copy_does_not_invent_facts():
    biz = {"name": "테스트카페", "industry": "cafe", "address": "부산 해운대구 우동", "products": "라떼, 케이크"}
    c = copywriter.rule_based(biz, {"id": 1, "purpose": "visit", "duration": 30, "highlights": ""}, 8)
    text = " ".join([c["hook_text"], c["cta_text"], *c["captions"]])
    for banned in ("원", "%", "할인", "최고", "1등", "후기"):
        assert banned not in text, banned
    assert len([x for x in c["captions"] if x]) == len(set(x for x in c["captions"] if x))  # 반복 없음


def test_analyzer_flags_bad_segments(media_dir):
    a = analyzer.analyze_video(str(media_dir / "clip.mp4"))
    segs = a["segments"]
    dark = [s for s in segs if 3.0 <= s["start"] < 6.0]
    blur = [s for s in segs if 6.0 <= s["start"] < 9.0]
    assert dark and all("너무 어두움" in s["issues"] for s in dark)
    assert blur and all("흐림(초점 불량)" in s["issues"] for s in blur)
    assert a["overall"]["usable_segments"] >= 2


def test_plan_respects_duration(media_dir):
    a = analyzer.analyze_video(str(media_dir / "clip.mp4"))
    img = analyzer.analyze_image(str(media_dir / "photo.jpg"))
    media = [{"id": 1, "kind": "video", "path": str(media_dir / "clip.mp4"), "analysis": a},
             {"id": 2, "kind": "image", "path": str(media_dir / "photo.jpg"), "analysis": img}]
    biz = {"name": "가게", "industry": "self", "address": "", "phone": "", "website": "", "products": "", "logo_path": ""}
    for dur in (15, 30):
        copy = copywriter.rule_based(biz, {"id": 1, "purpose": "visit", "duration": dur}, 6)
        p = planner.build_plan(order={"id": 1, "duration": dur}, biz=biz, media_list=media, style="trend",
                               duration=dur, pattern={}, copy=copy, music=None, transcripts={})
        total = sum(s["dur"] for s in p["scenes"]) + p["end_card"]["sec"]
        assert abs(total - dur) < 0.05
        # 어두운/흐린 구간(3~9초)은 사용하지 않음
        for s in p["scenes"]:
            if s["kind"] == "video":
                end = s["src_start"] + s["dur"] * s["speed"]
                assert not (3.0 < s["src_start"] + 0.1 < 9.0) or end <= 3.0


def test_production_requires_secrets(monkeypatch):
    from app import config
    monkeypatch.setattr(config, "APP_ENV", "production")
    monkeypatch.setattr(config, "SECRET_KEY", "dev-secret-change-me")
    monkeypatch.setattr(config, "ADMIN_PASSWORD", "")
    assert len(config.production_problems()) == 2
    monkeypatch.setattr(config, "SECRET_KEY", "x" * 40)
    monkeypatch.setattr(config, "ADMIN_PASSWORD", "abcd1234")
    assert config.production_problems() == []
