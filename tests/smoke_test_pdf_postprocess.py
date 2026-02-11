# tests/smoke_test_pdf_postprocess.py
"""apply_postprocessing이 PDF-origin SurveyDocument에 정상 동작하는지 확인"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from models.survey import SurveyQuestion, SurveyDocument
from services.postprocessor import apply_postprocessing

# 다양한 QuestionType 시뮬레이션
mock = [
    ("Q1", "Gender", "SA"),
    ("Q2", "Brands", "MA"),
    ("Q3", "Satisfaction", "5pt"),
    ("Q4", "Grid rating", "7pt x 3"),
    ("Q5", "Top choice", "Top3"),
    ("Q6", "Open text", "OE"),
    ("Q7", "Income", "NUMERIC"),
]

questions = [SurveyQuestion(question_number=qn, question_text=t, question_type=qt)
             for qn, t, qt in mock]
doc = SurveyDocument(filename="test.pdf", questions=questions)
apply_postprocessing(doc)

# TableNumber 할당 확인
assert doc.questions[0].table_number == "Q1"
assert doc.questions[6].table_number == "Q7"

# SummaryType 매핑 확인
assert doc.questions[0].summary_type == "%", f"SA -> % but got {doc.questions[0].summary_type}"
assert doc.questions[1].summary_type == "%", f"MA -> % but got {doc.questions[1].summary_type}"
assert "Top2" in doc.questions[2].summary_type, f"5pt should have Top2: {doc.questions[2].summary_type}"
assert "Top2" in doc.questions[3].summary_type, f"7pt x 3 should have Top2: {doc.questions[3].summary_type}"
assert doc.questions[4].summary_type == "%", f"Top3 -> % but got {doc.questions[4].summary_type}"
assert doc.questions[5].summary_type == "%", f"OE -> % but got {doc.questions[5].summary_type}"
assert doc.questions[6].summary_type == "%, mean", f"NUMERIC -> '%, mean' but got {doc.questions[6].summary_type}"

# DataFrame 변환 확인
df = doc.to_dataframe()
assert len(df) == 7
assert list(df["SummaryType"]) == [q.summary_type for q in doc.questions]

# Session save/load round-trip
import json
restored = SurveyDocument.from_json_dict(json.loads(doc.to_json_bytes()))
assert restored.questions[2].summary_type == doc.questions[2].summary_type
assert restored.questions[3].table_number == doc.questions[3].table_number

print("All postprocessing smoke tests passed!")
