# tests/smoke_test_banner_assignment.py
"""Banner assignment semantic fitness + expand_banner_ids 검증"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from models.survey import Banner, BannerPoint, SurveyQuestion
from services.table_guide_service import (
    _extract_all_banner_qns,
    _extract_filter_qns,
    assign_banners_to_questions,
    expand_banner_ids,
)


# ══════════════════════════════════════════════════════════════════
# _extract_all_banner_qns
# ══════════════════════════════════════════════════════════════════

def _make_banner(banner_id, name, points_data):
    """테스트용 Banner 생성 헬퍼."""
    pts = []
    for i, (src, cond) in enumerate(points_data):
        pts.append(BannerPoint(
            point_id=f"BP_{i+1}", label=f"Label{i+1}",
            source_question=src, condition=cond,
        ))
    return Banner(banner_id=banner_id, name=name, points=pts)


# Simple case: source_question only
b1 = _make_banner("A", "Gender", [("S1", "S1=1"), ("S1", "S1=2")])
qns = _extract_all_banner_qns(b1)
assert "S1" in qns, f"Expected S1 in {qns}"

# Composite: source_question with "&"
b2 = _make_banner("B", "Combo", [("A1&A2", "A1=1&A2=3")])
qns = _extract_all_banner_qns(b2)
assert "A1" in qns and "A2" in qns, f"Expected A1, A2 in {qns}"

# Empty source
b3 = _make_banner("C", "Empty", [("", "")])
qns = _extract_all_banner_qns(b3)
assert qns == set(), f"Expected empty set, got {qns}"

# Case insensitivity: stored as uppercase
b4 = _make_banner("D", "MixCase", [("sq1", "SQ1=1")])
qns = _extract_all_banner_qns(b4)
assert "SQ1" in qns, f"Expected SQ1 in {qns}"

# Condition-only extraction (no source_question match)
b5 = _make_banner("E", "CondOnly", [("S2", "Q5=1")])
qns = _extract_all_banner_qns(b5)
assert "S2" in qns and "Q5" in qns, f"Expected S2, Q5 in {qns}"

print("  _extract_all_banner_qns: ALL PASSED")


# ══════════════════════════════════════════════════════════════════
# _extract_filter_qns
# ══════════════════════════════════════════════════════════════════

# Simple filter
fq = _extract_filter_qns("Q2=3,4 응답자만")
assert "Q2" in fq, f"Expected Q2 in {fq}"

# Compound filter
fq = _extract_filter_qns("Q3=1 AND S1=2")
assert "Q3" in fq and "S1" in fq, f"Expected Q3, S1 in {fq}"

# Korean-only text (no question numbers)
fq = _extract_filter_qns("전체 응답자")
assert fq == set(), f"Expected empty set, got {fq}"

# None
fq = _extract_filter_qns(None)
assert fq == set(), f"Expected empty set, got {fq}"

# Empty string
fq = _extract_filter_qns("")
assert fq == set(), f"Expected empty set, got {fq}"

print("  _extract_filter_qns: ALL PASSED")


# ══════════════════════════════════════════════════════════════════
# assign_banners_to_questions
# ══════════════════════════════════════════════════════════════════

# Test banners
banners = [
    _make_banner("A", "Gender", [("S1", "S1=1"), ("S1", "S1=2")]),
    _make_banner("B", "Age", [("S2", "S2=1"), ("S2", "S2=2")]),
    _make_banner("C", "Brand", [("Q3", "Q3=1"), ("Q3", "Q3=2")]),
]


def _q(qn, role="", qtype="SA", filter_cond=None):
    """테스트용 SurveyQuestion 생성 헬퍼."""
    return SurveyQuestion(
        question_number=qn, question_text=f"Text for {qn}",
        question_type=qtype, role=role, filter_condition=filter_cond,
    )


# Rule 1: screening → empty
result = assign_banners_to_questions([_q("S1", role="screening")], banners)
assert result["S1"] == "", f"Screening should be empty: {result['S1']}"

# Rule 1 fallback: S-prefix → empty
result = assign_banners_to_questions([_q("S5")], banners)
assert result["S5"] == "", f"S-prefix should be screening: {result['S5']}"

# Rule 2: demographics → empty
result = assign_banners_to_questions([_q("D1", role="demographics")], banners)
assert result["D1"] == "", f"Demographics should be empty: {result['D1']}"

# Rule 3: OE → empty
result = assign_banners_to_questions([_q("Q10", qtype="OE")], banners)
assert result["Q10"] == "", f"OE should be empty: {result['Q10']}"

result = assign_banners_to_questions([_q("Q11", qtype="OPEN-END")], banners)
assert result["Q11"] == "", f"OPEN should be empty: {result['Q11']}"

# Rule 4: self-reference → excluded
# Q3 is referenced by banner C → should get only A,B
result = assign_banners_to_questions([_q("Q3", role="main")], banners)
assert "C" not in result["Q3"].split(","), f"Q3 should exclude C: {result['Q3']}"
assert "A" in result["Q3"].split(",") and "B" in result["Q3"].split(","), \
    f"Q3 should have A,B: {result['Q3']}"

# Rule 5: filter overlap → excluded
# Q7 has filter "S1=1 응답자" → S1 referenced by banner A → exclude A
result = assign_banners_to_questions(
    [_q("Q7", role="main", filter_cond="S1=1 응답자")], banners
)
assert "A" not in result["Q7"].split(","), f"Q7 filter overlap should exclude A: {result['Q7']}"
assert "B" in result["Q7"].split(",") and "C" in result["Q7"].split(","), \
    f"Q7 should have B,C: {result['Q7']}"

# Rule 6: normal question → all applicable
result = assign_banners_to_questions([_q("Q1", role="main")], banners)
assert result["Q1"] == "A,B,C", f"Normal should get all: {result['Q1']}"

# No banners → all empty
result = assign_banners_to_questions([_q("Q1")], [])
assert result["Q1"] == "", f"No banners should be empty: {result['Q1']}"

print("  assign_banners_to_questions: ALL PASSED")


# ══════════════════════════════════════════════════════════════════
# expand_banner_ids
# ══════════════════════════════════════════════════════════════════

test_banners = [
    Banner(banner_id="A", name="Gender", points=[]),
    Banner(banner_id="B", name="Age", points=[]),
    Banner(banner_id="C", name="Ownership", points=[]),
]

# Normal
assert expand_banner_ids("A,B,C", test_banners) == "A(Gender), B(Age), C(Ownership)"

# Single
assert expand_banner_ids("A", test_banners) == "A(Gender)"

# Empty string
assert expand_banner_ids("", test_banners) == ""

# None-like
assert expand_banner_ids("  ", test_banners) == ""

# Missing banner ID
assert expand_banner_ids("A,X", test_banners) == "A(Gender), X"

# No banners
assert expand_banner_ids("A,B", []) == "A,B"

print("  expand_banner_ids: ALL PASSED")

print("\n=== ALL BANNER ASSIGNMENT TESTS PASSED ===")
