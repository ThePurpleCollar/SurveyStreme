# tests/smoke_test_translation.py
"""Translation Helper 서비스 핵심 함수 smoke test (LLM 미호출)"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from models.survey import SurveyQuestion, AnswerOption
from services.translation_service import (
    SUPPORTED_LANGUAGES,
    TranslationResult,
    TranslatedQuestion,
    detect_source_language,
    export_translation_excel,
)

# ── 1. 지원 언어 ──
assert len(SUPPORTED_LANGUAGES) >= 10, f"Expected 10+ languages, got {len(SUPPORTED_LANGUAGES)}"
assert "en" in SUPPORTED_LANGUAGES
assert "ko" in SUPPORTED_LANGUAGES
assert "ja" in SUPPORTED_LANGUAGES
print(f"Supported languages: {len(SUPPORTED_LANGUAGES)}")

# ── 2. 언어 감지: 영어 ──
en_questions = [
    SurveyQuestion(question_number="Q1", question_text="What is your gender?"),
    SurveyQuestion(question_number="Q2", question_text="Which brand do you prefer?"),
]
assert detect_source_language(en_questions) == "en"

# ── 3. 언어 감지: 한국어 ──
ko_questions = [
    SurveyQuestion(question_number="Q1", question_text="귀하의 성별은 무엇입니까?"),
    SurveyQuestion(question_number="Q2", question_text="어떤 브랜드를 선호하십니까?"),
]
assert detect_source_language(ko_questions) == "ko"

# ── 4. 언어 감지: 빈 입력 ──
assert detect_source_language([]) == "en"

# ── 5. Excel 내보내기 ──
result = TranslationResult(
    source_language="en",
    target_language="ko",
    translated_questions=[
        TranslatedQuestion(
            question_number="Q1",
            original_text="What is your gender?",
            translated_text="귀하의 성별은 무엇입니까?",
            original_options=[AnswerOption("1", "Male"), AnswerOption("2", "Female")],
            translated_options=[AnswerOption("1", "남성"), AnswerOption("2", "여성")],
        ),
        TranslatedQuestion(
            question_number="Q2",
            original_text="Which brand?",
            translated_text="어떤 브랜드?",
            is_edited=True,
        ),
    ],
)

excel_bytes = export_translation_excel(result)
assert isinstance(excel_bytes, bytes), "Excel output should be bytes"
assert len(excel_bytes) > 100, f"Excel output too small: {len(excel_bytes)} bytes"
print(f"Excel output: {len(excel_bytes)} bytes")

# ── 6. TranslationResult 기본값 ──
empty_result = TranslationResult(source_language="en", target_language="ko")
assert len(empty_result.translated_questions) == 0

print("All translation smoke tests passed!")
