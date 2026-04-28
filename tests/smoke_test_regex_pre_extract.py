import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.llm_extractor import regex_pre_extract


text = """
Q1. Which brands do you know?
PN: ASK IF Q1=1
144Hz gaming monitor
65 Very satisfied
마케팅 안내 문구
스크리닝 조건 설명
A Additional instruction
2. Please select your gender.
3. Male
B2 [SA] Which product do you use most often?
| 1 | Yes |
[TABLE type=code_label rows=2 cols=2]
"""

items = regex_pre_extract(text)
qns = [item["question_number"] for item in items]

assert "Q1" in qns
assert "2" in qns
assert "B2" in qns
assert "PN" not in qns
assert "144Hz" not in qns
assert "65" not in qns
assert "마케팅" not in qns
assert "스크리닝" not in qns
assert "A" not in qns
assert "3" not in qns  # short option label, not a high-confidence question

print("ALL REGEX PRE-EXTRACT TESTS PASSED")
