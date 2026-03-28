# TASK-P3T8: 1셀 표 섹션 헤더 패턴 추가 (Section Detection 강화)

## Status: 🔴 Not Started

## 선행 조건

**TASK-P1T2 완료 필수** — `DocxTable.table_type == "section_header"` 필드가 있어야 함.

## 배경 및 문제 정의

실제 설문지 7개 파일 분석에서 발견된 패턴:

**1셀 표(1×1 table) = 섹션 헤더**

일부 설문지 템플릿에서 Heading 스타일 단락 대신, **1행 1열 표** 안에 섹션 제목을 넣는다.

```
┌──────────────────────────────────────────┐
│ SECTION A. AWARENESS AND CONSIDERATION   │   ← 1×1 표
└──────────────────────────────────────────┘

Q1. 귀하는 다음 브랜드 중 들어본 것이 있으신가요? ...
```

### 현재 문제

`parse_docx()`는 Heading 스타일 단락만 새 섹션 경계로 인식한다:
```python
if parsed.style_name and 'Heading' in parsed.style_name:
    if current_section.content or current_section.heading:
        sections.append(current_section)
    current_section = DocxSection(heading=parsed.text)
```

1셀 표는 이 조건에 해당하지 않으므로:
- 섹션 분리가 되지 않고 모든 내용이 단일 DocxSection에 포함됨
- 청커(chunker)가 섹션 경계를 인식하지 못해 과도한 크기의 단일 청크 생성
- LLM에 `[SECTION: ...]` 마커도 전달되지 않음

### 목표

TASK-P1T2에서 `_classify_table()`이 1×1 표를 `section_header` 타입으로 분류한다.
이 Task에서는 `parse_docx()`가 `section_header` 타입 표를 Heading과 동일하게 
새 섹션 경계로 처리하도록 수정한다.

## Goal

1. `parse_docx()`에서 `section_header` 타입 표를 만나면 새 섹션을 시작
2. 섹션의 `heading`에 표 셀의 텍스트를 설정
3. 해당 표 자체는 섹션 content에 포함하지 않음 (heading으로만 사용)
4. `docx_renderer.py`의 `render_section()`에서 section_header 표가 heading으로 변환되어 `=== TEXT ===` 형식으로 올바르게 렌더링되는지 확인

## 수정 대상 파일

- `services/docx_parser.py` — `parse_docx()` 함수 수정
- `tests/smoke_test_p3t8_section.py` — 신규 생성

## Implementation Steps

### Step 1: parse_docx()에서 1셀 표 섹션 헤더 처리 추가 (docx_parser.py)

현재 `parse_docx()` 내 table 처리 코드:
```python
elif tag == 'tbl':
    if table_index < len(doc.tables):
        table = doc.tables[table_index]
        table_index += 1
        
        parsed_table = _parse_table(table)
        if parsed_table.row_count > 0:
            current_section.content.append(parsed_table)
```

수정 후:
```python
elif tag == 'tbl':
    if table_index < len(doc.tables):
        table = doc.tables[table_index]
        table_index += 1
        
        parsed_table = _parse_table(table)
        if parsed_table.row_count > 0:
            # 1셀 표가 section_header 타입이면 새 섹션 경계로 처리
            if parsed_table.table_type == "section_header":
                heading_text = parsed_table.rows[0][0].strip()
                if heading_text:  # 빈 섹션 헤더 무시
                    if current_section.content or current_section.heading:
                        sections.append(current_section)
                    current_section = DocxSection(heading=heading_text)
                    # parsed_table 자체는 content에 추가하지 않음
                    continue  # 다음 요소로
            # 일반 표는 기존 방식으로 처리
            current_section.content.append(parsed_table)
```

**주의**: `continue`가 `for child in body:` 루프에서 동작하므로,
위 코드 블록이 `elif tag == 'tbl':` 내부의 `if table_index < len(doc.tables):` 블록 안에 있어야 한다.
`continue` 문이 outer for loop에 적용되는지 확인.

실제로는 outer loop에 `continue`가 필요하므로, 아래처럼 flag를 사용하거나 구조를 조정한다:

```python
elif tag == 'tbl':
    if table_index < len(doc.tables):
        table = doc.tables[table_index]
        table_index += 1
        
        parsed_table = _parse_table(table)
        if parsed_table.row_count == 0:
            continue  # (outer for loop으로 continue)
            
        if parsed_table.table_type == "section_header":
            heading_text = parsed_table.rows[0][0].strip()
            if heading_text:
                if current_section.content or current_section.heading:
                    sections.append(current_section)
                current_section = DocxSection(heading=heading_text)
            # heading_text가 있든 없든 content에는 추가하지 않음
        else:
            current_section.content.append(parsed_table)
```

### Step 2: 렌더링 확인 (docx_renderer.py — 변경 불필요)

`render_section()`은 이미 `section.heading`을 `=== heading ===` 형식으로 출력한다.
1셀 표의 텍스트가 `heading`으로 들어가면 자동으로 올바르게 렌더링된다.

단, `render_section()`이 `section_header` 타입 표를 만날 경우를 확인:
→ TASK-P1T2에서 `render_table()`이 `section_header`를 `[SECTION: TEXT]`로 렌더링하므로,
   표가 content에 남아 있으면 `[SECTION: ...]`와 `=== heading ===`이 중복될 수 있다.
→ 이 Task에서 표를 content에 추가하지 않으므로 중복 방지됨. 확인만 할 것.

## Do NOT Change

- `_parse_paragraph()`의 Heading 처리 로직
- `_parse_table()` 함수 (TASK-P1T1, P1T2에서 수정됨, 이 Task에서 건드리지 않음)
- `_classify_table()` 함수
- `chunker.py` 전체
- `docx_renderer.py` 전체 (변경 없음)

## Verification Checklist

- [ ] `python -m py_compile services/docx_parser.py` 성공
- [ ] `python -c "from services.docx_parser import parse_docx; print('import OK')"` 성공
- [ ] `python -c "from app import *; print('import OK')"` 성공
- [ ] Smoke Test 통과
- [ ] 1셀 표가 `DocxSection.heading`으로 변환됨 확인
- [ ] 변환된 1셀 표가 `DocxSection.content`에는 포함되지 않음 확인
- [ ] 기존 Heading 단락으로 섹션 분리되는 문서는 영향받지 않음 확인
- [ ] 2셀 이상 표는 기존 방식으로 처리됨 확인
- [ ] 빈 1셀 표는 새 섹션을 만들지 않음 확인

## Smoke Test Script

```python
# tests/smoke_test_p3t8_section.py
"""1셀 표 섹션 헤더 파싱 smoke test.

parse_docx()를 직접 mock하기 어려우므로,
_classify_table() + DocxSection 생성 로직을 단위로 테스트한다.
실제 DOCX 파일이 있으면 통합 테스트도 추가.
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.docx_parser import _classify_table, DocxTable, DocxSection
from services.docx_renderer import render_section, render_sections_to_annotated_text

# ── Test 1: 1×1 표가 section_header로 분류됨 확인 ──
rows_1x1 = [["SECTION A. AWARENESS"]]
table_type = _classify_table(rows_1x1)
assert table_type == "section_header", f"분류 실패: {table_type}"
print("✅ Test 1: 1×1 표 section_header 분류 OK")

# ── Test 2: section_header 표 → DocxSection heading 변환 시뮬레이션 ──
# parse_docx() 로직을 단순화하여 시뮬레이션
t1 = DocxTable(
    rows=[["SECTION A. AWARENESS"]],
    row_count=1, col_count=1,
    table_type="section_header"
)
t2 = DocxTable(
    rows=[["1", "Brand A"], ["2", "Brand B"]],
    row_count=2, col_count=2,
    table_type="code_label"
)

# 섹션 생성 로직 시뮬레이션
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
assert sections[0].heading == "SECTION A. AWARENESS", f"heading 오류: {sections[0].heading}"
assert len(sections[0].tables) == 1, f"content 오류: {sections[0].tables}"
assert sections[0].tables[0] is t2, "content에 잘못된 표가 포함됨"
print("✅ Test 2: section_header → DocxSection.heading 변환 OK")

# ── Test 3: render_section()에서 heading이 올바르게 렌더링됨 ──
section = DocxSection(heading="SECTION A. AWARENESS")
rendered = render_section(section)
assert "=== SECTION A. AWARENESS ===" in rendered, f"heading 렌더링 오류: {rendered}"
print("✅ Test 3: heading 렌더링 OK")

# ── Test 4: 빈 1셀 표는 새 섹션 만들지 않음 ──
empty_1x1 = DocxTable(rows=[[""]], row_count=1, col_count=1, table_type="section_header")
heading_text = empty_1x1.rows[0][0].strip()
assert heading_text == "", "빈 셀 오류"
# heading_text가 빈 문자열이면 새 섹션을 만들지 않아야 함
new_section_would_be_created = bool(heading_text)
assert not new_section_would_be_created, "빈 1셀 표가 새 섹션을 만들면 안 됨"
print("✅ Test 4: 빈 1셀 표 처리 OK")

# ── Test 5: 2셀 이상 표는 기존 방식으로 처리됨 ──
t3 = DocxTable(rows=[["1", "남성"], ["2", "여성"]], row_count=2, col_count=2,
               table_type="code_label")
assert t3.table_type != "section_header", "2열 표가 section_header로 잘못 분류됨"
print("✅ Test 5: 2셀 이상 표 정상 처리 OK")

# ── Test 6: import 체인 ──
from services.docx_parser import parse_docx
from services.chunker import split_into_chunks
print("✅ Test 6: import 체인 OK")

print("\n🎉 ALL P3-T8 TESTS PASSED")
```

## 예상 소요 시간

약 45분 (구현 20분 + 엣지케이스 확인 15분 + 테스트 10분)

## 다음 Task

Phase P 전체 완료 후 → 실제 설문지 파일로 통합 테스트 진행 권장.
`tests/eval_parsing.py`를 통해 개선 전후 파싱 정확도 비교.
