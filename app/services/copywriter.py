"""홍보 문구 생성.

1) 기본(무료): 고객이 입력한 정보만 조합하는 규칙 기반 문구.
2) 선택(유료): ANTHROPIC_API_KEY 가 설정되면 Claude가 장면 이미지와 입력 정보를 보고 문구를 작성.

공통 원칙: 고객이 제공하지 않은 가격·할인·효능·후기·수상 경력 등은 절대 만들지 않는다.
"""
from __future__ import annotations

import base64
import logging
import re
from pydantic import BaseModel, Field

from .. import config
from .catalog import INDUSTRIES, INDUSTRY_SHORT, INDUSTRY_TAGS, PURPOSES

log = logging.getLogger(__name__)


def region_of(address: str) -> str:
    toks = re.split(r"\s+", address or "")
    for suf in ("동", "읍", "면", "구", "군", "시"):
        for t in toks:
            t2 = re.sub(r"[^가-힣0-9]", "", t)
            if len(t2) >= 2 and t2.endswith(suf) and not t2[:-1].isdigit():
                return t2
    return ""


def split_items(text: str) -> list[str]:
    return [p.strip() for p in re.split(r"[,\n/·]+", text or "") if p.strip()][:8]


def wrap_ko(text: str, width: int = 12) -> str:
    """자막 줄바꿈(공백 기준, 한 줄 최대 width 글자)."""
    words, lines, cur = text.split(), [], ""
    for w in words:
        if cur and len(cur) + 1 + len(w) > width:
            lines.append(cur)
            cur = w
        else:
            cur = f"{cur} {w}".strip()
    if cur:
        lines.append(cur)
    return "\n".join(lines[:3])


def rule_based(biz: dict, order: dict, n_scenes: int) -> dict:
    name = biz["name"].strip()
    ind = biz["industry"]
    ind_label = INDUSTRY_SHORT.get(ind, "가게")
    region = region_of(biz.get("address", ""))
    items = split_items(biz.get("products", ""))
    highlights = split_items(order.get("highlights", ""))
    purpose = order.get("purpose", "visit")
    seed = int(order.get("id") or 0)

    hooks = []
    if region:
        hooks.append(f"{region} {ind_label} 찾고 있다면?")
    if items:
        hooks.append(f"{items[0]}, 이렇게 나옵니다")
    hooks.append(f"{name}, 딱 {order.get('duration', 30)}초만 보세요")
    if highlights:
        hooks.insert(0, highlights[0])
    hook = hooks[seed % len(hooks)] if not highlights else hooks[0]

    cta = {
        "visit": "지금 바로 방문해 보세요", "reservation": "예약·문의는 프로필 링크에서",
        "online_sale": "구매는 프로필 링크에서", "event": "행사 내용은 매장에 문의하세요",
        "recruit": "상담·등록 문의 환영합니다", "new_product": "새로운 메뉴, 직접 확인해 보세요",
        "brand": f"{name}를 기억해 주세요",
    }.get(purpose, "지금 바로 확인해 보세요")

    lines = []
    lines.append(name)
    lines += highlights[1:] if highlights else []
    lines += items
    if region:
        lines.append(f"{region}에 있어요")
    # 같은 문구가 반복되지 않도록 장면 전체에 고르게 배치(나머지 장면은 자막 없이 영상만)
    captions = [""] * max(0, n_scenes)
    lines = lines[:n_scenes]
    for i, line in enumerate(lines):
        captions[min(n_scenes - 1, round(i * n_scenes / len(lines)))] = line

    tags = []
    if region:
        tags += [region, f"{region}{INDUSTRY_TAGS.get(ind, ['가게'])[0]}"]
    tags += [re.sub(r"\s+", "", name)] + INDUSTRY_TAGS.get(ind, [])
    tags += [re.sub(r"\s+", "", i) for i in items[:3]]
    tags += ["숏폼", "소상공인"]
    seen, hashtags = set(), []
    for t in tags:
        if t and t not in seen:
            seen.add(t)
            hashtags.append("#" + t)

    title = f"{region + ' ' if region else ''}{name} | {items[0] if items else ind_label}"
    concept = f"{PURPOSES.get(purpose, '홍보')} 목적의 {ind_label} 숏폼. 고객 제공 영상의 핵심 장면 중심 구성."
    narration = " ".join([hook, *(items[:3]), cta])
    return {
        "engine": "rule", "title": title, "concept": concept, "hook_text": hook,
        "captions": captions, "cta_text": cta, "narration": narration,
        "hashtags": hashtags[:15], "scene_labels": {},
        "keywords": [k for k in [region and f"{region} {ind_label}", region and f"{region} 맛집" if ind == "restaurant" else "", *items[:3]] if k],
    }


def sns_pack(biz: dict, copy: dict) -> dict:
    name, addr, phone = biz["name"], biz.get("address", ""), biz.get("phone", "")
    web = biz.get("website", "")
    tags = " ".join(copy.get("hashtags", []))
    info = "\n".join(x for x in [f"📍 {addr}" if addr else "", f"📞 {phone}" if phone else "", f"🔗 {web}" if web else ""] if x)
    items = split_items(biz.get("products", ""))
    item_line = ", ".join(items) if items else ""
    return {
        "youtube_title": f"{copy['title']} #shorts"[:100],
        "youtube_description": f"{copy['hook_text']}\n\n{name}{' - ' + item_line if item_line else ''}\n{info}\n\n{tags}",
        "instagram": f"{copy['hook_text']}\n\n{name}{'의 ' + item_line if item_line else ''}\n{copy['cta_text']}\n\n{info}\n\n{tags}",
        "tiktok": f"{copy['hook_text']} {copy['cta_text']} {tags}"[:2200],
        "naver_blog": (f"[{name}] {copy['title']}\n\n안녕하세요, {name}입니다.\n"
                       + (f"저희 {name}에서는 {item_line}을(를) 준비하고 있습니다.\n" if item_line else "")
                       + f"영상으로 매장 분위기를 먼저 확인해 보세요.\n\n{info}\n\n{tags}"),
        "naver_place": f"{copy['hook_text']} {item_line} {copy['cta_text']}".strip()[:200],
        "threads": f"{copy['hook_text']}\n{name} {copy['cta_text']}\n{tags}",
        "kakao": f"[{name}] {copy['hook_text']}\n{copy['cta_text']}\n{info}",
        "hashtags": tags,
        "local_keywords": ", ".join(copy.get("keywords", [])),
        "notice": "가격·할인·효능 등은 고객이 제공한 정보만 사용했습니다. 게시 전 내용을 확인하세요.",
    }


# ---------------- Claude (선택) ----------------

class SceneLabel(BaseModel):
    segment_key: str = Field(description="입력에 주어진 장면 키 그대로")
    label: str = Field(description="화면에 실제로 보이는 것(예: 음식 클로즈업, 매장 외관). 짧게.")
    promo_value: int = Field(description="홍보 활용도 1~10")


class CopyOut(BaseModel):
    title: str
    concept: str
    hook_text: str = Field(description="첫 3초 후킹 자막, 18자 이내")
    captions: list[str] = Field(description="장면 순서대로의 짧은 자막(각 16자 이내)")
    cta_text: str
    narration: str
    hashtags: list[str]
    keywords: list[str]
    scene_labels: list[SceneLabel]


SYSTEM = """너는 한국 소상공인 홍보 숏폼 카피라이터다.
반드시 지킬 것:
- 고객이 입력한 정보와 이미지에 실제로 보이는 것만 사용한다.
- 가격, 할인, 이벤트, 효능, 수상, 후기, '최고/1등/유명' 같은 확인 불가 주장은 절대 만들지 않는다.
- 자막은 짧고 자연스러운 한국어 구어체. 이모지는 쓰지 않는다.
- 해시태그는 '#'으로 시작하며 지역·업종·상품 중심으로 10~15개."""


def claude_copy(biz: dict, order: dict, n_scenes: int, frames: dict[str, str], pattern: dict, style_name: str) -> tuple[dict, dict]:
    """frames: {segment_key: jpg_path}. 반환: (copy, usage)"""
    import anthropic

    client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)
    content: list[dict] = []
    for key, path in list(frames.items())[:8]:
        with open(path, "rb") as f:
            b64 = base64.standard_b64encode(f.read()).decode()
        content.append({"type": "text", "text": f"장면 키: {key}"})
        content.append({"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": b64}})
    info = (
        f"상호명: {biz['name']}\n업종: {INDUSTRIES.get(biz['industry'], biz['industry'])}\n주소: {biz.get('address','')}\n"
        f"주요 상품/서비스(고객 입력): {biz.get('products','')}\n강조 문구(고객 입력, 그대로 사용 가능): {order.get('highlights','')}\n"
        f"홍보 목적: {PURPOSES.get(order.get('purpose',''), '')}\n주요 고객 연령: {order.get('target_age','')}\n"
        f"원하는 분위기: {order.get('mood','')}\n편집 스타일: {style_name}\n영상 길이: {order.get('duration',30)}초\n"
        f"필요한 자막 개수: {n_scenes}\n"
        f"업종 인기 숏폼 패턴(관리자 등록 자료): 후킹 방식={pattern.get('hook_type','')}, 구성={pattern.get('story_structure','')}, "
        f"구매유도={pattern.get('cta_type','')}, 후킹 예시={pattern.get('hook_examples', [])}"
    )
    content.append({"type": "text", "text": info + "\n\n위 장면 이미지를 각각 설명(scene_labels)하고, 숏폼 기획 문구를 작성해 줘."})

    kwargs = dict(
        model=config.CLAUDE_MODEL, max_tokens=16000, system=SYSTEM,
        messages=[{"role": "user", "content": content}],
        output_format=CopyOut,
        output_config={"effort": "low"},
    )
    try:
        # 안전 정책으로 응답이 거절되면 서버가 다른 모델로 자동 재시도(server-side fallback)
        resp = client.messages.parse(
            **kwargs,
            extra_headers={"anthropic-beta": "server-side-fallback-2026-07-01"},
            extra_body={"fallbacks": "default"},
        )
    except anthropic.BadRequestError:
        resp = client.messages.parse(**kwargs)
    if resp.stop_reason == "refusal" or resp.parsed_output is None:
        raise RuntimeError(f"Claude 응답을 사용할 수 없습니다(stop_reason={resp.stop_reason}).")
    out: CopyOut = resp.parsed_output
    copy = out.model_dump()
    copy["engine"] = "claude"
    copy["scene_labels"] = {s["segment_key"]: {"label": s["label"], "value": s["promo_value"]} for s in copy["scene_labels"]}
    copy["hashtags"] = [h if h.startswith("#") else "#" + h for h in copy["hashtags"]]
    u = resp.usage
    usage = {"input_tokens": u.input_tokens, "output_tokens": u.output_tokens, "model": config.CLAUDE_MODEL}
    return copy, usage
