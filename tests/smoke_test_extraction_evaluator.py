import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from models.survey import AnswerOption, SkipLogic, SurveyDocument, SurveyQuestion
from services.extraction_evaluator import evaluate_documents


expected = SurveyDocument(
    filename="gt.json",
    questions=[
        SurveyQuestion(
            question_number="Q1",
            question_text="Gender",
            question_type="SA",
            answer_options=[AnswerOption("1", "Male"), AnswerOption("2", "Female")],
            skip_logic=[SkipLogic("Q1=2", "Q3")],
        ),
        SurveyQuestion(
            question_number="Q2",
            question_text="Age",
            question_type="NUMERIC",
            filter_condition="Q1=1",
        ),
    ],
)

actual = SurveyDocument(
    filename="session.json",
    questions=[
        SurveyQuestion(
            question_number="Q1",
            question_text="Gender",
            question_type="SA",
            answer_options=[AnswerOption("1", "Male")],
            skip_logic=[],
        ),
        SurveyQuestion(
            question_number="QX",
            question_text="Extra",
            question_type="OE",
        ),
    ],
)

report = evaluate_documents(expected, actual)

assert report["counts"]["expected_questions"] == 2
assert report["counts"]["actual_questions"] == 2
assert report["counts"]["matched_questions"] == 1
assert report["metrics"]["question_recall"] == 0.5
assert report["metrics"]["question_precision"] == 0.5
assert report["metrics"]["type_accuracy"] == 1.0
assert report["metrics"]["option_code_label_recall"] == 0.5
assert report["metrics"]["skip_recall"] == 0.0
assert report["missing_questions"] == ["Q2"]
assert report["extra_questions"] == ["QX"]
assert report["option_mismatches"]
assert report["skip_mismatches"]

print("ALL EXTRACTION EVALUATOR TESTS PASSED")
