# tests/smoke_test_piping.py
"""Piping Intelligence 서비스 핵심 함수 smoke test"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from models.survey import SurveyQuestion, AnswerOption, SkipLogic
from services.piping_service import (
    detect_text_piping,
    detect_code_piping,
    detect_filter_dependencies,
    build_filter_chains,
    validate_piping,
    generate_piping_dot,
    PipingRef,
)

# ── 테스트 데이터 ──
questions = [
    SurveyQuestion(
        question_number="Q1", question_text="Which brand do you prefer?",
        question_type="SA",
        answer_options=[AnswerOption("1", "Brand A"), AnswerOption("2", "Brand B")],
    ),
    SurveyQuestion(
        question_number="Q2", question_text="Why did you choose [Q1 response]?",
        question_type="OE",
    ),
    SurveyQuestion(
        question_number="Q3", question_text="Rate {Q1_answer} on satisfaction",
        question_type="Scale",
    ),
    SurveyQuestion(
        question_number="Q4", question_text="Additional comments about <<Q1>>",
        question_type="OE",
    ),
    SurveyQuestion(
        question_number="Q5", question_text="Usage frequency",
        question_type="SA",
        instructions="Pipe selected brands from Q1",
        filter_condition="Q1=1 or Q1=2",
    ),
    SurveyQuestion(
        question_number="Q6", question_text="Recommendation",
        question_type="SA",
        filter_condition="Q5=1",
    ),
]

# ── 1. Text piping 탐지 ──
text_refs = detect_text_piping(questions)
print(f"Text piping refs: {len(text_refs)}")
assert len(text_refs) >= 3, f"Expected at least 3 text piping refs, got {len(text_refs)}"
# Q2, Q3, Q4 모두 Q1을 참조
sources = {r.source_qn for r in text_refs}
assert "Q1" in sources, "Q1 should be a source"
targets = {r.target_qn for r in text_refs}
assert "Q2" in targets, "Q2 should be a target"
assert "Q3" in targets, "Q3 should be a target"
assert "Q4" in targets, "Q4 should be a target"

# ── 2. Code piping 탐지 ──
code_refs = detect_code_piping(questions)
print(f"Code piping refs: {len(code_refs)}")
assert len(code_refs) >= 1, f"Expected at least 1 code piping ref, got {len(code_refs)}"
assert any(r.target_qn == "Q5" for r in code_refs), "Q5 should have code piping from instructions"

# ── 3. Filter dependency 탐지 ──
filter_refs = detect_filter_dependencies(questions)
print(f"Filter deps: {len(filter_refs)}")
assert len(filter_refs) >= 2, f"Expected at least 2 filter deps, got {len(filter_refs)}"
# Q5 depends on Q1, Q6 depends on Q5
assert any(r.source_qn == "Q1" and r.target_qn == "Q5" for r in filter_refs)
assert any(r.source_qn == "Q5" and r.target_qn == "Q6" for r in filter_refs)

# ── 4. Filter chains ──
chains, bottlenecks = build_filter_chains(questions, filter_refs)
print(f"Filter chains: {len(chains)}, Bottlenecks: {len(bottlenecks)}")
assert len(chains) >= 1, "Expected at least 1 filter chain"

# ── 5. Validation ──
all_refs = text_refs + code_refs + filter_refs
issues = validate_piping(questions, all_refs)
print(f"Issues: {len(issues)}")
# 순환참조는 없어야 함
circular = [i for i in issues if i.issue_type == "circular"]
assert len(circular) == 0, f"Unexpected circular references: {circular}"

# ── 6. DOT 생성 ──
dot = generate_piping_dot(all_refs, questions)
assert "digraph Piping" in dot, "DOT should contain 'digraph Piping'"
assert "Q1" in dot, "DOT should contain Q1"
print(f"DOT length: {len(dot)} chars")

# ── 7. 빈 입력 ──
assert detect_text_piping([]) == []
assert detect_code_piping([]) == []
assert detect_filter_dependencies([]) == []

# ── 8. 순서 오류 탐지 ──
# Q1이 Q2를 참조하는 케이스 (역순)
reverse_refs = [PipingRef(source_qn="Q2", target_qn="Q1", pipe_type="text_piping", context="test")]
reverse_issues = validate_piping(questions, reverse_refs)
ordering = [i for i in reverse_issues if i.issue_type == "ordering"]
assert len(ordering) >= 1, "Expected ordering issue for reverse reference"

print("All piping smoke tests passed!")
