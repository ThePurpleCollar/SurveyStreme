"""Table title vocabulary and normalization helpers."""

import re


def build_title_domain_vocabulary(survey_context: str, language: str) -> str:
    """Return domain-specific MR title vocabulary guidance from context text."""
    context = (survey_context or "").lower()
    matches = []
    if any(k in context for k in ("u&a", "usage & attitude", "usage and attitude")):
        matches.append("ua")
    if "brand tracking" in context or "brand health" in context:
        matches.append("brand")
    if any(k in context for k in ("satisfaction", "nps", "csat")):
        matches.append("satisfaction")
    if any(k in context for k in ("concept test", "product test", "ad test", "creative test")):
        matches.append("test")

    if not matches:
        matches = ["general"]

    if language == "ko":
        blocks = {
            "general": [
                "구매 요인/선택 이유 문항: 핵심 구매 요인(Key Buying Factors)",
                "브랜드 인지 문항: TOM, 보조 인지(Aided Awareness)",
                "브랜드 고려/구매 의향 문항: 고려 브랜드, 향후 구매 의향(Purchase Intent)",
                "사용 빈도/상황 문항: 사용 빈도, 사용 상황(Usage Occasion)",
                "정보원 문항: 정보 탐색 채널(Information Sources)",
            ],
            "ua": [
                "카테고리 이용 문항: 카테고리 사용 행태(Category Usage)",
                "이용 빈도 문항: 사용 빈도(Usage Frequency)",
                "구매/선택 요인 문항: 핵심 구매 요인(Key Buying Factors)",
                "브랜드 레퍼토리 문항: 브랜드 레퍼토리(Brand Repertoire)",
                "상황/니즈 문항: 사용 상황(Usage Occasion), 니즈 상태(Need States)",
            ],
            "brand": [
                "인지 문항: TOM, 보조 인지(Aided Awareness)",
                "고려 문항: 브랜드 고려(Brand Consideration)",
                "이미지/속성 문항: 브랜드 이미지(Brand Image), 속성 평가(Attribute Rating)",
                "충성/추천 문항: 추천 의향(NPS), 브랜드 선호(Brand Preference)",
                "퍼널 문항: 브랜드 퍼널(Brand Funnel Stage)",
            ],
            "satisfaction": [
                "만족도 문항: 전반적 만족도(Overall Satisfaction), 접점 만족도(Touchpoint Satisfaction)",
                "추천 문항: 추천 의향(NPS)",
                "불만/문제 문항: 문제 경험(Problem Experience), 해결 만족도(Resolution Satisfaction)",
                "재이용 문항: 재이용 의향(Retention Intent)",
            ],
            "test": [
                "컨셉/제품 문항: 컨셉 매력도(Concept Appeal), 제품 평가(Product Evaluation)",
                "구매 의향 문항: 구매 의향(Purchase Intent)",
                "독창성/적합성 문항: 독창성(Uniqueness), 니즈 적합도(Need Fit)",
                "광고 문항: 광고 회상(Ad Recall), 메시지 명확성(Message Clarity), 브랜드 연결성(Brand Linkage)",
            ],
        }
        lines = [
            "## Table Title Domain Vocabulary",
            "질문 문구를 그대로 요약하지 말고, 아래 MR 표준 표현 중 가장 가까운 명사구를 우선 사용하세요.",
        ]
    else:
        blocks = {
            "general": [
                "Purchase driver / choice reason questions: Key Buying Factors",
                "Brand awareness questions: TOM, Aided Awareness",
                "Consideration / future buying questions: Brand Consideration, Purchase Intent",
                "Usage frequency / occasion questions: Usage Frequency, Usage Occasion",
                "Information source questions: Information Sources",
            ],
            "ua": [
                "Category behavior questions: Category Usage",
                "Usage frequency questions: Usage Frequency",
                "Purchase/choice driver questions: Key Buying Factors",
                "Brand set questions: Brand Repertoire",
                "Occasion/need questions: Usage Occasion, Need States",
            ],
            "brand": [
                "Awareness questions: TOM, Aided Awareness",
                "Consideration questions: Brand Consideration",
                "Image/attribute questions: Brand Image, Attribute Rating",
                "Loyalty/recommendation questions: NPS, Brand Preference",
                "Funnel questions: Brand Funnel Stage",
            ],
            "satisfaction": [
                "Satisfaction questions: Overall Satisfaction, Touchpoint Satisfaction",
                "Recommendation questions: NPS",
                "Problem questions: Problem Experience, Resolution Satisfaction",
                "Retention questions: Retention Intent",
            ],
            "test": [
                "Concept/product questions: Concept Appeal, Product Evaluation",
                "Purchase intent questions: Purchase Intent",
                "Uniqueness/fit questions: Uniqueness, Need Fit",
                "Ad questions: Ad Recall, Message Clarity, Brand Linkage",
            ],
        }
        lines = [
            "## Table Title Domain Vocabulary",
            "Prefer these standard MR table-title noun phrases over literal summaries of the question wording.",
        ]

    seen = set()
    for match in matches:
        for item in blocks.get(match, []):
            if item not in seen:
                lines.append(f"- {item}")
                seen.add(item)
    lines.append("")
    return "\n".join(lines)


def standard_title_for_question(item: dict, language: str) -> str:
    """Map clear question intent to standard MR table-title vocabulary."""
    haystack = " ".join(
        str(item.get(key, "") or "")
        for key in (
            "source_variable", "text", "options", "qtype", "filter",
            "skip_logic", "role", "variable_type", "analytical_value", "instructions",
        )
    ).lower()

    def has_any(*needles: str) -> bool:
        return any(needle in haystack for needle in needles)

    is_ko = language == "ko"

    if has_any("important", "importance", "driver", "factor", "attribute", "중요", "요인", "속성"):
        if has_any("buy", "purchase", "choose", "choosing", "choice", "consider", "구매", "선택", "고려"):
            return "핵심 구매 요인" if is_ko else "Key Buying Factors"

    if has_any("willingness to pay", "willing to pay", "price acceptable", "acceptable price",
               "지불 의향", "가격 수용", "적정 가격"):
        return "지불 의향" if is_ko else "Willingness to Pay"

    if has_any("price sensitivity", "price sensitive", "가격 민감"):
        return "가격 민감도" if is_ko else "Price Sensitivity"

    if has_any("why", "reason", "choose", "choice reason", "선택 이유", "구매 이유", "이유"):
        if has_any("buy", "purchase", "choose", "choosing", "brand", "구매", "선택", "브랜드"):
            return "선택 이유" if is_ko else "Choice Reasons"

    if has_any("likely", "willing", "intent", "intend", "consider buying", "purchase intention",
               "의향", "구입 의향", "구매 의향"):
        if has_any("buy", "purchase", "use", "subscribe", "구매", "구입", "이용"):
            return "구매 의향" if is_ko else "Purchase Intent"

    if has_any("aware", "awareness", "heard of", "know", "인지", "알고"):
        if has_any("brand", "브랜드"):
            return "보조 인지 브랜드" if is_ko else "Aided Brand Awareness"
        return "보조 인지" if is_ko else "Aided Awareness"

    if has_any("consideration", "consider", "고려"):
        if has_any("brand", "브랜드"):
            return "브랜드 고려" if is_ko else "Brand Consideration"

    if has_any("image", "imagery", "association", "이미지", "연상"):
        if has_any("brand", "브랜드"):
            return "브랜드 이미지" if is_ko else "Brand Image"

    if has_any("main brand", "primary brand", "current brand", "owned brand",
               "주 사용 브랜드", "현재 브랜드", "보유 브랜드"):
        return "주 사용 브랜드" if is_ko else "Main Brand"

    if has_any("own", "ownership", "have", "보유", "소유"):
        if has_any("tv", "product", "device", "car", "vehicle", "제품", "기기", "자동차"):
            return "보유 여부" if is_ko else "Ownership Status"

    if has_any("satisfied", "satisfaction", "만족"):
        if has_any("overall", "전반"):
            return "전반적 만족도" if is_ko else "Overall Satisfaction"
        return "만족도" if is_ko else "Satisfaction"

    if has_any("recommend", "nps", "추천"):
        return "추천 의향" if is_ko else "NPS"

    if has_any("how often", "frequency", "frequently", "빈도", "얼마나 자주"):
        return "사용 빈도" if is_ko else "Usage Frequency"

    if has_any("occasion", "situation", "use case", "usage context", "상황", "용도"):
        return "사용 상황" if is_ko else "Usage Occasion"

    if has_any("purchase channel", "where buy", "where did you buy", "구매 채널", "구입 채널", "구매 장소"):
        return "구매 채널" if is_ko else "Purchase Channel"

    if has_any("information source", "where did you", "channel", "search", "정보원", "정보 탐색", "채널"):
        return "정보 탐색 채널" if is_ko else "Information Sources"

    return ""


def title_case_mr(title: str) -> str:
    acronyms = {
        "tv": "TV", "nps": "NPS", "tom": "TOM", "csat": "CSAT",
        "u&a": "U&A", "ev": "EV", "ai": "AI",
    }
    small_words = {"and", "or", "of", "to", "for", "in", "on", "with", "by"}
    words = re.split(r"(\s+|-|/)", title.strip())
    result = []
    word_index = 0
    for token in words:
        low = token.lower()
        if not token.strip() or token in {"-", "/"}:
            result.append(token)
            continue
        if low in acronyms:
            result.append(acronyms[low])
        elif word_index > 0 and low in small_words:
            result.append(low)
        else:
            result.append(token[:1].upper() + token[1:].lower())
        word_index += 1
    return "".join(result)


def polish_generated_title(title: str, language: str) -> str:
    """Clean literal/awkward wording from generated table titles."""
    text = re.sub(r"\s+", " ", str(title or "")).strip(" \t\r\n-–—:：.;,")
    if not text:
        return ""

    if language == "ko":
        replacements = [
            (r"응답자\s*", ""),
            (r"설문\s*", ""),
            (r"조사\s*", ""),
            (r"\s*분포$", ""),
            (r"\s*확인$", ""),
            (r"에\s*대한\s*", " "),
            (r"관련\s*", ""),
            (r"향후\s*구매\s*가능성", "구매 의향"),
            (r"구매\s*의사", "구매 의향"),
            (r"구매\s*중요\s*(요소|요인|항목)", "핵심 구매 요인"),
            (r"선택\s*중요\s*(요소|요인|항목)", "핵심 구매 요인"),
            (r"중요\s*구매\s*(요소|요인|항목)", "핵심 구매 요인"),
            (r"구매\s*가능성", "구매 의향"),
            (r"구입\s*가능성", "구매 의향"),
            (r"지불\s*용의", "지불 의향"),
            (r"브랜드\s*인지\s*여부", "보조 인지 브랜드"),
            (r"(?<!보조 )인지\s*브랜드", "보조 인지 브랜드"),
            (r"현재\s*(보유|사용)\s*브랜드", "주 사용 브랜드"),
            (r"고려\s*브랜드", "브랜드 고려"),
            (r"브랜드\s*고려\s*여부", "브랜드 고려"),
            (r"브랜드\s*연상", "브랜드 이미지"),
            (r"브랜드\s*이미지\s*평가", "브랜드 이미지"),
            (r"구매처", "구매 채널"),
            (r"구매\s*장소", "구매 채널"),
            (r"연령$", "연령대"),
            (r"나이$", "연령대"),
            (r"소득$", "소득수준"),
            (r"소득\s*수준$", "소득수준"),
        ]
        for pattern, repl in replacements:
            text = re.sub(pattern, repl, text, flags=re.IGNORECASE)
        text = re.sub(r"\s+", " ", text).strip(" -:：")
        return text

    replacements = [
        (r"\bRespondent\s+", ""),
        (r"\bSurvey\s+", ""),
        (r"\bQuestion\s+", ""),
        (r"\s+Survey\b", ""),
        (r"\s+Question\b", ""),
        (r"\s+Distribution\b", ""),
        (r"\s+Check\b", ""),
        (r"\bAbout\s+", ""),
        (r"\bTV Choice Factors\b", "Key Buying Factors"),
        (r"\bPurchase Important Factors\b", "Key Buying Factors"),
        (r"\bImportant Things\b", "Key Buying Factors"),
        (r"\bImportant Factors\b", "Key Buying Factors"),
        (r"(?<!Key )\bBuying Factors\b", "Key Buying Factors"),
        (r"\bChoice Factors\b", "Key Buying Factors"),
        (r"\bFuture Purchase Intention\b", "Purchase Intent"),
        (r"\bPurchase Intention\b", "Purchase Intent"),
        (r"\bIntention to Purchase\b", "Purchase Intent"),
        (r"\bLikelihood to Purchase\b", "Purchase Intent"),
        (r"\bWillingness to Purchase\b", "Purchase Intent"),
        (r"\bPurchase Likelihood\b", "Purchase Intent"),
        (r"\bAware Brands\b", "Aided Brand Awareness"),
        (r"\bBrand Awareness Brands\b", "Aided Brand Awareness"),
        (r"\bBrand Awareness Status\b", "Aided Brand Awareness"),
        (r"\bCurrent Product Brand\b", "Main Brand"),
        (r"\bCurrent TV Brand\b", "Main Brand"),
        (r"\bOwned Brand\b", "Main Brand"),
        (r"\bTV Ownership\b", "Ownership Status"),
        (r"\bProduct Ownership\b", "Ownership Status"),
        (r"\bBrand Consideration Set\b", "Brand Consideration"),
        (r"\bConsidered Brands\b", "Brand Consideration"),
        (r"\bBrands Considered\b", "Brand Consideration"),
        (r"\bBrand Imagery\b", "Brand Image"),
        (r"\bBrand Association(s)?\b", "Brand Image"),
        (r"\bPayment Willingness\b", "Willingness to Pay"),
        (r"\bPrice Willingness\b", "Willingness to Pay"),
        (r"\bAcceptable Price\b", "Willingness to Pay"),
        (r"\bWhere Purchased\b", "Purchase Channel"),
        (r"\bWhere Bought\b", "Purchase Channel"),
        (r"\bAge\b(?!\s+Group\b)", "Age Group"),
        (r"\bIncome\b(?!\s+Level\b)", "Income Level"),
        (r"\bGender\b", "Gender"),
    ]
    for pattern, repl in replacements:
        text = re.sub(pattern, repl, text, flags=re.IGNORECASE)
    text = re.sub(r"\s+", " ", text).strip(" -:")
    return title_case_mr(text)


def normalize_title_by_intent(base_title: str, item: dict, language: str) -> str:
    standard = standard_title_for_question(item, language)
    return standard or polish_generated_title(base_title, language)
