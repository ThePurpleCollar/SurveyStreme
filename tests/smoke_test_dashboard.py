# tests/smoke_test_dashboard.py
"""Intelligence Dashboard 핵심 함수 smoke test"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from models.survey import SurveyQuestion, SurveyDocument, SkipLogic, AnswerOption
from pages.intelligence_dashboard import (
    _estimate_loi_quick,
    _skip_complexity,
    _normalize_type,
)

# ── 테스트 데이터 ──
questions = [
    SurveyQuestion(question_number="Q1", question_text="Gender", question_type="SA",
                   answer_options=[AnswerOption("1", "Male"), AnswerOption("2", "Female")]),
    SurveyQuestion(question_number="Q2", question_text="Brands", question_type="MA",
                   answer_options=[AnswerOption(str(i), f"Brand{i}") for i in range(1, 6)]),
    SurveyQuestion(question_number="Q3", question_text="Satisfaction", question_type="5pt x 3"),
    SurveyQuestion(question_number="Q4", question_text="Why?", question_type="OE"),
    SurveyQuestion(question_number="Q5", question_text="Age", question_type="NUMERIC"),
    SurveyQuestion(question_number="Q6", question_text="Rating", question_type="Scale"),
    SurveyQuestion(question_number="Q7", question_text="Preference", question_type="SA",
                   skip_logic=[SkipLogic(condition="Q7=1", target="Q10")]),
]

# ── LOI 추정 ──
loi = _estimate_loi_quick(questions)
assert isinstance(loi, int), f"LOI should be int, got {type(loi)}"
assert loi > 0, f"LOI should be > 0, got {loi}"
print(f"LOI estimate: {loi} min")

# ── 빈 리스트 ──
assert _estimate_loi_quick([]) == 1

# ── Skip complexity ──
assert _skip_complexity([]) == "Low"
assert _skip_complexity(questions) in ("Low", "Medium")  # 1/7 ≈ 0.14

# Heavy skip
heavy_skip_qs = [
    SurveyQuestion(question_number=f"Q{i}", question_text=f"Q{i}",
                   skip_logic=[SkipLogic(condition="cond", target="target")])
    for i in range(10)
]
assert _skip_complexity(heavy_skip_qs) == "High"

# ── Type normalize ──
assert _normalize_type("SA") == "SA"
assert _normalize_type("MA") == "MA"
assert _normalize_type("OE") == "OE"
assert _normalize_type("5pt x 3") == "Grid/Matrix"
assert _normalize_type("Scale") == "Scale"
assert _normalize_type("NUMERIC") == "Numeric"
assert _normalize_type("") == "Unknown"
assert _normalize_type(None) == "Unknown"
assert _normalize_type("TopN") == "TopN"

print("All dashboard smoke tests passed!")
