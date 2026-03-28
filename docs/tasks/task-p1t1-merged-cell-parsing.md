# TASK-P1T1: _parse_table() 병합 셀 완전 처리

## Status: 🔴 Not Started

## 배경

`python-docx`의 `row.cells`는 병합된 셀을 **물리적으로 병합된 횟수만큼 반복 반환**한다.
예: 3열 병합이면 동일 텍스트가 3번 나타남 → Grid 문항 스템이 중복되거나 누락.

현재 코드:
```python
row_data = [cell.text.strip() for cell in row.cells]  # 병합 셀 중복 발생
```

## Goal

1. `DocxCell` dataclass 추가 (text + `is_merged_continuation` 플래그)
2. `_parse_table()`을 `seen_tc_ids` 방식으로 중복 제거
3. `DocxTable.has_merged_cells` 플래그 추가 (grid 분류에 활용)
4. `DocxTable.rows_text` 프로퍼티 추가 (continuation 제거한 clean 텍스트 리스트)

## Files to Modify

- `services/docx_parser.py`
- `tests/smoke_test_p1t1_merged.py` (신규)

## Implementation Steps

### Step 1: DocxCell dataclass 추가 (docx_parser.py)

`DocxTable` 정의 바로 위에 추가:
```python
@dataclass
class DocxCell:
    """표의 개별 셀 — 병합 정보 포함."""
    text: str
    is_merged_continuation: bool = False  # True = 병합으로 인한 복제 셀
    row_span: int = 1
    col_span: int = 1
```

### Step 2: DocxTable 확장

```python
@dataclass
class DocxTable:
    rows: List[List[str]] = field(default_factory=list)       # 하위 호환용 유지
    header_row: List[str] = field(default_factory=list)
    row_count: int = 0
    col_count: int = 0
    has_merged_cells: bool = False                             # ← 신규
    raw_cells: List[List[DocxCell]] = field(default_factory=list)  # ← 신규

    @property
    def rows_text(self) -> List[List[str]]:
        """continuation 셀 제거한 클린 행 텍스트."""
        if not self.raw_cells:
            return self.rows
        return [
            [c.text for c in row if not c.is_merged_continuation]
            for row in self.raw_cells
        ]
```

### Step 3: _parse_table() 재구현

```python
def _parse_table(table) -> DocxTable:
    raw_cells_data: List[List[DocxCell]] = []
    rows_data: List[List[str]] = []
    has_merged = False

    for row in table.rows:
        seen_tc_ids: set = set()
        row_cells: List[DocxCell] = []
        row_text: List[str] = []

        for cell in row.cells:
            tc_id = id(cell._tc)
            is_dup = tc_id in seen_tc_ids
            seen_tc_ids.add(tc_id)

            if is_dup:
                has_merged = True
                row_cells.append(DocxCell(text=cell.text.strip(),
                                          is_merged_continuation=True))
            else:
                row_cells.append(DocxCell(text=cell.text.strip(),
                                          is_merged_continuation=False))
                row_text.append(cell.text.strip())

        raw_cells_data.append(row_cells)
        rows_data.append(row_text)

    return DocxTable(
        rows=rows_data,
        header_row=rows_data[0] if rows_data else [],
        row_count=len(rows_data),
        col_count=len(rows_data[0]) if rows_data else 0,
        has_merged_cells=has_merged,
        raw_cells=raw_cells_data,
    )
```

### Step 4: 취소선 셀 처리 추가 (이 Task에 통합)

`_is_cell_strikethrough()` 헬퍼 추가 + 취소선 셀을 `""` 로 치환.
(상세 스펙: task-p1t1-strikethrough-cells.md 참조)

## Do NOT Change

- `DocxSection`, `DocxParagraph`, `DocxRun` dataclass
- `parse_docx()` 함수의 섹션 분리 로직
- `docx_renderer.py` (P1-T4에서 처리)

## Verification Checklist

- [ ] `python -m py_compile services/docx_parser.py` 성공
- [ ] `python -c "from services.docx_parser import DocxCell, DocxTable; print('OK')"` 성공
- [ ] `DocxTable().has_merged_cells == False` (기본값 확인)
- [ ] `python -c "from app import *; print('import OK')"` 성공
- [ ] Smoke Test 전체 통과
- [ ] 병합 없는 일반 표에서 `rows == rows_text` 확인
- [ ] 기존 `rows` 필드 접근 코드가 영향받지 않음 확인

## Smoke Test Script

```python
# tests/smoke_test_p1t1_merged.py
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.docx_parser import DocxCell, DocxTable

# Test 1: DocxCell 기본값
c = DocxCell(text="test")
assert c.is_merged_continuation == False
print("✅ Test 1: DocxCell 기본값 OK")

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
print("✅ Test 2: rows_text (continuation 제거) OK")

# Test 3: has_merged_cells 플래그
assert table.has_merged_cells == True
normal = DocxTable(rows=[["1","남성"],["2","여성"]], row_count=2, col_count=2)
assert normal.has_merged_cells == False
print("✅ Test 3: has_merged_cells 플래그 OK")

# Test 4: import 체인
from services.docx_parser import parse_docx
from services.docx_renderer import render_table
print("✅ Test 4: import 체인 OK")

print("\n🎉 ALL P1T1-MERGED TESTS PASSED")
```

## 예상 소요 시간

약 2~3시간 (XML 구조 파악 0.5h + 구현 1.5h + 테스트 1h)
