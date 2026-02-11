# tests/smoke_test_qn_filter.py
"""비문항 필터링 화이트/블랙리스트 검증"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.llm_extractor import _is_valid_question_number as valid

# ── 화이트리스트: 알려진 유효 접두어 → 항상 True ──
# Standard
assert valid("Q1") is True
assert valid("SQ1a") is True
assert valid("SC2") is True
assert valid("S1") is True

# Section-based
assert valid("A1") is True
assert valid("B2") is True
assert valid("C3") is True
assert valid("D4") is True
assert valid("F1") is True

# Product, Tracking
assert valid("P1") is True
assert valid("T1") is True

# Question groups
assert valid("QA1") is True
assert valid("QB2") is True
assert valid("QC3") is True
assert valid("QD4") is True

# Brand value tracking (would fail >5 char check without whitelist for BVT)
assert valid("BV1") is True
assert valid("BVT11") is True

# Demographics
assert valid("DM1") is True
assert valid("DEM01") is True

# Product prefix
assert valid("PR1") is True

# Case insensitive whitelist
assert valid("q1") is True
assert valid("sq1") is True
assert valid("sc2") is True
assert valid("bvt11") is True
assert valid("dem01") is True

print("Whitelist tests passed!")


# ── 블랙리스트: 비문항 접두어 → 항상 False ──
# Process/routing
assert valid("STEP1") is False
assert valid("PAGE2") is False
assert valid("GOTO3") is False
assert valid("SKIP1") is False
assert valid("LOOP1") is False

# Structural
assert valid("PART1") is False
assert valid("BLOCK1") is False
assert valid("MODULE1") is False

# Metadata
assert valid("NOTE3") is False
assert valid("ITEM5") is False
assert valid("INFO1") is False
assert valid("TEXT1") is False
assert valid("MSG1") is False

# Survey flow
assert valid("INTRO1") is False
assert valid("END1") is False
assert valid("CLOSE1") is False
assert valid("THANK1") is False

# Display/programming
assert valid("DISPLAY1") is False
assert valid("SHOW1") is False
assert valid("HIDE1") is False

# Sampling/quota
assert valid("QUOTA1") is False
assert valid("SAMPLE1") is False
assert valid("CELL1") is False

# Case insensitive blacklist
assert valid("step1") is False
assert valid("Step1") is False
assert valid("page2") is False
assert valid("Page2") is False
assert valid("note3") is False
assert valid("Note3") is False
assert valid("intro1") is False
assert valid("display1") is False
assert valid("quota1") is False

# SECTION (7 chars, also >5 heuristic would catch it)
assert valid("SECTION1") is False

print("Blacklist tests passed!")


# ── 휴리스틱: 알 수 없는 접두어 ──
# Long prefix (>5 chars) → rejected
assert valid("RegionCode2") is False
assert valid("SegCode15") is False
assert valid("CategoryCode1") is False
assert valid("BrandCode1") is False

# camelCase → rejected
assert valid("RegCode2") is False  # camelCase + would be caught by >5 too
assert valid("myVar1") is False    # camelCase

# Short unknown prefix → accepted (benefit of the doubt)
assert valid("X1") is True
assert valid("R1") is True
assert valid("NEW1") is True
assert valid("NET1") is True
assert valid("BASE1") is True  # 4 chars, no camelCase, not blacklisted

# Edge cases
assert valid("") is False          # empty
assert valid("123") is False       # no alpha prefix
assert valid("Q") is True          # valid prefix (full format validation is done by regex patterns)

print("Heuristic tests passed!")


# ── PDF regex와의 통합 확인 ──
from services.postprocessor import _match_question_line

# Whitelist prefixes work through PDF regex
assert _match_question_line("BVT11. Brand value tracking question") is not None
assert _match_question_line("DEM01. What is your age?") is not None

# Blacklist prefixes are rejected by PDF regex
assert _match_question_line("STEP1. Do this step") is None
assert _match_question_line("INTRO1. Welcome text") is None
assert _match_question_line("DISPLAY1. Show image") is None
assert _match_question_line("QUOTA1. Check quota") is None

# Case insensitive through PDF regex
assert _match_question_line("step1. something") is None
assert _match_question_line("note2. something") is None

print("PDF regex integration tests passed!")
print("All QN filter smoke tests passed!")
