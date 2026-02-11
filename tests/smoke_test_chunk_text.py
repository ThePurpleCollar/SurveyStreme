"""chunk_text() 단위 테스트 — PDF 텍스트 청킹 검증."""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.chunker import chunk_text, _is_text_question_start


def test_is_text_question_start():
    """문항 시작점 감지 테스트"""
    # 유효한 문항 시작점
    assert _is_text_question_start("Q1. What is your age?") is True
    assert _is_text_question_start("Q2 [S] How often do you...") is True
    assert _is_text_question_start("SQ1a. Please select...") is True
    assert _is_text_question_start("[SC2. SENSITIVE INDUSTRY (MA)]") is True
    assert _is_text_question_start("A1-1. First question") is True
    assert _is_text_question_start("BVT11 [S] Brand value") is True

    # 비문항 (거부해야 함)
    assert _is_text_question_start("") is False
    assert _is_text_question_start("This is just a paragraph.") is False
    assert _is_text_question_start("RegionCode1. something") is False
    assert _is_text_question_start("STEP1. Go to next page") is False
    assert _is_text_question_start("INTRO1. Welcome text") is False

    print("  [PASS] _is_text_question_start()")


def test_chunk_text_empty():
    """빈 입력 처리"""
    assert chunk_text([]) == []
    print("  [PASS] chunk_text([]) == []")


def test_chunk_text_single_chunk():
    """max_chars 이내이면 단일 청크 반환"""
    pages = ["Q1. What is your age?\n1. Under 18\n2. 18-25\n3. 26-35"]
    result = chunk_text(pages, max_chars=200000)
    assert len(result) == 1
    assert "Q1." in result[0]
    print("  [PASS] Single chunk for small input")


def test_chunk_text_split_at_question_boundary():
    """문항 경계에서 분할"""
    # 두 문항, 작은 max_chars로 강제 분할
    page1 = "Q1. What is your age?\n1. Under 18\n2. 18-25\n3. 26-35"
    page2 = "Q2. What is your gender?\n1. Male\n2. Female"
    pages = [page1, page2]

    # max_chars를 page1 길이보다 약간 크게 설정 → Q2에서 분할
    result = chunk_text(pages, max_chars=len(page1) + 5)
    assert len(result) == 2, f"Expected 2 chunks, got {len(result)}"
    assert "Q1." in result[0]
    assert "Q2." in result[1]
    print("  [PASS] Split at question boundary")


def test_chunk_text_no_split_within_question():
    """문항 경계가 아닌 곳에서는 분할하지 않음"""
    # 문항 시작 패턴이 없는 텍스트 → 단일 청크 (max_chars 초과하더라도)
    lines = [f"Line {i}: This is some survey content without question markers" for i in range(100)]
    pages = ["\n".join(lines)]
    result = chunk_text(pages, max_chars=100)
    # 문항 시작점이 없으므로 1개 청크
    assert len(result) == 1
    print("  [PASS] No split without question boundaries")


def test_chunk_text_multiple_pages():
    """여러 페이지 결합 후 청킹"""
    pages = [
        "Introduction\nWelcome to the survey.\n",
        "Q1. First question?\n1. Yes\n2. No\n",
        "Q2. Second question?\n1. A\n2. B\n",
        "Q3. Third question?\n1. X\n2. Y\n",
    ]
    # 전체를 하나로 결합 → 충분히 작으면 단일 청크
    result = chunk_text(pages, max_chars=200000)
    assert len(result) == 1
    assert "Q1." in result[0]
    assert "Q2." in result[0]
    assert "Q3." in result[0]
    print("  [PASS] Multiple pages merged into single chunk")


def test_chunk_text_large_document():
    """큰 문서 시뮬레이션"""
    questions = []
    for i in range(1, 51):
        q_text = f"Q{i}. This is question number {i} with some detail?\n"
        options = "\n".join([f"{j}. Option {j} for Q{i}" for j in range(1, 6)])
        questions.append(q_text + options)

    pages = ["\n\n".join(questions)]
    total_len = len(pages[0])

    # 절반 크기로 제한 → 2개 이상 청크
    result = chunk_text(pages, max_chars=total_len // 2)
    assert len(result) >= 2, f"Expected >=2 chunks, got {len(result)}"

    # 모든 문항이 포함되어야 함
    combined = "\n".join(result)
    for i in range(1, 51):
        assert f"Q{i}." in combined, f"Q{i} missing from chunks"
    print(f"  [PASS] Large document split into {len(result)} chunks")


if __name__ == "__main__":
    print("Running chunk_text() smoke tests...")
    test_is_text_question_start()
    test_chunk_text_empty()
    test_chunk_text_single_chunk()
    test_chunk_text_split_at_question_boundary()
    test_chunk_text_no_split_within_question()
    test_chunk_text_multiple_pages()
    test_chunk_text_large_document()
    print("\nAll chunk_text tests passed!")
