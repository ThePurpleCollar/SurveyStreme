import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.docx_parser import _is_cell_strikethrough

# Test 1: 함수 존재 확인
assert callable(_is_cell_strikethrough), "_is_cell_strikethrough 함수가 없습니다"
print("Test 1: _is_cell_strikethrough 함수 존재 OK")

# Mock classes
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

# Test 2: 취소선 셀 감지
strike_cell = MockCell([
    MockParagraph([MockRun("보통", strike=True)])
])
assert _is_cell_strikethrough(strike_cell) == True, "취소선 셀 감지 실패"
print("Test 2: 취소선 셀 감지 OK")

# Test 3: 일반 셀
normal_cell = MockCell([
    MockParagraph([MockRun("만족", strike=False)])
])
assert _is_cell_strikethrough(normal_cell) == False, "일반 셀 오탐"
print("Test 3: 일반 셀 오탐 없음 OK")

# Test 4: 빈 셀
empty_cell = MockCell([
    MockParagraph([MockRun("", strike=True)])
])
assert _is_cell_strikethrough(empty_cell) == False, "빈 셀을 취소선으로 오인"
print("Test 4: 빈 셀 오인 없음 OK")

# Test 5: 혼합 셀 (일부 취소선, 일부 아님)
mixed_cell = MockCell([
    MockParagraph([
        MockRun("만족", strike=False),
        MockRun(" (이전)", strike=True),
    ])
])
assert _is_cell_strikethrough(mixed_cell) == False, "혼합 셀을 취소선으로 오인"
print("Test 5: 혼합 셀 오인 없음 OK")

# Test 6: import 체인
from services.docx_parser import parse_docx, DocxTable
from services.docx_renderer import render_table
print("Test 6: import 체인 OK")

print("\nALL P1-T1 STRIKETHROUGH TESTS PASSED")
