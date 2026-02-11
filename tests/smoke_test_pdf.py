# tests/smoke_test_pdf.py
from models.survey import SurveyQuestion, SurveyDocument

# PDF 추출 결과 시뮬레이션
mock_data = [
    ("Q1", "What is your gender?", "SA"),
    ("Q2", "What is your age?", "SA"),
    ("Q3", "How satisfied are you?", "5pt"),
]

questions = []
for qn, text, qtype in mock_data:
    q = SurveyQuestion(question_number=qn, question_text=text, question_type=qtype)
    questions.append(q)

doc = SurveyDocument(filename="test.pdf", questions=questions)
assert len(doc.questions) == 3
assert doc.questions[0].question_number == "Q1"

# to_dataframe 확인
df = doc.to_dataframe()
assert "QuestionNumber" in df.columns
assert len(df) == 3

# JSON 직렬화/역직렬화
import json
json_bytes = doc.to_json_bytes()
restored = SurveyDocument.from_json_dict(json.loads(json_bytes))
assert len(restored.questions) == 3

print("All smoke tests passed!")
