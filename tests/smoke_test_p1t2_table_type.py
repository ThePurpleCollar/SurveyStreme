import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.docx_parser import _classify_table, DocxTable
from services.docx_renderer import render_table

# Test 1: section_header (1x1 표)
assert _classify_table([["SECTION A: AWARENESS"]]) == "section_header"
assert _classify_table([[""]]) == "unknown"  # 빈 1x1은 unknown
print("Test 1: section_header 분류 OK")

# Test 2: coding_reference (Variable/Code/Label 헤더)
assert _classify_table([
    ["Variable", "Code", "Label"],
    ["Q1_1", "1", "Very satisfied"],
    ["Q1_1", "2", "Satisfied"],
]) == "coding_reference"
assert _classify_table([
    ["Code", "Label"],
    ["1", "Brand A"],
    ["2", "Brand B"],
]) == "coding_reference"
# 한국어 키워드
assert _classify_table([
    ["변수", "코드", "설명"],
    ["Q1", "1", "만족"],
]) == "coding_reference"
print("Test 2: coding_reference 분류 OK")

# Test 3: multi_question (첫 열에 문항 번호)
assert _classify_table([
    ["Q5a.", "브랜드 인지도", "1", "2", "3"],
    ["Q5b.", "최근 구매 경험", "1", "2", "3"],
    ["Q5c.", "재구매 의향", "1", "2", "3"],
]) == "multi_question"
print("Test 3: multi_question 분류 OK")

# Test 4: code_label (2열 숫자+텍스트)
assert _classify_table([
    ["1", "매우 만족"],
    ["2", "만족"],
    ["3", "보통"],
    ["4", "불만족"],
    ["99", "모름"],
]) == "code_label"
print("Test 4: code_label 분류 OK")

# Test 5: grid (숫자 헤더 + 행 항목)
assert _classify_table([
    ["", "1", "2", "3", "4", "5"],
    ["브랜드 이미지", "○", "○", "○", "○", "○"],
    ["제품 품질", "○", "○", "○", "○", "○"],
    ["가격 경쟁력", "○", "○", "○", "○", "○"],
]) == "grid"
print("Test 5: grid 분류 OK")

# Test 6: DocxTable 기본값
t = DocxTable()
assert t.table_type == "unknown", f"기본값이 'unknown'이어야 하는데 '{t.table_type}'"
print("Test 6: DocxTable 기본값 OK")

# Test 7: render_table — section_header
t_sh = DocxTable(rows=[["SECTION A: AWARENESS"]], row_count=1, col_count=1,
                  table_type="section_header")
rendered = render_table(t_sh)
assert "[SECTION: SECTION A: AWARENESS]" in rendered
print("Test 7: section_header 렌더링 OK")

# Test 8: render_table — coding_reference (마커로 보존)
t_cr = DocxTable(rows=[["Variable", "Code"], ["Q1", "1"]], row_count=2, col_count=2,
                  table_type="coding_reference")
rendered = render_table(t_cr)
assert "[CODING_REF" in rendered, f"coding_reference는 마커로 보존되어야 함: '{rendered}'"
print("Test 8: coding_reference 렌더링 마커 보존 OK")

# Test 9: render_table — multi_question
t_mq = DocxTable(
    rows=[["Q5a.", "브랜드 인지도", "1", "2"], ["Q5b.", "구매 경험", "1", "2"]],
    row_count=2, col_count=4, table_type="multi_question"
)
rendered = render_table(t_mq)
assert "[TABLE:multi_question" in rendered
print("Test 9: multi_question 렌더링 OK")

# Test 10: render_table — code_label
t_cl = DocxTable(
    rows=[["1", "만족"], ["2", "불만족"]],
    row_count=2, col_count=2, table_type="code_label"
)
rendered = render_table(t_cl)
assert "[TABLE:options]" in rendered
assert "[/TABLE]" in rendered
print("Test 10: code_label 렌더링 OK")

# Test 11: import 체인
from services.docx_parser import parse_docx
from services.chunker import chunk_sections
print("Test 11: import 체인 OK")

print("\nALL P1-T2 TESTS PASSED")
