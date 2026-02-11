# tests/smoke_test_subbanner.py
"""SubBanner 제안 로직 검증 — 매트릭스 감지 필터 + 비매트릭스 빈 반환."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from models.survey import SurveyQuestion, AnswerOption, SkipLogic


def _q(qn, qtype, text="Sample text", instructions=None,
       filter_cond=None, skip_logic=None, options=None):
    """테스트용 SurveyQuestion 생성 헬퍼."""
    return SurveyQuestion(
        question_number=qn, question_text=text,
        question_type=qtype, instructions=instructions,
        filter_condition=filter_cond,
        skip_logic=skip_logic or [],
        answer_options=options or [],
    )


# ══════════════════════════════════════════════════════════════════
# 1. 비매트릭스 문항 → 빈 결과, LLM 호출 없음
# ══════════════════════════════════════════════════════════════════

from services.table_guide_service import suggest_sub_banners

non_matrix_types = ["SA", "MA", "OE", "OPEN-END", "SCALE", "5PT SCALE", "MULTI"]
qs = [_q(f"Q{i+1}", t) for i, t in enumerate(non_matrix_types)]
result = suggest_sub_banners(qs, language="en")

for q in qs:
    assert q.question_number in result, f"Missing {q.question_number}"
    assert result[q.question_number] == "", \
        f"{q.question_number} ({q.question_type}) should be empty, got: {result[q.question_number]}"

print("  Non-matrix types → empty: PASSED")


# ══════════════════════════════════════════════════════════════════
# 2. 매트릭스 타입 인식 테스트
# ══════════════════════════════════════════════════════════════════

import re

# 매트릭스 감지 로직 재현 (table_guide_service.py의 suggest_sub_banners 내부)
def _is_matrix(qtype_str):
    qtype = (qtype_str or "").strip().upper()
    return bool(
        re.match(r'\d+\s*PT\s*X\s*\d+', qtype)
        or re.match(r'\d+\s*PT\s+SCALE\s*X\s*\d+', qtype)
        or "GRID" in qtype
        or "MATRIX" in qtype
    )


matrix_types = [
    ("5PT X 10", True),
    ("5pt x 10", True),
    ("7PT SCALE X 5", True),
    ("5PT SCALE X 8", True),
    ("GRID", True),
    ("MATRIX", True),
    ("5PT X GRID", True),
    ("SA GRID", True),
    # Non-matrix
    ("SA", False),
    ("MA", False),
    ("OE", False),
    ("5PT SCALE", False),
    ("SCALE", False),
    ("OPEN-END", False),
]

for qtype, expected in matrix_types:
    actual = _is_matrix(qtype)
    assert actual == expected, f"_is_matrix({qtype!r}) = {actual}, expected {expected}"

print("  Matrix type detection: PASSED")


# ══════════════════════════════════════════════════════════════════
# 3. user prompt에 Instructions/Filter/Skip 포함 확인
# ══════════════════════════════════════════════════════════════════

from unittest.mock import patch, MagicMock

matrix_q = _q(
    "Q5", "5PT X 8",
    text="다음 각 브랜드에 대해 평가해 주세요",
    instructions="SHOW CARD A, 보기 로테이션",
    filter_cond="Q2=1,2 응답자만",
    skip_logic=[SkipLogic(condition="Q5 완료", target="Q7로 이동")],
    options=[AnswerOption(code="1", label="브랜드A"), AnswerOption(code="2", label="브랜드B")],
)

captured_prompts = []

def _mock_call_llm_json(system_prompt, user_prompt, model, **kwargs):
    captured_prompts.append(user_prompt)
    return {"results": [{"question_number": "Q5", "sub_banner": "test"}]}

with patch("services.table_guide_service.call_llm_json", side_effect=_mock_call_llm_json):
    result = suggest_sub_banners([matrix_q], language="ko")

assert len(captured_prompts) == 1, f"Expected 1 LLM call, got {len(captured_prompts)}"
prompt = captured_prompts[0]

assert "Instructions: SHOW CARD A" in prompt, f"Missing Instructions in prompt:\n{prompt}"
assert "Filter: Q2=1,2" in prompt, f"Missing Filter in prompt:\n{prompt}"
assert "Skip: Q5 완료" in prompt, f"Missing Skip in prompt:\n{prompt}"

print("  User prompt includes Instructions/Filter/Skip: PASSED")


print("\n=== ALL SUBBANNER TESTS PASSED ===")
