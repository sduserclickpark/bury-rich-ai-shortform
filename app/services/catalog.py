"""업종·목적·스타일 등 기본 카탈로그."""

INDUSTRIES = {
    "restaurant": "일반 음식점", "cafe": "카페·디저트", "beauty": "미용실·피부관리",
    "fitness": "헬스·필라테스", "academy": "학원·교육", "realestate": "부동산 중개",
    "lodging": "숙박·펜션", "auto": "자동차 정비", "market": "전통시장·소매점",
    "online": "온라인 쇼핑몰", "self": "개인사업자·자영업", "company": "중소기업·서비스업",
}

INDUSTRY_SHORT = {
    "restaurant": "식당", "cafe": "카페", "beauty": "미용실", "fitness": "운동센터", "academy": "학원",
    "realestate": "부동산", "lodging": "숙소", "auto": "정비소", "market": "가게", "online": "쇼핑몰",
    "self": "가게", "company": "업체",
}

INDUSTRY_TAGS = {
    "restaurant": ["맛집", "맛집추천", "오늘뭐먹지"], "cafe": ["카페", "카페추천", "디저트맛집"],
    "beauty": ["미용실", "헤어스타일", "피부관리"], "fitness": ["헬스장", "필라테스", "운동"],
    "academy": ["학원", "공부", "교육"], "realestate": ["부동산", "매물", "집구하기"],
    "lodging": ["펜션", "숙소추천", "여행"], "auto": ["자동차정비", "카센터", "차량관리"],
    "market": ["전통시장", "시장", "로컬상점"], "online": ["온라인쇼핑", "쇼핑", "신상품"],
    "self": ["자영업", "소상공인", "가게"], "company": ["기업", "서비스", "비즈니스"],
}

PURPOSES = {
    "visit": "매장 방문 유도", "new_product": "신상품·신메뉴 홍보", "brand": "브랜드 인지도",
    "reservation": "예약·문의 유도", "event": "행사·할인 홍보", "online_sale": "온라인 구매 유도",
    "recruit": "회원·수강생 모집",
}

AGES = {"10s": "10대", "20s": "20대", "30s": "30대", "40s": "40대", "50s": "50대", "60s": "60대 이상", "all": "전 연령"}

MOODS = {"bright": "밝고 경쾌한", "calm": "차분하고 감성적인", "luxury": "고급스러운", "fun": "재미있는",
         "trendy": "트렌디한", "warm": "따뜻한", "dynamic": "역동적인"}

# 스타일별 편집 파라미터. cut: 평균 컷 길이(초), trans: cut|fade, zoom: 확대 효과 강도,
# color: (밝기, 대비, 채도, 감마), cap: 자막 디자인, music: 추천 음악 분위기, story: 구성
STYLES = {
    "trend":      {"name": "트렌드형", "cut": 1.6, "trans": "cut", "zoom": 0.06, "color": (0.02, 1.06, 1.15, 1.0), "cap": "pop", "music": "trendy", "story": "후킹 → 빠른 장면 나열 → 행동 유도"},
    "emotional":  {"name": "감성형", "cut": 3.0, "trans": "fade", "zoom": 0.04, "color": (0.02, 0.98, 0.92, 1.05), "cap": "soft", "music": "calm", "story": "분위기 도입 → 디테일 → 여운 → 브랜드"},
    "premium":    {"name": "고급 브랜드형", "cut": 2.8, "trans": "fade", "zoom": 0.03, "color": (0.0, 1.10, 0.95, 1.0), "cap": "luxury", "music": "luxury", "story": "브랜드 도입 → 디테일 클로즈업 → 공간 → 로고"},
    "purchase":   {"name": "구매 유도형", "cut": 1.8, "trans": "cut", "zoom": 0.06, "color": (0.03, 1.08, 1.12, 1.0), "cap": "bold", "music": "dynamic", "story": "문제/관심 → 상품 → 장점 → 구매 방법"},
    "visit":      {"name": "방문 유도형", "cut": 2.0, "trans": "cut", "zoom": 0.05, "color": (0.03, 1.05, 1.10, 1.0), "cap": "bold", "music": "bright", "story": "후킹 → 매장/상품 → 위치 → 방문 유도"},
    "story":      {"name": "스토리텔링형", "cut": 2.6, "trans": "fade", "zoom": 0.04, "color": (0.02, 1.0, 1.0, 1.03), "cap": "soft", "music": "warm", "story": "시작 → 과정 → 결과 → 브랜드"},
    "info":       {"name": "정보 전달형", "cut": 2.4, "trans": "cut", "zoom": 0.03, "color": (0.03, 1.04, 1.05, 1.0), "cap": "info", "music": "bright", "story": "질문 → 핵심 정보 나열 → 정리"},
    "product":    {"name": "상품 소개형", "cut": 2.2, "trans": "cut", "zoom": 0.07, "color": (0.03, 1.06, 1.10, 1.0), "cap": "bold", "music": "trendy", "story": "대표 상품 → 디테일 → 구성 → 구매/방문"},
    "humor":      {"name": "유머형", "cut": 1.5, "trans": "cut", "zoom": 0.10, "color": (0.04, 1.05, 1.18, 1.0), "cap": "pop", "music": "fun", "story": "반전 후킹 → 빠른 전개 → 마무리"},
    "cinematic":  {"name": "시네마틱형", "cut": 3.2, "trans": "fade", "zoom": 0.03, "color": (-0.02, 1.12, 0.88, 1.0), "cap": "luxury", "music": "calm", "story": "와이드 도입 → 슬로우 디테일 → 엔딩"},
    "fast":       {"name": "빠른 장면 전환형", "cut": 0.9, "trans": "cut", "zoom": 0.08, "color": (0.03, 1.08, 1.15, 1.0), "cap": "pop", "music": "dynamic", "story": "초고속 컷 몽타주 → 브랜드"},
    "review":     {"name": "고객 후기형", "cut": 2.6, "trans": "cut", "zoom": 0.04, "color": (0.03, 1.02, 1.05, 1.02), "cap": "info", "music": "warm", "story": "고객 반응(고객 제공 자료만) → 상품 → 방문"},
    "food":       {"name": "음식 전문형", "cut": 1.8, "trans": "cut", "zoom": 0.08, "color": (0.04, 1.08, 1.22, 1.0), "cap": "pop", "music": "trendy", "story": "음식 클로즈업 후킹 → 조리/플레이팅 → 매장 → 위치"},
    "asmr":       {"name": "ASMR형", "cut": 3.0, "trans": "fade", "zoom": 0.02, "color": (0.02, 1.02, 1.05, 1.0), "cap": "soft", "music": "", "story": "현장음 중심 디테일 → 브랜드 (배경음악 최소화)"},
    "event":      {"name": "행사·할인 홍보형", "cut": 1.6, "trans": "cut", "zoom": 0.06, "color": (0.04, 1.08, 1.15, 1.0), "cap": "bold", "music": "dynamic", "story": "행사 내용(고객 제공) → 상품 → 기간·위치"},
}

# 자막 디자인(색상은 RGB 16진수): 글자 크기, 글자색, 테두리색, 배경박스 여부, 위치(top/middle/bottom)
CAPTION_STYLES = {
    "pop":    {"size": 86, "color": "FFFFFF", "accent": "FFD400", "outline": "000000", "box": False, "pos": "middle"},
    "bold":   {"size": 80, "color": "FFFFFF", "accent": "FFC83C", "outline": "000000", "box": True, "pos": "middle"},
    "soft":   {"size": 66, "color": "FFFFFF", "accent": "FFE6C8", "outline": "202020", "box": False, "pos": "bottom"},
    "luxury": {"size": 64, "color": "E8D5A3", "accent": "C9A24B", "outline": "000000", "box": False, "pos": "bottom"},
    "info":   {"size": 70, "color": "FFFFFF", "accent": "FFC94B", "outline": "000000", "box": True, "pos": "bottom"},
}
