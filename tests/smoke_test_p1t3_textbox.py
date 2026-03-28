import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.docx_parser import _extract_textbox_text

# Test 1: 함수 존재 확인
assert callable(_extract_textbox_text)
print("Test 1: _extract_textbox_text 존재 OK")

# Test 2: 텍스트 박스 없는 단락 -> 빈 문자열
class MockElement:
    def findall(self, path):
        return []

class MockParagraph:
    _element = MockElement()

result = _extract_textbox_text(MockParagraph())
assert result == "", f"텍스트 박스 없는 경우 빈 문자열이어야 함: {result}"
print("Test 2: 텍스트 박스 없는 경우 OK")

# Test 3: import 체인
from services.docx_parser import parse_docx, DocxParagraph
from services.docx_renderer import render_paragraph
print("Test 3: import 체인 OK")

# Test 4: WPS_NS 상수 존재
from services.docx_parser import WPS_NS
assert 'wordprocessingShape' in WPS_NS
print("Test 4: WPS_NS 상수 OK")

print("\nALL P1T3-TEXTBOX TESTS PASSED")
