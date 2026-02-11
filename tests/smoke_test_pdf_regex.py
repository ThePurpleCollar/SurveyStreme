# tests/smoke_test_pdf_regex.py
"""PDF 문항번호 정규식 패턴 강화 검증"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.postprocessor import _match_question_line, extract_question_data

# ── _match_question_line 단위 테스트 ──

# Pattern A: 표준 구분자 (dot, paren, colon)
assert _match_question_line("Q1. What is your gender?") == ("Q1", "What is your gender?")
assert _match_question_line("SQ1a. Brand awareness") == ("SQ1a", "Brand awareness")
assert _match_question_line("Q2) How old are you?") == ("Q2", "How old are you?")
assert _match_question_line("Q3: What brand do you prefer?") == ("Q3", "What brand do you prefer?")

# Underscore sub-questions
assert _match_question_line("Q4_1. First mention") == ("Q4_1", "First mention")
assert _match_question_line("Q4_2. Second mention") == ("Q4_2", "Second mention")

# Dash sub-questions (이미 지원됨)
assert _match_question_line("Q5-1. Satisfaction rating") == ("Q5-1", "Satisfaction rating")

# Pattern B: 공백+대괄호 타입 힌트
result_b = _match_question_line("Q6 [S] What is your income?")
assert result_b is not None
assert result_b[0] == "Q6"
assert "[S]" in result_b[1]
assert "income" in result_b[1]

result_b2 = _match_question_line("QPID100 [S] Product identification")
assert result_b2 is not None
assert result_b2[0] == "QPID100"

# Pattern C: 대괄호 헤더
result_c = _match_question_line("[SC2. SENSITIVE INDUSTRY (MA)]")
assert result_c is not None
assert result_c[0] == "SC2"
assert "SENSITIVE INDUSTRY" in result_c[1]

# False positive 거부: STEP, PAGE, 긴 접두어, camelCase
assert _match_question_line("STEP1. Do this step") is None
assert _match_question_line("PAGE2. Next page") is None
assert _match_question_line("RegionCode2. Some text") is None
assert _match_question_line("NOTE3. Important note") is None

# 일반 텍스트 거부
assert _match_question_line("This is a regular sentence.") is None
assert _match_question_line("1. A numbered list item") is None
assert _match_question_line("") is None

print("_match_question_line: all tests passed!")


# ── extract_question_data 통합 테스트 ──

texts_standard = [
    "Q1. What is your gender? (SA)\nMale\nFemale\nQ2. How old are you?\n18-24\n25-34",
]
result = extract_question_data(texts_standard)
assert len(result) == 2
assert result[0][0] == "Q1"
assert result[0][2] == "SA"  # type extracted from (SA)
assert result[1][0] == "Q2"

# 다양한 구분자 혼합
texts_mixed = [
    "Q1. First question [SA]\nSome options\n"
    "Q2) Second question\nMore text\n"
    "Q3: Third question (MA)\nA\nB\nC",
]
result_mixed = extract_question_data(texts_mixed)
assert len(result_mixed) == 3
assert result_mixed[0][0] == "Q1"
assert result_mixed[1][0] == "Q2"
assert result_mixed[2][0] == "Q3"
assert result_mixed[2][2] == "MA"

# 밑줄 하위문항
texts_underscore = [
    "Q4_1. First sub-question\nOption A\nQ4_2. Second sub-question\nOption B",
]
result_us = extract_question_data(texts_underscore)
assert len(result_us) == 2
assert result_us[0][0] == "Q4_1"
assert result_us[1][0] == "Q4_2"

# 대괄호 헤더
texts_bracket = [
    "[SC1. SCREENER QUESTION (SA)]\nAre you eligible?\nYes\nNo\n"
    "Q1. Main question\nText here",
]
result_bracket = extract_question_data(texts_bracket)
assert len(result_bracket) == 2
assert result_bracket[0][0] == "SC1"
assert result_bracket[1][0] == "Q1"

# False positive 필터링
texts_fp = [
    "STEP1. Please read the following instructions\n"
    "NOTE2. This is important\n"
    "Q1. Actual question\nSome text\n"
    "Q2. Another question",
]
result_fp = extract_question_data(texts_fp)
assert len(result_fp) == 2
assert result_fp[0][0] == "Q1"
assert result_fp[1][0] == "Q2"

print("extract_question_data: all tests passed!")
print("All PDF regex smoke tests passed!")
