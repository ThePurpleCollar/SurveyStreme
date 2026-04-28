import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd

from models.survey import AnswerOption, SurveyDocument, SurveyQuestion
from ui.spreadsheet import apply_spreadsheet_edits_to_document


doc = SurveyDocument(filename="test.docx", questions=[
    SurveyQuestion(
        question_number="Q1",
        table_number="Q1",
        question_text="Original",
        question_type="SA",
        answer_options=[AnswerOption("1", "Old")],
    )
])

edited = pd.DataFrame([
    {
        "ReviewStatus": "verified",
        "QuestionNumber": "Q1",
        "TableNumber": "Q1",
        "QuestionText": "Updated",
        "QuestionType": "MA",
        "AnswerOptions": "1. Apple | 2. Samsung",
        "SkipLogic": "Q1=2 -> Q3",
        "Filter": "All respondents",
        "Instructions": "ROTATE",
        "SummaryType": "%",
        "ReviewNotes": "Checked against source",
    },
    {
        "ReviewStatus": "needs_review",
        "QuestionNumber": "Q2",
        "TableNumber": "Q2",
        "QuestionText": "Added manually",
        "QuestionType": "OE",
        "AnswerOptions": "",
        "SkipLogic": "",
        "Filter": "",
        "Instructions": "",
        "SummaryType": "%",
        "ReviewNotes": "",
    },
])

doc = apply_spreadsheet_edits_to_document(doc, edited)

assert len(doc.questions) == 2
q1 = doc.questions[0]
assert q1.question_text == "Updated"
assert q1.question_type == "MA"
assert q1.answer_options[1].label == "Samsung"
assert q1.skip_logic[0].target == "Q3"
assert q1.review_status == "verified"
assert q1.review_notes == "Checked against source"

q2 = doc.questions[1]
assert q2.question_number == "Q2"
assert q2.question_text == "Added manually"

print("ALL SPREADSHEET SYNC TESTS PASSED")
