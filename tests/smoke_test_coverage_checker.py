import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from models.survey import AnswerOption, SurveyQuestion
from services.coverage_checker import check_extraction_coverage
from services.docx_parser import DocxParagraph, DocxSection, DocxTable


sections = [
    DocxSection(content=[
        DocxParagraph("Q1. Which brand do you use? [SA]"),
        DocxTable(
            rows=[
                ["Apple", "1"],
                ["Samsung", "2"],
                ["Other", "97"],
            ],
            row_count=3,
            col_count=2,
            table_type="code_label",
        ),
        DocxParagraph("Q2. Why? [OE]"),
        DocxTable(
            rows=[["Marketing firm", "1", "TERMINATE"]],
            row_count=1,
            col_count=3,
            table_type="generic",
        ),
    ])
]

questions = [
    SurveyQuestion(
        question_number="Q1",
        question_text="Which brand do you use?",
        question_type="SA",
        answer_options=[AnswerOption("1", "Apple"), AnswerOption("2", "Samsung")],
    ),
    SurveyQuestion(question_number="Q2", question_text="Why?", question_type="OE"),
]

report = check_extraction_coverage(sections, questions)

assert report.detected_questions == 2
assert report.extracted_questions == 2
assert report.tables_with_options == 1
assert report.options_matched == 1
assert report.generic_tables == 1
assert report.skip_patterns_found >= 1  # TERMINATE inside table text is now visible
assert any(i.category == "table_classification" for i in report.items)
assert any(i.category == "table_drilldown" and i.evidence for i in report.items)

print("ALL COVERAGE CHECKER TESTS PASSED")
