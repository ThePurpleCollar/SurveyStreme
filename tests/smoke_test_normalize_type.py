# tests/smoke_test_normalize_type.py
"""question_type 정규화 매핑 전체 검증"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.llm_extractor import _normalize_question_type as norm

# ── 1. 상세 형식 보존 ──
assert norm("5pt x 3") == "5pt x 3"
assert norm("7pt x 8") == "7pt x 8"
assert norm("5PT X 3") == "5pt x 3"
assert norm("5pt") == "5pt"
assert norm("7PT") == "7pt"
assert norm("Top3") == "Top3"
assert norm("Top 5") == "Top5"
assert norm("Rank3") == "Top3"
assert norm("Rank 5") == "Top5"
assert norm("3순위") == "Top3"
assert norm("5 순위") == "Top5"

# ── 2. 표준 유형 정확 매칭 ──
for t in ['SA', 'MA', 'OE', 'NUMERIC', 'SCALE', 'RANK', 'GRID', 'MATRIX']:
    assert norm(t) == t, f"{t} should stay {t}"
    assert norm(t.lower()) == t, f"{t.lower()} should become {t}"

# ── 3. 단일 문자 약어 ──
assert norm("S") == "SA"
assert norm("M") == "MA"
assert norm("O") == "OE"
assert norm("s") == "SA"
assert norm("m") == "MA"
assert norm("o") == "OE"

# ── 4. 변형 패턴 ──
# N-point scale variations
assert norm("5-point scale x 3") == "5pt x 3"
assert norm("5-point scale") == "5pt"
assert norm("5-point") == "5pt"
assert norm("7 point scale") == "7pt"
assert norm("5점 척도 x 3") == "5pt x 3"
assert norm("5점척도") == "5pt"
assert norm("5점") == "5pt"

# Npt scale suffix
assert norm("5pt scale") == "5pt"
assert norm("5-pt scale") == "5pt"
assert norm("7pt scale") == "7pt"

# Range notation
assert norm("1-5") == "5pt"
assert norm("1-7") == "7pt"
assert norm("0-10") == "11pt"
assert norm("scale 1-5") == "5pt"
assert norm("1-5 scale") == "5pt"
assert norm("1 to 5") == "5pt"
assert norm("0 to 10") == "11pt"
assert norm("1~7") == "7pt"

# Likert
assert norm("Likert 5") == "5pt"
assert norm("Likert-7") == "7pt"
assert norm("likert:5") == "5pt"

# NPS
assert norm("NPS") == "11pt"
assert norm("nps") == "11pt"
assert norm("Net Promoter Score") == "11pt"
assert norm("net promoter") == "11pt"

# ── 5. 동의어 매핑 ──
# SA
assert norm("단수") == "SA"
assert norm("single") == "SA"
assert norm("select one") == "SA"
assert norm("single choice") == "SA"
assert norm("Single Select") == "SA"
assert norm("one answer") == "SA"
assert norm("binary") == "SA"
assert norm("yes/no") == "SA"
assert norm("dichotomous") == "SA"
assert norm("boolean") == "SA"
assert norm("dropdown") == "SA"
assert norm("drop-down") == "SA"
assert norm("pull-down") == "SA"
assert norm("객관식") == "SA"

# MA
assert norm("복수") == "MA"
assert norm("multiple") == "MA"
assert norm("select all") == "MA"
assert norm("multiple choice") == "MA"
assert norm("multi-select") == "MA"
assert norm("multi response") == "MA"
assert norm("choose all") == "MA"
assert norm("check all") == "MA"

# OE
assert norm("주관") == "OE"
assert norm("open") == "OE"
assert norm("OPEN") == "OE"
assert norm("open/sa") == "OE"
assert norm("free text") == "OE"
assert norm("freetext") == "OE"
assert norm("verbatim") == "OE"
assert norm("open-ended") == "OE"
assert norm("open ended") == "OE"
assert norm("text entry") == "OE"
assert norm("text input") == "OE"
assert norm("essay") == "OE"
assert norm("서술형") == "OE"
assert norm("기술형") == "OE"

# NUMERIC
assert norm("numeric") == "NUMERIC"
assert norm("숫자") == "NUMERIC"
assert norm("constant sum") == "NUMERIC"
assert norm("allocation") == "NUMERIC"
assert norm("배분") == "NUMERIC"

# SCALE
assert norm("rating") == "SCALE"
assert norm("likert") == "SCALE"
assert norm("척도") == "SCALE"
assert norm("slider") == "SCALE"
assert norm("sliding scale") == "SCALE"

# RANK
assert norm("순위") == "RANK"
assert norm("ranking") == "RANK"
assert norm("rank order") == "RANK"

# GRID / MATRIX
assert norm("grid") == "GRID"
assert norm("matrix") == "MATRIX"

# ── Edge cases ──
assert norm(None) is None
assert norm("") is None
assert norm("  ") is None
assert norm("Unknown Custom Type") == "Unknown Custom Type"  # 원본 유지

print("All normalization smoke tests passed!")
