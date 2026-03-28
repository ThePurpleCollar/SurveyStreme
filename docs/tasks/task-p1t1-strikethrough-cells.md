# TASK-P1T1: _parse_table() 취소선 셀 처리 추가

## Status: 🔴 Not Started

## 배경 및 문제 정의

실제 설문지 7개 파일 분석에서 발견된 패턴:

**취소선(strikethrough) 셀 = 삭제된 보기**

설문지 수정 과정에서 ~~삭제된 보기~~ 를 표시하기 위해 Word 취소선 서식을 사용하는 경우가 빈번하다.
현재 `_parse_table()`은 `cell.text.strip()`으로 텍스트만 추출하므로,
취소선 셀의 텍스트가 유효한 보기로 LLM에 전달된다.

### 발생 사례

```
| 1  | 매우 만족       |   ← 유효 보기
| 2  | 만족           |   ← 유효 보기
| 3  | ~~보통~~        |   ← 취소선 → 삭제된 보기 (LLM에 전달 불가)
| 4  | 불만족         |   ← 유효 보기
| 99 | ~~모르겠음~~    |   ← 취소선 → 삭제된 보기 (LLM에 전달 불가)
```

현재 결과: LLM이 "보통"과 "모르겠음"을 유효 보기로 인식 → answer_options에 포함
목표 결과: 취소선 셀은 빈 문자열 또는 `[DELETED]` 마커로 치환

### 기존 단락 처리와의 차이

`_parse_paragraph()`에서는 **단락 전체**가 취소선이면 `return None`으로 처리한다:
```python
if all_strike and has_runs:
    return None
```

그러나 표의 셀은 단락과 달리:
- 단락을 삭제하면 표 구조가 무너지므로 `None`을 반환할 수 없다
- 빈 문자열 `""` 또는 `"[DELETED]"` 마커로 치환해야 한다

## Goal

1. `_parse_table()`이 각 셀의 취소선 여부를 감지하도록 수정
2. 취소선 셀 텍스트를 `""` (빈 문자열)로 치환
3. `DocxTable.rows`에서 취소선 정보가 보존되는 새 셀 구조를 사용 (선택적 개선)
4. LLM에 전달되는 렌더링에서 취소선 셀을 무시

## 접근 방법

### 방법 A: 단순 텍스트 교체 (권장 — 영향 최소)

`_parse_table()`에서 셀 텍스트를 추출할 때, 셀의 모든 run이 취소선이면 빈 문자열로 교체.

```python
def _is_cell_strikethrough(cell) -> bool:
    """셀의 모든 텍스트 run이 취소선인지 확인."""
    runs_with_text = [run for run in cell.paragraphs[0].runs 
                      if run.text.strip()]
    if not runs_with_text:
        return False
    return all(bool(run.font.strike) for run in runs_with_text)
```

결과: `DocxTable.rows`가 `List[List[str]]` 타입을 유지하므로 하위 호환성 100%.

### 방법 B: 구조화된 DocxCell 도입 (더 완전하지만 범위 큼)

`DocxCell` dataclass를 추가하고, `DocxTable.rows`를 `List[List[DocxCell]]`로 변경.
→ 이 접근은 `docx_renderer.py`와 `chunker.py`의 모든 `row` 접근 코드를 함께 수정해야 함.
→ **Phase P에서는 방법 A를 사용하고, 구조화는 나중으로 미룬다.**

## 수정 대상 파일

- `services/docx_parser.py` — `_parse_table()` 함수 수정
- `tests/smoke_test_p1t1_strikethrough.py` — 신규 생성

## Implementation Steps

### Step 1: `_is_cell_strikethrough()` 헬퍼 추가 (docx_parser.py)

`_parse_table()` 함수 바로 위에 아래 헬퍼를 추가한다:

```python
def _is_cell_strikethrough(cell) -> bool:
    """셀의 텍스트 런이 모두 취소선(strikethrough)인지 확인.
    
    취소선 셀 = 삭제된 보기. 빈 셀이면 False 반환.
    셀 내 여러 단락이 있으면 첫 번째 비어 있지 않은 단락 기준으로 판단.
    """
    for para in cell.paragraphs:
        runs_with_text = [r for r in para.runs if r.text.strip()]
        if not runs_with_text:
            continue
        # 텍스트가 있는 런이 하나라도 있으면 모두 취소선인지 확인
        return all(bool(r.font.strike) for r in runs_with_text)
    return False  # 빈 셀
```

### Step 2: `_parse_table()` 수정 (docx_parser.py)

기존 코드:
```python
def _parse_table(table) -> DocxTable:
    rows_data = []
    for row in table.rows:
        row_data = [cell.text.strip() for cell in row.cells]
        rows_data.append(row_data)
    ...
```

변경 후:
```python
def _parse_table(table) -> DocxTable:
    """python-docx Table을 DocxTable로 변환.
    
    취소선으로 표시된 셀은 삭제된 내용으로 간주하여 빈 문자열로 처리한다.
    """
    rows_data = []
    for row in table.rows:
        row_data = []
        for cell in row.cells:
            if _is_cell_strikethrough(cell):
                row_data.append("")  # 취소선 셀 → 빈 문자열
            else:
                row_data.append(cell.text.strip())
        rows_data.append(row_data)

    return DocxTable(
        rows=rows_data,
        header_row=rows_data[0] if rows_data else [],
        row_count=len(rows_data),
        col_count=len(rows_data[0]) if rows_data else 0,
    )
```

## Do NOT Change

- `DocxTable` dataclass 구조 (`rows: List[List[str]]` 유지)
- `docx_renderer.py`의 `render_table()` 함수 (변경 없음)
- `chunker.py` 전체
- `_parse_paragraph()`의 단락 취소선 처리 로직 (건드리지 않음)
- DOCX 처리 파이프라인의 다른 모든 부분

## Verification Checklist

- [ ] `python -m py_compile services/docx_parser.py` 성공
- [ ] `python -c "from services.docx_parser import parse_docx, DocxTable; print('import OK')"` 성공
- [ ] `python -c "from app import *; print('import OK')"` 성공
- [ ] Smoke Test 통과
- [ ] 취소선 없는 정상 셀은 영향받지 않음 확인
- [ ] 빈 셀(텍스트 없음)은 `False` 반환 (빈 셀을 취소선으로 오인 금지)

## Smoke Test Script

```python
# tests/smoke_test_p1t1_strikethrough.py
"""취소선 셀 처리 smoke test.

python-docx 객체를 직접 mock하기 어려우므로,
_is_cell_strikethrough 함수를 단위 테스트하고
_parse_table의 통합 동작을 검증한다.
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.docx_parser import _is_cell_strikethrough

# ── Test 1: _is_cell_strikethrough 함수 존재 확인 ──
assert callable(_is_cell_strikethrough), "_is_cell_strikethrough 함수가 없습니다"
print("✅ Test 1: _is_cell_strikethrough 함수 존재 OK")

# ── Test 2: Mock 셀로 취소선 감지 확인 ──
class MockFont:
    def __init__(self, strike=False):
        self.strike = strike

class MockRun:
    def __init__(self, text, strike=False):
        self.text = text
        self.font = MockFont(strike)

class MockParagraph:
    def __init__(self, runs):
        self.runs = runs

class MockCell:
    def __init__(self, paragraphs):
        self.paragraphs = paragraphs

# 취소선 셀 (모든 런이 취소선)
strike_cell = MockCell([
    MockParagraph([MockRun("보통", strike=True)])
])
assert _is_cell_strikethrough(strike_cell) == True, "취소선 셀 감지 실패"
print("✅ Test 2: 취소선 셀 감지 OK")

# 일반 셀 (취소선 없음)
normal_cell = MockCell([
    MockParagraph([MockRun("만족", strike=False)])
])
assert _is_cell_strikethrough(normal_cell) == False, "일반 셀 오탐"
print("✅ Test 3: 일반 셀 오탐 없음 OK")

# 빈 셀 (텍스트 없음)
empty_cell = MockCell([
    MockParagraph([MockRun("", strike=True)])
])
assert _is_cell_strikethrough(empty_cell) == False, "빈 셀을 취소선으로 오인"
print("✅ Test 4: 빈 셀 오인 없음 OK")

# 혼합 셀 (일부 취소선, 일부 아님) → False (일부라도 유효하면 보존)
mixed_cell = MockCell([
    MockParagraph([
        MockRun("만족", strike=False),
        MockRun(" (이전)", strike=True),
    ])
])
assert _is_cell_strikethrough(mixed_cell) == False, "혼합 셀을 취소선으로 오인"
print("✅ Test 5: 혼합 셀 오인 없음 OK")

# ── Test 6: import 체인 확인 ──
from services.docx_parser import parse_docx, DocxTable
from services.docx_renderer import render_table
print("✅ Test 6: import 체인 OK")

print("\n🎉 ALL P1-T1 TESTS PASSED")
```

## 예상 소요 시간

약 30분 (구현 15분 + 테스트 15분)

## 다음 Task

이 Task 완료 후 → **TASK-P1T2** (표 타입 분류기 확장)로 진행.
