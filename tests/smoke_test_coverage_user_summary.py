import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.coverage_checker import CoverageItem, CoverageReport
from services.coverage_user_summary import summarize_coverage_for_user


report = CoverageReport(
    detected_questions=78,
    extracted_questions=55,
    tables_total=64,
    tables_with_options=41,
    generic_tables=29,
    unknown_tables=1,
    options_matched=51,
    skip_patterns_found=7,
    skip_extracted=10,
    filter_patterns_found=225,
    filter_extracted=52,
    instruction_patterns_found=4,
    instruction_extracted=54,
    items=[
        CoverageItem(
            category="question",
            question_number="43",
            description="문항 43이 문서에서 감지되었으나 추출되지 않았습니다.",
            evidence="43 inches or smaller | 1 48/49 inches | 2 50 inches | 3",
        ),
        CoverageItem(
            category="question",
            question_number="U1-1",
            description="문항 U1-1이 문서에서 감지되었으나 추출되지 않았습니다.",
            evidence="[PN: ANSWER GRID] U1-1 | U1-2 Weekdays | Weekends",
        ),
        CoverageItem(
            category="question",
            question_number="Product1",
            description="문항 Product1이 문서에서 감지되었으나 추출되지 않았습니다.",
            evidence="Product1 | Product2 | Product3 | Purchase Choice Card 1",
        ),
        CoverageItem(
            category="table_drilldown",
            question_number="",
            description="표 25 (2x10)가 generic로 분류되었습니다.",
            severity="info",
            evidence="NOT proud to own AT ALL | STRONGLY proud to own / 1 | 2 | 3 | 4",
        ),
        CoverageItem(
            category="table_drilldown",
            question_number="",
            description="표 1 (4x2)가 generic로 분류되었습니다.",
            severity="info",
            evidence="Methodology | Online / Sample Size | n=500",
        ),
        CoverageItem(
            category="table_classification",
            question_number="",
            description="역할 미확정 표(generic)가 29개 남아 있습니다.",
            severity="info",
            evidence="Table 1 4x2: Methodology",
        ),
    ],
)

summary = summarize_coverage_for_user(report)

assert summary.status_label == "확인 후 진행 권장"
assert summary.headline == "55개 문항을 추출했습니다."
assert not any("%" in metric.value for metric in summary.metrics)
assert not any("/" in metric.value for metric in summary.metrics)

key_titles = {item.title for item in summary.key_items}
reference_titles = {item.title for item in summary.reference_items}

assert "U1-1" in key_titles
assert "Product1" in key_titles
assert "표 25" in key_titles
assert "43 후보" in reference_titles
assert "표 1" in reference_titles

print("ALL COVERAGE USER SUMMARY TESTS PASSED")
