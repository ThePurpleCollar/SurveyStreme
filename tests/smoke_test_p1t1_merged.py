import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.docx_parser import DocxCell, DocxTable

# Test 1: DocxCell 기본값
c = DocxCell(text="test")
assert c.is_merged_continuation == False
print("Test 1: DocxCell 기본값 OK")

# Test 2: DocxTable.rows_text (continuation 제거)
raw = [
    [DocxCell("Q5. 브랜드평가"), DocxCell("1"), DocxCell("2"), DocxCell("3")],
    [DocxCell("Q5. 브랜드평가", is_merged_continuation=True),
     DocxCell("브랜드이미지"), DocxCell(""), DocxCell("")],
]
table = DocxTable(raw_cells=raw, row_count=2, col_count=4, has_merged_cells=True)
rt = table.rows_text
assert rt[0] == ["Q5. 브랜드평가", "1", "2", "3"]
assert rt[1] == ["브랜드이미지", "", ""]
print("Test 2: rows_text (continuation 제거) OK")

# Test 3: has_merged_cells 플래그
assert table.has_merged_cells == True
normal = DocxTable(rows=[["1","남성"],["2","여성"]], row_count=2, col_count=2)
assert normal.has_merged_cells == False
print("Test 3: has_merged_cells 플래그 OK")

# Test 4: rows_text fallback (raw_cells 없으면 rows 반환)
assert normal.rows_text == [["1","남성"],["2","여성"]]
print("Test 4: rows_text fallback OK")

# Test 5: import 체인
from services.docx_parser import parse_docx
from services.docx_renderer import render_table
print("Test 5: import 체인 OK")

print("\nALL P1T1-MERGED TESTS PASSED")
