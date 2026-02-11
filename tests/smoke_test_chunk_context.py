# tests/smoke_test_chunk_context.py
"""청크 간 컨텍스트 전달 검증"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.llm_extractor import _build_chunk_context, _build_prompt

# ── _build_chunk_context: 단일 청크 → 빈 컨텍스트 ──
ctx = _build_chunk_context(0, 1, [[]], ["chunk0 text"])
assert ctx == "", f"Single chunk should have empty context, got: {ctx!r}"
print("Single chunk context: PASS")


# ── _build_chunk_context: 멀티 청크 — 다른 청크의 문항번호 포함 ──
pre_all = [
    [{"question_number": "Q1", "question_text": "Age?", "question_type": "SA"},
     {"question_number": "Q2", "question_text": "Gender?", "question_type": "SA"}],
    [{"question_number": "Q3", "question_text": "Income?", "question_type": "SA"},
     {"question_number": "Q4", "question_text": "Education?", "question_type": "SA"}],
    [{"question_number": "Q5", "question_text": "Satisfaction?", "question_type": "SCALE"}],
]
chunks_text = [
    "Chunk 0 content with Q1 and Q2",
    "Chunk 1 content with Q3 and Q4",
    "Chunk 2 content with Q5",
]

# 첫 번째 청크 (index=0): Q3,Q4,Q5가 other sections로 나와야 함
ctx0 = _build_chunk_context(0, 3, pre_all, chunks_text)
assert "Q3, Q4" in ctx0, f"Chunk 0 should reference Q3, Q4: {ctx0}"
assert "Q5" in ctx0, f"Chunk 0 should reference Q5: {ctx0}"
assert "Q1" not in ctx0, f"Chunk 0 should NOT reference own Q1: {ctx0}"
assert "previous" not in ctx0.split("KNOWN")[1].split("Section 1")[0] if "Section 1" in ctx0 else True
# 첫 번째 청크는 이전 청크가 없으므로 END OF PREVIOUS SECTION 없음
assert "END OF PREVIOUS SECTION" not in ctx0, f"Chunk 0 has no previous section: {ctx0}"
print("Multi-chunk context (chunk 0): PASS")

# 두 번째 청크 (index=1): Q1,Q2(이전)와 Q5(이후) 표시, 이전 청크 말미 포함
ctx1 = _build_chunk_context(1, 3, pre_all, chunks_text)
assert "Q1, Q2" in ctx1, f"Chunk 1 should reference Q1, Q2: {ctx1}"
assert "Q5" in ctx1, f"Chunk 1 should reference Q5: {ctx1}"
assert "previous" in ctx1, f"Chunk 1 should label section 1 as previous: {ctx1}"
assert "later" in ctx1, f"Chunk 1 should label section 3 as later: {ctx1}"
assert "END OF PREVIOUS SECTION" in ctx1, f"Chunk 1 should have prev section tail: {ctx1}"
assert "Chunk 0 content" in ctx1, f"Chunk 1 should include prev chunk text: {ctx1}"
print("Multi-chunk context (chunk 1): PASS")

# 세 번째 청크 (index=2): Q1,Q2,Q3,Q4 표시
ctx2 = _build_chunk_context(2, 3, pre_all, chunks_text)
assert "Q1, Q2" in ctx2
assert "Q3, Q4" in ctx2
assert "Q5" not in ctx2, f"Chunk 2 should NOT reference own Q5"
assert "END OF PREVIOUS SECTION" in ctx2
print("Multi-chunk context (chunk 2): PASS")


# ── _build_chunk_context: 이전 청크 말미 500자 제한 ──
long_prev = "A" * 300 + "\n" + "B" * 300 + "\n" + "C" * 300
pre_2 = [
    [{"question_number": "Q1", "question_text": "x", "question_type": "SA"}],
    [],
]
ctx_long = _build_chunk_context(1, 2, pre_2, [long_prev, "chunk1"])
# 500자 잘림 + 첫 불완전 줄 제거
assert len(ctx_long) < len(long_prev), "Should truncate long previous chunk"
print("Long previous chunk truncation: PASS")


# ── _build_prompt: 컨텍스트 미전달 → 기존 동작 ──
prompt_no_ctx = _build_prompt("Q1. Age?", 0, 1)
assert "DOCUMENT CONTEXT" not in prompt_no_ctx
assert "Q1. Age?" in prompt_no_ctx
print("Prompt without context: PASS")

# ── _build_prompt: 컨텍스트 전달 → CONTEXT 블록 포함 ──
prompt_with_ctx = _build_prompt("Q3. Income?", 1, 3, chunk_context="Section 1: Q1, Q2")
assert "DOCUMENT CONTEXT" in prompt_with_ctx
assert "Section 1: Q1, Q2" in prompt_with_ctx
assert "Q3. Income?" in prompt_with_ctx
assert "avoid duplicating" in prompt_with_ctx
print("Prompt with context: PASS")

# ── _build_prompt: Section info ──
prompt_multi = _build_prompt("text", 2, 5)
assert "[Section 3 of 5]" in prompt_multi
prompt_single = _build_prompt("text", 0, 1)
assert "[Section" not in prompt_single
print("Section info: PASS")

# ── 빈 pre-extracted (모든 청크에 문항 없음) ──
ctx_empty = _build_chunk_context(0, 2, [[], []], ["a", "b"])
# 다른 청크에 문항이 없으면 KNOWN QUESTIONS 없음, 하지만 첫 청크이므로 END OF PREVIOUS도 없음
assert "KNOWN QUESTIONS" not in ctx_empty
print("Empty pre-extracted: PASS")

ctx_empty1 = _build_chunk_context(1, 2, [[], []], ["prev text", "cur"])
# 다른 청크에 문항이 없지만 이전 텍스트는 있음
assert "END OF PREVIOUS SECTION" in ctx_empty1
print("Empty pre-extracted with prev text: PASS")


print("\nAll chunk context smoke tests passed!")
