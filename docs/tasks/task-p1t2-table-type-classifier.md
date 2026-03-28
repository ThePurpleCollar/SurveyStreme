# TASK-P1T2: 표 타입 분류기 확장

## Status: 🔴 Not Started

## 선행 조건

**TASK-P1T1 완료 권장** — `_parse_table()` 수정과 같은 파일이므로 충돌 방지를 위해 순서 준수.

## 배경 및 문제 정의

실제 설문지 7개 파일 분석에서 발견된 추가 표 패턴:

현재 `DocxTable`에는 `table_type` 필드가 없고 모든 표가 동일하게 처리된다.
이전 작업 계획에서 `code_label`, `grid`, `matrix`, `generic` 4개 타입을 설계했지만,
실제 설문지에는 LLM이 문항이 아님을 명확히 알아야 하는 3가지 추가 패턴이 존재한다:

### 신규 발견 패턴 1: section_header (섹션 헤더 표)

1행 1열 표로 섹션 제목을 표시하는 패턴. 일부 설문지 템플릿에서 Heading 스타일 대신 사용.

```
┌────────────────────────────────────┐
│ SECTION A: AWARENESS               │  ← 1×1 표, 굵은 글씨 or ALL CAPS
└────────────────────────────────────┘
```

**LLM이 받으면**: 문항 번호 없이 텍스트가 길어 혼란 → `section_header` 타입으로 SKIP 처리 필요

### 신규 발견 패턴 2: coding_reference (코딩 참고 표)

변수명-코드-레이블 구조의 표. 데이터 처리 가이드로 사용되며 응답 보기가 아님.

```
┌──────────┬─────┬──────────────────────┐
│ Variable │ Code│ Label                │  ← 헤더에 Variable/Code/Label
├──────────┼─────┼──────────────────────┤
│ Q1_1     │  1  │ Very satisfied       │
│ Q1_1     │  2  │ Satisfied            │
└──────────┴─────┴──────────────────────┘
```

또는:
```
┌───────┬──────────────────────────────┐
│ Code  │ Label                        │
├───────┼──────────────────────────────┤
│  1    │ Brand A                      │
│  2    │ Brand B                      │
└───────┴──────────────────────────────┘
```

**LLM이 받으면**: 코딩 스펙으로 인식하지 못하고 문항 보기로 오추출

### 신규 발견 패턴 3: multi_question (다중 문항 포함 표)

첫 번째 열에 여러 문항 번호가 있는 표. 배터리 문항 블록을 표 형태로 제시하는 패턴.

```
┌───────┬─────────────────────────────────┬─────┬─────┬─────┐
│ Q5a.  │ 브랜드 인지도                   │  1  │  2  │  3  │
├───────┼─────────────────────────────────┼─────┼─────┼─────┤
│ Q5b.  │ 최근 6개월 구매 경험            │  1  │  2  │  3  │
├───────┼─────────────────────────────────┼─────┼─────┼─────┤
│ Q5c.  │ 재구매 의향                     │  1  │  2  │  3  │
└───────┴─────────────────────────────────┴─────┴─────┴─────┘
```

**LLM이 받으면**: 표 내 각 행이 별도 문항임을 파악 못하고 단일 문항으로 추출

## Goal

1. `DocxTable`에 `table_type: str` 필드 추가 (기본값 `"unknown"`)
2. `_classify_table()` 함수 구현 — 7가지 타입 분류:
   - 기존: `code_label`, `grid`, `matrix`, `generic`
   - 신규: `section_header`, `coding_reference`, `multi_question`
   - 기타: `unknown` (분류 불가)
3. `_parse_table()`에서 `_classify_table()` 호출하여 `table_type` 설정
4. `docx_renderer.py`의 `render_table()`에서 타입별 힌트 마커 추가
5. LLM SYSTEM_PROMPT에 신규 타입 설명 추가 (TASK-P2T6에서 더 확장 예정이나 기본은 여기서)

## 수정 대상 파일

- `services/docx_parser.py` — `DocxTable` 필드 추가 + `_classify_table()` 구현
- `services/docx_renderer.py` — `render_table()` 타입별 분기 추가
- `tests/smoke_test_p1t2_table_type.py` — 신규 생성

## Implementation Steps

### Step 1: DocxTable에 table_type 필드 추가 (docx_parser.py)

```python
@dataclass
class DocxTable:
    """DOCX 테이블"""
    rows: List[List[str]] = field(default_factory=list)
    header_row: List[str] = field(default_factory=list)
    row_count: int = 0
    col_count: int = 0
    table_type: str = "unknown"  # ← 신규 추가
```

### Step 2: _classify_table() 구현 (docx_parser.py)

`_parse_table()` 함수 바로 위에 추가:

```python
# 코딩 참고 표 헤더 키워드
_CODING_REF_HEADERS = frozenset({
    'variable', 'var', 'code', 'label', 'value', 'name', 'description',
    '변수', '코드', '레이블', '값', '이름', '설명', '항목'
})

# 문항 번호 패턴 (multi_question 감지용)
import re as _re
_QN_IN_CELL_RE = _re.compile(
    r'^[A-Za-z]+\d+[a-z]?[.)\s]',   # Q1. Q1a. SQ2)
)


def _classify_table(rows: List[List[str]]) -> str:
    """표의 내용을 분석하여 타입을 분류한다.
    
    Returns:
        'section_header' | 'coding_reference' | 'multi_question' |
        'code_label' | 'grid' | 'matrix' | 'generic' | 'unknown'
    """
    if not rows:
        return "unknown"

    row_count = len(rows)
    col_count = max(len(r) for r in rows) if rows else 0

    # ── section_header: 1×1 표, 텍스트가 있는 경우 ──
    if row_count == 1 and col_count == 1:
        text = rows[0][0].strip()
        if text:
            return "section_header"
        return "unknown"

    # ── coding_reference: 헤더에 Variable/Code/Label 키워드 포함 ──
    if rows:
        header_cells = [c.strip().lower() for c in rows[0] if c.strip()]
        header_matches = sum(1 for c in header_cells if c in _CODING_REF_HEADERS)
        # 헤더 셀의 40% 이상이 코딩 키워드면 coding_reference
        if header_cells and header_matches / len(header_cells) >= 0.4:
            return "coding_reference"

    # ── multi_question: 첫 번째 열에 여러 문항 번호 패턴 ──
    if col_count >= 2:
        first_col_values = [rows[i][0].strip() for i in range(row_count) 
                            if rows[i] and rows[i][0].strip()]
        qn_count = sum(1 for v in first_col_values if _QN_IN_CELL_RE.match(v))
        # 첫 번째 열의 50% 이상이 문항 번호 패턴이면 multi_question
        if first_col_values and qn_count / len(first_col_values) >= 0.5 and qn_count >= 2:
            return "multi_question"

    # ── code_label: 2열 표, 첫 열이 숫자/코드, 두 번째 열이 텍스트 ──
    if col_count == 2 and row_count >= 2:
        data_rows = rows[1:] if len(rows) > 1 else rows  # 헤더 제외
        numeric_first = sum(
            1 for r in data_rows
            if r[0].strip() and r[0].strip().lstrip('-').isdigit()
        )
        if data_rows and numeric_first / len(data_rows) >= 0.6:
            return "code_label"

    # ── grid: 첫 행이 숫자 척도, 나머지 행이 항목 ──
    if row_count >= 3 and col_count >= 3:
        header = [c.strip() for c in rows[0] if c.strip()]
        # 첫 번째 열 제외한 헤더가 숫자들인지 확인
        scale_headers = [c for c in header[1:] if c] if len(header) > 1 else header
        numeric_headers = sum(1 for c in scale_headers if c.isdigit() or 
                              c in ('○', '●', '□', '■'))
        if scale_headers and numeric_headers / len(scale_headers) >= 0.6:
            return "grid"

    # ── matrix: 첫 행이 범주 레이블, 나머지 행이 항목 ──
    if row_count >= 3 and col_count >= 3:
        # 첫 열 값들이 텍스트 항목인지 확인 (문항 번호 패턴 제외)
        first_col = [rows[i][0].strip() for i in range(1, row_count) if rows[i]]
        non_numeric = sum(1 for v in first_col if v and not v.lstrip('-').isdigit())
        if first_col and non_numeric / len(first_col) >= 0.7:
            return "matrix"

    # ── generic: 위 어디에도 해당하지 않는 일반 표 ──
    return "generic"
```

### Step 3: _parse_table()에서 _classify_table() 호출 (docx_parser.py)

```python
def _parse_table(table) -> DocxTable:
    """python-docx Table을 DocxTable로 변환.
    
    취소선 셀은 빈 문자열로 처리하고, 표 타입을 자동 분류한다.
    """
    rows_data = []
    for row in table.rows:
        row_data = []
        for cell in row.cells:
            if _is_cell_strikethrough(cell):
                row_data.append("")
            else:
                row_data.append(cell.text.strip())
        rows_data.append(row_data)

    table_type = _classify_table(rows_data)  # ← 타입 분류

    return DocxTable(
        rows=rows_data,
        header_row=rows_data[0] if rows_data else [],
        row_count=len(rows_data),
        col_count=len(rows_data[0]) if rows_data else 0,
        table_type=table_type,  # ← 신규 필드
    )
```

### Step 4: docx_renderer.py의 render_table()에 타입 힌트 마커 추가

기존 `render_table()` 함수를 타입별로 분기하여 LLM 힌트를 추가:

```python
def render_table(table: DocxTable) -> str:
    """DocxTable을 LLM 친화적 텍스트로 변환.
    
    table_type에 따라 적절한 마커를 추가하여 LLM이 표의 역할을 파악할 수 있게 함.
    """
    if not table.rows:
        return ""

    table_type = getattr(table, 'table_type', 'unknown')

    # section_header: 단순 텍스트로 변환 (표 구조 불필요)
    if table_type == "section_header":
        text = table.rows[0][0].strip() if table.rows and table.rows[0] else ""
        return f"\n[SECTION: {text}]\n" if text else ""

    # coding_reference: 스킵 (LLM에 전달하지 않음 — 문항 추출 대상 아님)
    if table_type == "coding_reference":
        return ""

    # 나머지 타입: 기존 마크다운 렌더링 + 타입 마커
    lines = [""]
    
    if table_type == "multi_question":
        lines.append("[TABLE:multi_question — 각 행이 별도 문항]")
    elif table_type == "grid":
        lines.append("[TABLE:grid — 척도형 배터리]")
    elif table_type == "matrix":
        lines.append("[TABLE:matrix — 다중 범주]")
    elif table_type == "code_label":
        lines.append("[TABLE:options]")

    for i, row in enumerate(table.rows):
        line = "| " + " | ".join(cell if cell else "" for cell in row) + " |"
        lines.append(line)
        if i == 0:
            separator = "| " + " | ".join("---" for _ in row) + " |"
            lines.append(separator)

    if table_type == "code_label":
        lines.append("[/TABLE]")

    lines.append("")
    return "\n".join(lines)
```

## Do NOT Change

- `DocxSection`, `DocxParagraph`, `DocxRun` dataclass 구조
- `parse_docx()` 함수의 섹션 분리 로직 (TASK-P3T8에서 처리)
- `chunker.py` 전체
- `llm_extractor.py`의 SYSTEM_PROMPT (TASK-P2T6에서 처리)

## Verification Checklist

- [ ] `python -m py_compile services/docx_parser.py` 성공
- [ ] `python -m py_compile services/docx_renderer.py` 성공
- [ ] `python -c "from services.docx_parser import DocxTable; t = DocxTable(); print(t.table_type)"` → `"unknown"` 출력
- [ ] `python -c "from services.docx_parser import _classify_table; print(_classify_table([['']]))"` → `"unknown"` 출력
- [ ] `python -c "from app import *; print('import OK')"` 성공
- [ ] Smoke Test 통과
- [ ] `section_header` → `[SECTION: ...]` 렌더링 확인
- [ ] `coding_reference` → 빈 문자열 렌더링 (LLM에 전달 안 됨) 확인
- [ ] `multi_question` → `[TABLE:multi_question]` 마커 포함 확인
- [ ] `code_label` → `[TABLE:options]...[/TABLE]` 확인
- [ ] 기존 표 타입 없이 생성한 `DocxTable()`의 기본값이 `"unknown"` 확인

## Smoke Test Script

```python
# tests/smoke_test_p1t2_table_type.py
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.docx_parser import _classify_table, DocxTable
from services.docx_renderer import render_table

# ── Test 1: section_header (1×1 표) ──
assert _classify_table([["SECTION A: AWARENESS"]]) == "section_header"
assert _classify_table([[""]]) == "unknown"  # 빈 1×1은 unknown
print("✅ Test 1: section_header 분류 OK")

# ── Test 2: coding_reference (Variable/Code/Label 헤더) ──
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
print("✅ Test 2: coding_reference 분류 OK")

# ── Test 3: multi_question (첫 열에 문항 번호) ──
assert _classify_table([
    ["Q5a.", "브랜드 인지도", "1", "2", "3"],
    ["Q5b.", "최근 구매 경험", "1", "2", "3"],
    ["Q5c.", "재구매 의향", "1", "2", "3"],
]) == "multi_question"
print("✅ Test 3: multi_question 분류 OK")

# ── Test 4: code_label (2열 숫자+텍스트) ──
assert _classify_table([
    ["1", "매우 만족"],
    ["2", "만족"],
    ["3", "보통"],
    ["4", "불만족"],
    ["99", "모름"],
]) == "code_label"
print("✅ Test 4: code_label 분류 OK")

# ── Test 5: grid (숫자 헤더 + 행 항목) ──
assert _classify_table([
    ["", "1", "2", "3", "4", "5"],
    ["브랜드 이미지", "○", "○", "○", "○", "○"],
    ["제품 품질", "○", "○", "○", "○", "○"],
    ["가격 경쟁력", "○", "○", "○", "○", "○"],
]) == "grid"
print("✅ Test 5: grid 분류 OK")

# ── Test 6: DocxTable 기본값 ──
t = DocxTable()
assert t.table_type == "unknown", f"기본값이 'unknown'이어야 하는데 '{t.table_type}'"
print("✅ Test 6: DocxTable 기본값 OK")

# ── Test 7: render_table — section_header ──
t_sh = DocxTable(rows=[["SECTION A: AWARENESS"]], row_count=1, col_count=1,
                  table_type="section_header")
rendered = render_table(t_sh)
assert "[SECTION: SECTION A: AWARENESS]" in rendered
print("✅ Test 7: section_header 렌더링 OK")

# ── Test 8: render_table — coding_reference (빈 문자열) ──
t_cr = DocxTable(rows=[["Variable", "Code"], ["Q1", "1"]], row_count=2, col_count=2,
                  table_type="coding_reference")
rendered = render_table(t_cr)
assert rendered == "", f"coding_reference는 빈 문자열이어야 함: '{rendered}'"
print("✅ Test 8: coding_reference 렌더링 스킵 OK")

# ── Test 9: render_table — multi_question ──
t_mq = DocxTable(
    rows=[["Q5a.", "브랜드 인지도", "1", "2"], ["Q5b.", "구매 경험", "1", "2"]],
    row_count=2, col_count=4, table_type="multi_question"
)
rendered = render_table(t_mq)
assert "[TABLE:multi_question" in rendered
print("✅ Test 9: multi_question 렌더링 OK")

# ── Test 10: import 체인 ──
from services.docx_parser import parse_docx
from services.chunker import split_into_chunks
print("✅ Test 10: import 체인 OK")

print("\n🎉 ALL P1-T2 TESTS PASSED")
```

## 예상 소요 시간

약 2시간 (분류 로직 1시간 + 렌더러 수정 30분 + 테스트 30분)

## 다음 Task

이 Task 완료 후 → **TASK-P2T6** (프롬프트 + JSON 스키마 업데이트)로 진행.
P3T8(1셀 표 섹션 헤더 패턴)은 독립적이므로 병행 가능.
