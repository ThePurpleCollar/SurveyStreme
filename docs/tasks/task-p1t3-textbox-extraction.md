# TASK-P1T3: 텍스트 박스(TextBox) 콘텐츠 추출

## Status: 🔴 Not Started

## 선행 조건

없음 — P1-T1, P1-T2와 독립적으로 병행 가능.

## 배경

Word의 텍스트 박스(`<w:txbxContent>`)는 `doc.element.body` 순회로 접근되지 않아
설문지의 지시사항, PN 노트, 필터 조건이 완전히 무시된다.

### 텍스트 박스 사용 케이스

| 케이스 | 예시 |
|--------|------|
| 섹션 안내 | "다음 질문은 제품 사용 경험에 관한 것입니다" |
| 인터뷰어 지시 | "SHOW CARD A" / "여기서부터 태블릿 제시" |
| 프로그래머 노트 | "[PN: ASK IF Q1=1]" |
| 보기 카드 참조 | "카드 A", "보기 1번" |

### Word XML 구조

```xml
<w:p>
  <w:r>
    <w:drawing>
      <wp:inline>
        <a:graphicData>
          <wps:wsp>
            <wps:txbx>
              <w:txbxContent>
                <w:p><w:r><w:t>SHOW CARD A</w:t></w:r></w:p>
              </w:txbxContent>
            </wps:txbx>
          </wps:wsp>
        </a:graphicData>
      </wp:inline>
    </w:drawing>
  </w:r>
</w:p>
```

## Goal

1. `_extract_textbox_text()` 함수 — 단락의 텍스트 박스 텍스트 추출
2. `_parse_paragraph()`에서 텍스트 박스 텍스트를 `[TEXTBOX]...[/TEXTBOX]` 마커로 추가
3. LLM이 텍스트 박스 내용을 `instructions`/`filter`로 인식할 수 있게 함

## Files to Modify

- `services/docx_parser.py` — 텍스트 박스 추출 로직 추가
- `tests/smoke_test_p1t3_textbox.py` (신규)

## Implementation Steps

### Step 1: XML 네임스페이스 상수 추가

```python
WPS_NS = 'http://schemas.microsoft.com/office/word/2010/wordprocessingShape'
```

### Step 2: _extract_textbox_text() 헬퍼

```python
def _extract_textbox_text(paragraph) -> str:
    """paragraph 내 텍스트 박스(wps:txbx)의 텍스트를 추출.
    
    Returns:
        추출된 텍스트 또는 빈 문자열 (텍스트 박스 없으면)
    """
    try:
        # Drawing 요소 탐색
        for drawing in paragraph._element.findall(
            f'.//{{{WORD_NS}}}drawing'
        ):
            # wps:txbxContent 탐색
            for txbx_content in drawing.findall(
                f'.//{{{WPS_NS}}}txbx/{{{WORD_NS}}}txbxContent'
            ):
                texts = []
                for p in txbx_content.findall(f'{{{WORD_NS}}}p'):
                    t = ''.join(
                        r.text or '' for r in p.findall(f'.//{{{WORD_NS}}}t')
                    ).strip()
                    if t:
                        texts.append(t)
                if texts:
                    return ' / '.join(texts)
    except Exception:
        pass
    return ''
```

### Step 3: _parse_paragraph()에 텍스트 박스 병합

`_parse_paragraph()` 함수 끝, `return DocxParagraph(...)` 바로 전에 추가:

```python
# 텍스트 박스 추출
textbox_text = _extract_textbox_text(paragraph)
if textbox_text:
    # 기존 텍스트에 [TEXTBOX] 마커로 추가
    # 또는 별도 DocxParagraph로 삽입 (현재는 인라인 추가 방식 채택)
    if text:
        text = f"{text} [TEXTBOX: {textbox_text}]"
    else:
        text = f"[TEXTBOX: {textbox_text}]"
```

## Do NOT Change

- `_parse_table()` (P1-T1에서 처리)
- `parse_docx()`의 섹션/표 처리 로직
- `docx_renderer.py` 전체

## Verification Checklist

- [ ] `python -m py_compile services/docx_parser.py` 성공
- [ ] `python -c "from services.docx_parser import _extract_textbox_text; print('OK')"` 성공
- [ ] `python -c "from app import *; print('import OK')"` 성공
- [ ] 텍스트 박스 없는 일반 단락은 영향받지 않음 확인
- [ ] Smoke Test 통과

## Smoke Test Script

```python
# tests/smoke_test_p1t3_textbox.py
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.docx_parser import _extract_textbox_text

# Test 1: 함수 존재 확인
assert callable(_extract_textbox_text)
print("✅ Test 1: _extract_textbox_text 존재 OK")

# Test 2: 텍스트 박스 없는 단락 → 빈 문자열
class MockParagraph:
    class _element:
        @staticmethod
        def findall(path): return []

result = _extract_textbox_text(MockParagraph())
assert result == "", f"텍스트 박스 없는 경우 빈 문자열이어야 함: {result}"
print("✅ Test 2: 텍스트 박스 없는 경우 OK")

# Test 3: import 체인
from services.docx_parser import parse_docx, DocxParagraph
from services.docx_renderer import render_paragraph
print("✅ Test 3: import 체인 OK")

print("\n🎉 ALL P1T3-TEXTBOX TESTS PASSED")
```

## 예상 소요 시간

약 2시간 (XML 구조 파악 0.5h + 구현 1h + 테스트 0.5h)
