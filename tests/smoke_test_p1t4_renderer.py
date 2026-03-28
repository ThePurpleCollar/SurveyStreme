import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.docx_parser import DocxTable
from services.docx_renderer import render_table

def make_table(rows, table_type="unknown"):
    return DocxTable(rows=rows, row_count=len(rows),
                     col_count=len(rows[0]) if rows else 0,
                     table_type=table_type)

# Test 1: grid 렌더링
t = make_table([["", "1", "2", "3", "4", "5"],
                ["브랜드이미지", "○", "○", "○", "○", "○"],
                ["제품품질", "○", "○", "○", "○", "○"]], "grid")
r = render_table(t)
assert "[TABLE:grid]" in r
assert "[SCALE_HEADER]" in r
assert "[ROW] 브랜드이미지" in r
assert "[/TABLE]" in r
print("Test 1: grid 렌더링 OK")

# Test 2: coding_reference -> 마커로 보존
t2 = make_table([["Code", "Label"], ["1", "만족"]], "coding_reference")
r2 = render_table(t2)
assert "[CODING_REF" in r2
assert "만족" in r2  # 내용이 보존됨
print("Test 2: coding_reference 마커 보존 OK")

# Test 3: section_header
t3 = make_table([["SECTION A"]], "section_header")
r3 = render_table(t3)
assert "[SECTION: SECTION A]" in r3
print("Test 3: section_header 렌더링 OK")

# Test 4: matrix 렌더링
t4 = make_table([["", "구매", "인지", "비인지"],
                  ["Brand A", "", "", ""],
                  ["Brand B", "", "", ""]], "matrix")
r4 = render_table(t4)
assert "[TABLE:matrix]" in r4
assert "[COL_HEADER]" in r4
assert "[ROW] Brand A" in r4
print("Test 4: matrix 렌더링 OK")

# Test 5: code_label 렌더링
t5 = make_table([["1", "만족"], ["2", "불만족"]], "code_label")
r5 = render_table(t5)
assert "[TABLE:options]" in r5
assert "[/TABLE]" in r5
print("Test 5: code_label 렌더링 OK")

# Test 6: multi_question 렌더링
t6 = make_table([["Q5a.", "인지도", "1", "2"],
                  ["Q5b.", "구매경험", "1", "2"]], "multi_question")
r6 = render_table(t6)
assert "[TABLE:multi_question" in r6
assert "[/TABLE]" in r6
print("Test 6: multi_question 렌더링 OK")

# Test 7: generic 렌더링
t7 = make_table([["a", "b"], ["c", "d"]], "generic")
r7 = render_table(t7)
assert "[TABLE:info]" in r7
print("Test 7: generic 렌더링 OK")

# Test 8: SYSTEM_PROMPT에 RENDERING MARKERS 존재
from services.llm_extractor import SYSTEM_PROMPT
assert "RENDERING MARKERS" in SYSTEM_PROMPT
assert "[TABLE:grid]" in SYSTEM_PROMPT
assert "TEXTBOX" in SYSTEM_PROMPT
print("Test 8: SYSTEM_PROMPT RENDERING MARKERS OK")

print("\nALL P1T4-RENDERER TESTS PASSED")
