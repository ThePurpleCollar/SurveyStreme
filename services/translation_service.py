"""Translation Helper 서비스.

추출된 설문지를 다국어로 번역. 마케팅 리서치 용어 보존.
GPT-5 기반 배치 번역.
"""

import io
import json
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional

import pandas as pd

from models.survey import AnswerOption, SurveyQuestion
from services.llm_client import MODEL_TITLE_GENERATOR, call_llm_json

# ---------------------------------------------------------------------------
# 지원 언어
# ---------------------------------------------------------------------------

SUPPORTED_LANGUAGES: Dict[str, str] = {
    "en": "English",
    "ko": "한국어",
    "ja": "日本語",
    "zh-CN": "中文(简体)",
    "zh-TW": "中文(繁體)",
    "th": "ไทย",
    "vi": "Tiếng Việt",
    "id": "Bahasa Indonesia",
    "ms": "Bahasa Melayu",
    "fr": "Français",
    "de": "Deutsch",
    "es": "Español",
}

# ---------------------------------------------------------------------------
# 데이터 구조
# ---------------------------------------------------------------------------


@dataclass
class TranslatedQuestion:
    """번역된 문항."""
    question_number: str
    original_text: str
    translated_text: str
    original_options: List[AnswerOption] = field(default_factory=list)
    translated_options: List[AnswerOption] = field(default_factory=list)
    original_instructions: str = ""
    translated_instructions: str = ""
    is_edited: bool = False


@dataclass
class TranslationResult:
    """번역 결과."""
    source_language: str
    target_language: str
    translated_questions: List[TranslatedQuestion] = field(default_factory=list)


# ---------------------------------------------------------------------------
# 언어 감지
# ---------------------------------------------------------------------------


def detect_source_language(questions: List[SurveyQuestion]) -> str:
    """상위 5개 문항 텍스트를 분석하여 소스 언어를 휴리스틱으로 감지."""
    sample_text = " ".join(
        q.question_text[:200] for q in questions[:5] if q.question_text
    )

    if not sample_text.strip():
        return "en"

    # 한글 비율
    korean_chars = sum(1 for c in sample_text if '\uac00' <= c <= '\ud7a3')
    # CJK 통합한자
    cjk_chars = sum(1 for c in sample_text if '\u4e00' <= c <= '\u9fff')
    # 일본어 (히라가나 + 가타카나)
    jp_chars = sum(1 for c in sample_text
                   if '\u3040' <= c <= '\u309f' or '\u30a0' <= c <= '\u30ff')
    # 태국어
    thai_chars = sum(1 for c in sample_text if '\u0e01' <= c <= '\u0e5b')

    total_chars = len(sample_text.replace(" ", ""))
    if total_chars == 0:
        return "en"

    if korean_chars / total_chars > 0.2:
        return "ko"
    if jp_chars / total_chars > 0.1:
        return "ja"
    if cjk_chars / total_chars > 0.2:
        # 간체/번체 구분은 어려우므로 간체 기본값
        return "zh-CN"
    if thai_chars / total_chars > 0.1:
        return "th"

    # 라틴 계열 (기본 영어)
    return "en"


# ---------------------------------------------------------------------------
# LLM 번역 프롬프트
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT_EN = """You are a professional survey questionnaire translator specializing in marketing research.

CRITICAL RULES — DO NOT translate:
- Question types: [SA], [MA], [5pt x 3], [OE], [NUMERIC]
- Question numbers: Q1, SQ2a, S3
- Piping references: [Q1 response], {{Q2_answer}}, <<Q3>>
- Answer option codes: 1, 2, 3...
- MR terminology: TOM, Aided Awareness, NPS, SOV, Brand Equity

TRANSLATION RULES:
- Maintain consistent scale anchor translations (same anchor = same translation)
- Preserve formatting and line breaks
- Use natural, fluent target language
- Keep professional survey tone

INPUT: JSON array of questions
OUTPUT: JSON object:
{{
  "translations": [
    {{
      "question_number": "Q1",
      "translated_text": "...",
      "translated_options": [
        {{"code": "1", "label": "translated label"}}
      ],
      "translated_instructions": "..."
    }}
  ]
}}"""

_SYSTEM_PROMPT_KO = """전문 설문지 번역가입니다. 마케팅 리서치 설문지 번역을 수행합니다.

절대 번역 금지 대상:
- 문항 유형: [SA], [MA], [5pt x 3], [OE], [NUMERIC]
- 문항 번호: Q1, SQ2a, S3
- 파이핑 참조: [Q1 응답], {{Q2_answer}}, <<Q3>>
- 보기 코드 번호: 1, 2, 3...
- MR 전문용어: TOM, Aided Awareness, NPS, SOV, Brand Equity

번역 규칙:
- 척도 앵커 일관 번역 (동일 앵커 → 동일 번역)
- 서식과 줄바꿈 유지
- 자연스러운 대상 언어 사용
- 전문적인 설문 어조 유지

입력: JSON 문항 배열
출력: JSON 객체:
{{
  "translations": [
    {{
      "question_number": "Q1",
      "translated_text": "...",
      "translated_options": [
        {{"code": "1", "label": "번역된 라벨"}}
      ],
      "translated_instructions": "..."
    }}
  ]
}}"""


# ---------------------------------------------------------------------------
# 번역 실행
# ---------------------------------------------------------------------------


def translate_questions(
    questions: List[SurveyQuestion],
    source_language: str,
    target_language: str,
    model: str = MODEL_TITLE_GENERATOR,
    batch_size: int = 15,
    progress_callback: Optional[Callable] = None,
) -> TranslationResult:
    """문항을 배치 단위로 번역.

    Args:
        questions: 번역할 문항 리스트
        source_language: 소스 언어 코드 (예: "en", "ko")
        target_language: 타겟 언어 코드
        model: 사용할 LLM 모델
        batch_size: 배치 크기 (기본 15)
        progress_callback: 진행 콜백 함수

    Returns:
        TranslationResult
    """
    result = TranslationResult(
        source_language=source_language,
        target_language=target_language,
    )

    if not questions:
        return result

    # 언어 감지로 시스템 프롬프트 선택
    is_korean_source = source_language == "ko"
    system_prompt = _SYSTEM_PROMPT_KO if is_korean_source else _SYSTEM_PROMPT_EN

    source_name = SUPPORTED_LANGUAGES.get(source_language, source_language)
    target_name = SUPPORTED_LANGUAGES.get(target_language, target_language)

    total_batches = (len(questions) + batch_size - 1) // batch_size

    for batch_idx in range(0, len(questions), batch_size):
        batch = questions[batch_idx:batch_idx + batch_size]
        batch_num = batch_idx // batch_size

        if progress_callback:
            progress_callback("batch_start", {
                "batch_index": batch_num,
                "total_batches": total_batches,
                "question_count": len(batch),
            })

        # 배치 데이터 구성
        batch_data = []
        for q in batch:
            q_dict = {
                "question_number": q.question_number,
                "question_text": q.question_text,
                "question_type": q.question_type or "",
            }
            if q.answer_options:
                q_dict["answer_options"] = [
                    {"code": o.code, "label": o.label}
                    for o in q.answer_options
                ]
            if q.instructions:
                q_dict["instructions"] = q.instructions
            batch_data.append(q_dict)

        user_prompt = (
            f"Translate the following survey questions from {source_name} to {target_name}.\n\n"
            f"Questions:\n{json.dumps(batch_data, ensure_ascii=False, indent=2)}"
        )

        try:
            llm_result = call_llm_json(
                system_prompt, user_prompt,
                model=model,
                max_tokens=16384,
            )

            translations = llm_result.get("translations", [])

            # 번역 결과 매핑
            trans_map = {t.get("question_number", ""): t for t in translations}

            for q in batch:
                trans = trans_map.get(q.question_number, {})
                translated_options = []
                for raw_opt in trans.get("translated_options", []):
                    if isinstance(raw_opt, dict):
                        translated_options.append(AnswerOption(
                            code=str(raw_opt.get("code", "")),
                            label=str(raw_opt.get("label", "")),
                        ))

                result.translated_questions.append(TranslatedQuestion(
                    question_number=q.question_number,
                    original_text=q.question_text,
                    translated_text=trans.get("translated_text", q.question_text),
                    original_options=list(q.answer_options),
                    translated_options=translated_options,
                    original_instructions=q.instructions or "",
                    translated_instructions=trans.get("translated_instructions", q.instructions or ""),
                ))

        except Exception as e:
            # 실패 시 원문 유지
            for q in batch:
                result.translated_questions.append(TranslatedQuestion(
                    question_number=q.question_number,
                    original_text=q.question_text,
                    translated_text=f"[Translation Error: {e}] {q.question_text}",
                    original_options=list(q.answer_options),
                    translated_options=list(q.answer_options),
                    original_instructions=q.instructions or "",
                    translated_instructions=q.instructions or "",
                ))

        if progress_callback:
            progress_callback("batch_done", {
                "batch_index": batch_num,
                "total_batches": total_batches,
            })

    return result


# ---------------------------------------------------------------------------
# Excel 내보내기
# ---------------------------------------------------------------------------


def export_translation_excel(result: TranslationResult) -> bytes:
    """번역 결과를 Excel 바이트로 내보내기 (2시트: Original, Translated)."""
    source_name = SUPPORTED_LANGUAGES.get(result.source_language, result.source_language)
    target_name = SUPPORTED_LANGUAGES.get(result.target_language, result.target_language)

    original_rows = []
    translated_rows = []

    for tq in result.translated_questions:
        # 원문 시트
        options_text = "\n".join(
            f"{o.code}. {o.label}" for o in tq.original_options
        ) if tq.original_options else ""

        original_rows.append({
            "Q#": tq.question_number,
            "Question Text": tq.original_text,
            "Answer Options": options_text,
            "Instructions": tq.original_instructions,
        })

        # 번역 시트
        trans_options_text = "\n".join(
            f"{o.code}. {o.label}" for o in tq.translated_options
        ) if tq.translated_options else ""

        translated_rows.append({
            "Q#": tq.question_number,
            "Question Text": tq.translated_text,
            "Answer Options": trans_options_text,
            "Instructions": tq.translated_instructions,
            "Edited": "Yes" if tq.is_edited else "",
        })

    df_original = pd.DataFrame(original_rows)
    df_translated = pd.DataFrame(translated_rows)

    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine='openpyxl') as writer:
        df_original.to_excel(writer, sheet_name=f"Original ({source_name})", index=False)
        df_translated.to_excel(writer, sheet_name=f"Translated ({target_name})", index=False)
    buffer.seek(0)

    return buffer.getvalue()
