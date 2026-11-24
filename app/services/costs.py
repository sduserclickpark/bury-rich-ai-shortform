"""제작 원가 계산. 실측값과 추정값을 구분해 기록한다."""
from __future__ import annotations

from .. import config, db

# Claude API 단가 (USD / 100만 토큰). 가격 변경 시 이 표만 수정.
CLAUDE_PRICES = {
    "claude-opus-5-5": (4.0, 20.0), "claude-sonnet-5-5": (2.0, 10.0), "claude-haiku-5-5": (0.10, 0.50),
    "claude-fable-5-2": (8.0, 40.0),
}


def claude_cost_krw(usage: dict | None) -> float:
    if not usage:
        return 0.0
    pin, pout = CLAUDE_PRICES.get(usage.get("model", ""), (4.0, 20.0))
    usd = usage.get("input_tokens", 0) / 1e6 * pin + usage.get("output_tokens", 0) / 1e6 * pout
    return round(usd * config.USD_KRW, 1)


def estimate_job_krw(n_media: int, total_media_sec: float) -> dict:
    """작업 시작 전 예상 원가(승인 판단용)."""
    ai = 0.0
    if config.ANTHROPIC_API_KEY:
        ai = claude_cost_krw({"model": config.CLAUDE_MODEL, "input_tokens": 12000, "output_tokens": 2500})
    server_month = float(db.setting("server_monthly_cost_krw", "15000"))
    videos = max(1.0, float(db.setting("expected_monthly_videos", "100")))
    server = server_month / videos
    return {"ai_krw": ai, "server_krw": round(server, 1), "total_krw": round(ai + server, 1), "estimated": True}


def actual_job_cost(usage: dict | None, render_seconds: float, storage_bytes: int, price: int) -> dict:
    ai = claude_cost_krw(usage)
    server_month = float(db.setting("server_monthly_cost_krw", "15000"))
    videos = max(1.0, float(db.setting("expected_monthly_videos", "100")))
    server = server_month / videos
    storage = storage_bytes / 1e9 * 0.015 * config.USD_KRW  # 1GB·월 약 $0.015 (Cloudflare R2 기준) → 추정
    fee = price * 0.033 if price else 0.0
    items = [
        {"name": "AI 모델 사용료(Claude)", "krw": ai, "basis": "실측 토큰 × 공시 단가" if usage else "미사용(무료 규칙 엔진)", "estimated": False},
        {"name": "음성 인식", "krw": 0.0, "basis": "서버 내 무료 모델(서버비에 포함)", "estimated": False},
        {"name": "AI 음성 생성", "krw": 0.0, "basis": "V1 미사용", "estimated": False},
        {"name": "영상 렌더링·서버", "krw": round(server, 1), "basis": f"월 서버비 ÷ 월 예상 제작 편수 (렌더 {render_seconds}초)", "estimated": True},
        {"name": "저장 공간(월)", "krw": round(storage, 1), "basis": f"{storage_bytes / 1e6:.0f}MB 기준 추정", "estimated": True},
        {"name": "데이터 전송", "krw": 0.0, "basis": "Cloudflare R2/서버 기본 포함 범위 가정", "estimated": True},
        {"name": "음원 사용료", "krw": 0.0, "basis": "무료 상업용 라이선스 음원 사용 시", "estimated": True},
        {"name": "결제 수수료", "krw": round(fee, 1), "basis": "PG 수수료 3.3% 가정(결제 연동 전)", "estimated": True},
    ]
    total = round(sum(i["krw"] for i in items), 1)
    return {"items": items, "total_krw": total, "price": price, "profit_krw": round(price - total, 1),
            "render_seconds": render_seconds}


def month_ai_spend_krw() -> float:
    rows = db.q("SELECT cost_json FROM renders WHERE created_at >= date('now','start of month')")
    s = 0.0
    for r in rows:
        c = db.jload(r["cost_json"])
        for it in c.get("items", []):
            if it["name"].startswith("AI 모델"):
                s += it["krw"]
    return round(s, 1)
