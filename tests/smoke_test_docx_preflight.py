import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.docx_parser import DocxParagraph, DocxSection, DocxTable
from services.docx_preflight import check_docx_preflight


good_sections = [
    DocxSection(heading="Main", content=[
        DocxParagraph("Q1. Which brands do you know? (MA)"),
        DocxTable(
            rows=[["Code", "Label"], ["1", "Apple"], ["2", "Samsung"]],
            row_count=3,
            col_count=2,
            table_type="code_label",
        ),
        DocxParagraph("Q2. How satisfied are you? (5PT SCALE)"),
        DocxTable(
            rows=[["Item", "1", "2", "3", "4", "5"], ["Overall", "", "", "", "", ""]],
            row_count=2,
            col_count=6,
            table_type="grid",
        ),
    ])
]

good = check_docx_preflight(good_sections)
assert good.score >= 80
assert good.question_candidates == 2
assert good.typed_question_candidates == 2
assert good.option_tables == 1
assert good.grid_tables == 1


risky_sections = [
    DocxSection(content=[
        DocxParagraph("Please answer the following"),
        DocxParagraph("This is an instruction only"),
        DocxTable(
            rows=[["Header", "Value"], ["Marketing", "Text"]],
            row_count=2,
            col_count=2,
            table_type="generic",
            has_merged_cells=True,
        ),
    ])
]

risky = check_docx_preflight(risky_sections)
assert risky.score < good.score
assert risky.question_candidates == 0
assert any(i.category == "question_number" for i in risky.issues)

print("ALL DOCX PREFLIGHT TESTS PASSED")
