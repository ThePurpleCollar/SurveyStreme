"""Create a human-reviewable Ground Truth JSON from a session JSON.

This script does not claim the session is correct. It stamps metadata and marks
questions as review-ready so a human can verify and commit the result.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from models.survey import SurveyDocument


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Promote a reviewed session JSON to a Ground Truth candidate."
    )
    parser.add_argument("--session", required=True,
                        help="Questionnaire Analyzer session JSON path.")
    parser.add_argument("--out", required=True,
                        help="Output Ground Truth JSON path.")
    parser.add_argument("--reviewer", default="",
                        help="Optional reviewer name or initials.")
    parser.add_argument("--mark-status", default="verified",
                        choices=["needs_review", "verified", "rejected"],
                        help="Review status to apply to every question.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    session_path = Path(args.session)
    out_path = Path(args.out)

    data = json.loads(session_path.read_text(encoding="utf-8"))
    doc = SurveyDocument.from_json_dict(data)

    for q in doc.questions:
        q.review_status = args.mark_status
        if args.reviewer and not q.review_notes:
            q.review_notes = f"Reviewed by {args.reviewer}"

    payload = doc.to_json_dict()
    payload["ground_truth_metadata"] = {
        "source_session": str(session_path),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "reviewer": args.reviewer,
        "status": "candidate_requires_human_review",
    }

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"Ground Truth candidate written: {out_path}")
    print("Review this file manually before using it as an authoritative baseline.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
