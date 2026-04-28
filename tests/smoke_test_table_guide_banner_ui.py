"""Smoke tests for Table Guide banner generation entry points."""

from pathlib import Path


SOURCE = Path("pages/table_guide.py").read_text(encoding="utf-8")


def _slice_between(start: str, end: str) -> str:
    start_idx = SOURCE.index(start)
    end_idx = SOURCE.index(end, start_idx)
    return SOURCE[start_idx:end_idx]


def test_selected_generation_calls_banner_runner():
    section = _slice_between("if generate_clicked:", "# ── 진행률 요약 ──")
    assert "if gen_banners:" in section
    assert "_run_banner_generation_only(df, language)" in section
    assert "_tab_banner_setup(df, language)" not in section


def test_banner_tab_has_direct_generation_button():
    section = _slice_between("def _tab_banner_setup", "# 카테고리별 그룹핑")
    assert '"배너 생성/재생성"' in section
    assert "_run_banner_generation_only(df, language)" in section
    assert "generate_banners_from_tab" in section


if __name__ == "__main__":
    test_selected_generation_calls_banner_runner()
    test_banner_tab_has_direct_generation_button()
    print("ALL TABLE GUIDE BANNER UI TESTS PASSED")
