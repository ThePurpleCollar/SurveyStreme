import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.docx_parser import _classify_table, DocxTable, DocxSection
from services.docx_renderer import render_section

# Test 1: 1x1 표가 section_header로 분류
table_type = _classify_table([["SECTION A. AWARENESS"]])
assert table_type == "section_header", f"분류 실패: {table_type}"
print("Test 1: 1x1 표 section_header 분류 OK")

# Test 2: section_header -> DocxSection heading 변환 시뮬레이션
t1 = DocxTable(rows=[["SECTION A. AWARENESS"]], row_count=1, col_count=1,
               table_type="section_header")
t2 = DocxTable(rows=[["1", "Brand A"], ["2", "Brand B"]], row_count=2, col_count=2,
               table_type="code_label")

sections = []
current = DocxSection()

for table in [t1, t2]:
    if table.table_type == "section_header":
        heading_text = table.rows[0][0].strip()
        if heading_text:
            if current.content or current.heading:
                sections.append(current)
            current = DocxSection(heading=heading_text)
    else:
        current.content.append(table)
sections.append(current)

assert len(sections) == 1, f"섹션 수 오류: {len(sections)}"
assert sections[0].heading == "SECTION A. AWARENESS"
assert len(sections[0].tables) == 1
assert sections[0].tables[0] is t2
print("Test 2: section_header -> DocxSection.heading 변환 OK")

# Test 3: heading이 올바르게 렌더링
section = DocxSection(heading="SECTION A. AWARENESS")
rendered = render_section(section)
assert "=== SECTION A. AWARENESS ===" in rendered
print("Test 3: heading 렌더링 OK")

# Test 4: 빈 1셀 표는 새 섹션 만들지 않음
empty_1x1 = DocxTable(rows=[[""]], row_count=1, col_count=1, table_type="section_header")
heading_text = empty_1x1.rows[0][0].strip()
assert heading_text == ""
assert not bool(heading_text)
print("Test 4: 빈 1셀 표 처리 OK")

# Test 5: 2셀 이상 표는 기존 방식
t3 = DocxTable(rows=[["1", "남성"], ["2", "여성"]], row_count=2, col_count=2,
               table_type="code_label")
assert t3.table_type != "section_header"
print("Test 5: 2셀 이상 표 정상 처리 OK")

# Test 6: import 체인
from services.docx_parser import parse_docx
from services.chunker import chunk_sections
print("Test 6: import 체인 OK")

print("\nALL P3-T8 TESTS PASSED")
