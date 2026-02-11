# tests/smoke_test_special_instructions.py
"""Special Instructions 패턴 매칭 + LLM prompt 검증."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from models.survey import SurveyQuestion, AnswerOption, SkipLogic
from services.table_guide_service import generate_special_instructions
from unittest.mock import patch


def _q(qn, qtype="SA", text="Sample text", instructions=None,
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
# 1. Rotation 패턴
# ══════════════════════════════════════════════════════════════════

q = _q("Q1", instructions="보기 로테이션 적용")
result = generate_special_instructions([q], language="ko")
assert "로테이션" in result["Q1"], f"Expected rotation: {result['Q1']}"
print("  Rotation (KO): PASSED")

q = _q("Q1", instructions="Randomize options")
result = generate_special_instructions([q], language="en")
assert "Randomize" in result["Q1"], f"Expected randomize: {result['Q1']}"
print("  Rotation (EN): PASSED")


# ══════════════════════════════════════════════════════════════════
# 2. Piping 패턴
# ══════════════════════════════════════════════════════════════════

q = _q("Q2", text="Q3에서 선택한 항목에 대해 평가")
result = generate_special_instructions([q], language="ko")
assert "파이핑" in result["Q2"], f"Expected piping: {result['Q2']}"
print("  Piping (KO): PASSED")

q = _q("Q2", text="Pipe from Q3 selected items")
result = generate_special_instructions([q], language="en")
assert "Pipe" in result["Q2"], f"Expected pipe: {result['Q2']}"
print("  Piping (EN): PASSED")


# ══════════════════════════════════════════════════════════════════
# 3. Open-end 패턴
# ══════════════════════════════════════════════════════════════════

q = _q("Q3", qtype="OE")
result = generate_special_instructions([q], language="en")
assert "Open-end" in result["Q3"], f"Expected OE: {result['Q3']}"
print("  Open-end: PASSED")


# ══════════════════════════════════════════════════════════════════
# 4. Exclusive 패턴
# ══════════════════════════════════════════════════════════════════

q = _q("Q4", instructions="단독응답 코드 포함")
result = generate_special_instructions([q], language="ko")
assert "단독응답" in result["Q4"], f"Expected exclusive: {result['Q4']}"
print("  Exclusive (KO): PASSED")

q = _q("Q4", options=[
    AnswerOption(code="1", label="Brand A"),
    AnswerOption(code="99", label="None of the above (exclusive)"),
])
result = generate_special_instructions([q], language="en")
assert "Exclusive" in result["Q4"], f"Expected exclusive: {result['Q4']}"
print("  Exclusive (EN): PASSED")


# ══════════════════════════════════════════════════════════════════
# 5. Rank 패턴
# ══════════════════════════════════════════════════════════════════

q = _q("Q5", instructions="rank top 3")
result = generate_special_instructions([q], language="en")
assert "Rank" in result["Q5"], f"Expected rank: {result['Q5']}"
print("  Rank (EN): PASSED")

q = _q("Q5", instructions="상위 3개 선택")
result = generate_special_instructions([q], language="ko")
assert "순위" in result["Q5"], f"Expected rank: {result['Q5']}"
print("  Rank (KO): PASSED")


# ══════════════════════════════════════════════════════════════════
# 6. Show Card 패턴
# ══════════════════════════════════════════════════════════════════

q = _q("Q6", instructions="SHOW CARD A")
result = generate_special_instructions([q], language="en")
assert "Show Card" in result["Q6"], f"Expected show card: {result['Q6']}"
print("  Show Card (EN): PASSED")

q = _q("Q6", instructions="보기 카드 제시")
result = generate_special_instructions([q], language="ko")
assert "보기 카드" in result["Q6"], f"Expected show card: {result['Q6']}"
print("  Show Card (KO): PASSED")


# ══════════════════════════════════════════════════════════════════
# 7. Multiple response (MA) — only when no other auto_parts
# ══════════════════════════════════════════════════════════════════

q = _q("Q7", qtype="MA", text="다음 중 해당하는 것을 모두 선택")
result = generate_special_instructions([q], language="ko")
assert "복수응답" in result["Q7"], f"Expected MA: {result['Q7']}"
print("  MA (standalone): PASSED")

# MA with rotation → rotation takes priority, MA 추가 안됨
q = _q("Q7b", qtype="MA", instructions="randomize options")
result = generate_special_instructions([q], language="en")
assert "Randomize" in result["Q7b"], f"Expected randomize: {result['Q7b']}"
assert "Multiple" not in result["Q7b"], f"MA should not appear with other parts: {result['Q7b']}"
print("  MA (suppressed with other): PASSED")


# ══════════════════════════════════════════════════════════════════
# 8. 복합 패턴 " / " 구분자
# ══════════════════════════════════════════════════════════════════

q = _q("Q8", instructions="보기 로테이션, 단독응답 코드 포함")
result = generate_special_instructions([q], language="ko")
assert " / " in result["Q8"], f"Expected ' / ' separator: {result['Q8']}"
assert "로테이션" in result["Q8"] and "단독응답" in result["Q8"], \
    f"Expected rotation+exclusive: {result['Q8']}"
print("  Combined patterns with separator: PASSED")


# ══════════════════════════════════════════════════════════════════
# 9. 일반 질문 → needs_llm 경로
# ══════════════════════════════════════════════════════════════════

captured_prompts = []

def _mock_call_llm_json(system_prompt, user_prompt, model, **kwargs):
    captured_prompts.append(user_prompt)
    return {"results": [{"question_number": "Q9", "instruction": "LLM result"}]}

# Plain SA with no keyword → goes to LLM
q = _q("Q9", qtype="SA", text="전반적인 만족도를 평가해 주세요")

with patch("services.table_guide_service.call_llm_json", side_effect=_mock_call_llm_json):
    result = generate_special_instructions([q], language="ko")

assert len(captured_prompts) == 1, f"Expected 1 LLM call, got {len(captured_prompts)}"
assert result["Q9"] == "LLM result", f"Expected LLM result: {result['Q9']}"
print("  Plain question → LLM path: PASSED")


# ══════════════════════════════════════════════════════════════════
# 10. LLM user prompt에 Filter/Skip 포함 확인
# ══════════════════════════════════════════════════════════════════

captured_prompts2 = []

def _mock_call_llm_json2(system_prompt, user_prompt, model, **kwargs):
    captured_prompts2.append(user_prompt)
    return {"results": [{"question_number": "Q10", "instruction": ""}]}

q = _q(
    "Q10", qtype="SA", text="일반 문항",
    filter_cond="Q2=3 응답자만",
    skip_logic=[SkipLogic(condition="Q10=1", target="Q12로 이동")],
)

with patch("services.table_guide_service.call_llm_json", side_effect=_mock_call_llm_json2):
    result = generate_special_instructions([q], language="ko")

assert len(captured_prompts2) == 1
prompt = captured_prompts2[0]
assert "Filter: Q2=3" in prompt, f"Missing Filter in LLM prompt:\n{prompt}"
assert "Skip: Q10=1" in prompt, f"Missing Skip in LLM prompt:\n{prompt}"
print("  LLM prompt includes Filter/Skip: PASSED")


print("\n=== ALL SPECIAL INSTRUCTIONS TESTS PASSED ===")
