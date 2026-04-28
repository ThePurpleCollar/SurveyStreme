"""Evaluate Questionnaire Analyzer output against Ground Truth JSON.

Usage:
    python scripts/evaluate_extraction.py --ground-truth gt.json --extracted session.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from services.extraction_evaluator import evaluate_json_files


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Compare extracted SurveyDocument JSON with Ground Truth JSON."
    )
    parser.add_argument("--ground-truth", required=True,
                        help="Human-reviewed Ground Truth JSON path.")
    parser.add_argument("--extracted", required=True,
                        help="Questionnaire Analyzer session JSON path.")
    parser.add_argument("--out", help="Optional path to write the full JSON report.")
    parser.add_argument("--fail-under-question-recall", type=float,
                        help="Exit with code 1 if question recall is below this threshold.")
    parser.add_argument("--fail-under-option-recall", type=float,
                        help="Exit with code 1 if option code-label recall is below this threshold.")
    parser.add_argument("--fail-under-type-accuracy", type=float,
                        help="Exit with code 1 if type accuracy is below this threshold.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    report = evaluate_json_files(args.ground_truth, args.extracted)

    metrics = report["metrics"]
    counts = report["counts"]
    print("Extraction Evaluation")
    print(f"  Questions: matched {counts['matched_questions']}/"
          f"{counts['expected_questions']} expected, "
          f"{counts['extra_questions']} extra")
    print(f"  Question recall: {metrics['question_recall']:.2%}")
    print(f"  Question precision: {metrics['question_precision']:.2%}")
    print(f"  Type accuracy: {metrics['type_accuracy']:.2%}")
    print(f"  Option exact by question: {metrics['option_question_exact']:.2%}")
    print(f"  Option code-label recall: {metrics['option_code_label_recall']:.2%}")
    print(f"  Skip recall: {metrics['skip_recall']:.2%}")
    print(f"  Filter accuracy: {metrics['filter_accuracy']:.2%}")

    if args.out:
        Path(args.out).write_text(
            json.dumps(report, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(f"  Report written: {args.out}")

    failed = False
    checks = [
        ("question_recall", args.fail_under_question_recall),
        ("option_code_label_recall", args.fail_under_option_recall),
        ("type_accuracy", args.fail_under_type_accuracy),
    ]
    for metric_name, threshold in checks:
        if threshold is not None and metrics[metric_name] < threshold:
            print(f"  FAIL: {metric_name} {metrics[metric_name]:.2%} < {threshold:.2%}")
            failed = True

    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
