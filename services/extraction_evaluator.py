"""Ground Truth 기반 설문지 추출 품질 평가.

Questionnaire Analyzer가 만든 session JSON과 사람이 검수한 Ground Truth JSON을
비교하여 문항/유형/보기/스킵/필터 품질 지표를 계산한다.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Iterable

from models.survey import AnswerOption, SkipLogic, SurveyDocument, SurveyQuestion


def _norm_text(value: str | None) -> str:
    """Normalize text for stable comparison."""
    if value is None:
        return ""
    text = str(value).strip().lower()
    text = re.sub(r"\s+", " ", text)
    return text


def _norm_qn(value: str | None) -> str:
    return _norm_text(value).replace(" ", "")


def _option_set(options: Iterable[AnswerOption]) -> set[tuple[str, str]]:
    return {
        (_norm_text(opt.code), _norm_text(opt.label))
        for opt in options
        if _norm_text(opt.code) or _norm_text(opt.label)
    }


def _skip_set(skip_logic: Iterable[SkipLogic]) -> set[tuple[str, str]]:
    return {
        (_norm_text(item.condition), _norm_text(item.target))
        for item in skip_logic
        if _norm_text(item.condition) or _norm_text(item.target)
    }


def _question_map(doc: SurveyDocument) -> dict[str, SurveyQuestion]:
    """Map normalized question number to SurveyQuestion.

    If duplicate question numbers exist, the first instance is kept because the
    extraction pipeline should already assign unique table_number suffixes.
    """
    result = {}
    for q in doc.questions:
        key = _norm_qn(q.question_number)
        if key and key not in result:
            result[key] = q
    return result


def load_survey_document_json(path: str | Path) -> SurveyDocument:
    """Load either a SurveyDocument session JSON or a minimal questions JSON."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if isinstance(data, list):
        data = {"filename": Path(path).name, "questions": data}
    if not isinstance(data, dict):
        raise ValueError("Ground truth/extracted JSON must be an object or question list")
    return SurveyDocument.from_json_dict(data)


def evaluate_documents(expected: SurveyDocument, actual: SurveyDocument) -> dict:
    """Compare expected vs actual extraction results.

    Returns a JSON-serializable report with aggregate metrics and actionable
    mismatch lists.
    """
    expected_map = _question_map(expected)
    actual_map = _question_map(actual)

    expected_keys = set(expected_map)
    actual_keys = set(actual_map)
    matched_keys = sorted(expected_keys & actual_keys)
    missing_keys = sorted(expected_keys - actual_keys)
    extra_keys = sorted(actual_keys - expected_keys)

    type_checked = 0
    type_matches = 0
    type_mismatches = []

    option_expected_questions = 0
    option_exact_questions = 0
    option_tp = option_fp = option_fn = 0
    option_mismatches = []

    skip_expected_questions = 0
    skip_exact_questions = 0
    skip_tp = skip_fp = skip_fn = 0
    skip_mismatches = []

    filter_checked = 0
    filter_matches = 0
    filter_mismatches = []

    for key in matched_keys:
        exp = expected_map[key]
        act = actual_map[key]

        exp_type = _norm_text(exp.question_type)
        if exp_type:
            type_checked += 1
            act_type = _norm_text(act.question_type)
            if exp_type == act_type:
                type_matches += 1
            else:
                type_mismatches.append({
                    "question_number": exp.question_number,
                    "expected": exp.question_type or "",
                    "actual": act.question_type or "",
                })

        exp_options = _option_set(exp.answer_options)
        act_options = _option_set(act.answer_options)
        if exp_options:
            option_expected_questions += 1
            if exp_options == act_options:
                option_exact_questions += 1
            else:
                option_mismatches.append({
                    "question_number": exp.question_number,
                    "missing": sorted(exp_options - act_options),
                    "extra": sorted(act_options - exp_options),
                })
        option_tp += len(exp_options & act_options)
        option_fn += len(exp_options - act_options)
        option_fp += len(act_options - exp_options)

        exp_skip = _skip_set(exp.skip_logic)
        act_skip = _skip_set(act.skip_logic)
        if exp_skip:
            skip_expected_questions += 1
            if exp_skip == act_skip:
                skip_exact_questions += 1
            else:
                skip_mismatches.append({
                    "question_number": exp.question_number,
                    "missing": sorted(exp_skip - act_skip),
                    "extra": sorted(act_skip - exp_skip),
                })
        skip_tp += len(exp_skip & act_skip)
        skip_fn += len(exp_skip - act_skip)
        skip_fp += len(act_skip - exp_skip)

        exp_filter = _norm_text(exp.filter_condition)
        if exp_filter:
            filter_checked += 1
            act_filter = _norm_text(act.filter_condition)
            if exp_filter == act_filter:
                filter_matches += 1
            else:
                filter_mismatches.append({
                    "question_number": exp.question_number,
                    "expected": exp.filter_condition or "",
                    "actual": act.filter_condition or "",
                })

    def _safe_ratio(num: int, den: int) -> float:
        return round(num / den, 4) if den else 1.0

    return {
        "files": {
            "expected": expected.filename,
            "actual": actual.filename,
        },
        "counts": {
            "expected_questions": len(expected_keys),
            "actual_questions": len(actual_keys),
            "matched_questions": len(matched_keys),
            "missing_questions": len(missing_keys),
            "extra_questions": len(extra_keys),
        },
        "metrics": {
            "question_recall": _safe_ratio(len(matched_keys), len(expected_keys)),
            "question_precision": _safe_ratio(len(matched_keys), len(actual_keys)),
            "type_accuracy": _safe_ratio(type_matches, type_checked),
            "option_question_exact": _safe_ratio(option_exact_questions, option_expected_questions),
            "option_code_label_recall": _safe_ratio(option_tp, option_tp + option_fn),
            "option_code_label_precision": _safe_ratio(option_tp, option_tp + option_fp),
            "skip_question_exact": _safe_ratio(skip_exact_questions, skip_expected_questions),
            "skip_recall": _safe_ratio(skip_tp, skip_tp + skip_fn),
            "skip_precision": _safe_ratio(skip_tp, skip_tp + skip_fp),
            "filter_accuracy": _safe_ratio(filter_matches, filter_checked),
        },
        "missing_questions": [
            expected_map[k].question_number for k in missing_keys
        ],
        "extra_questions": [
            actual_map[k].question_number for k in extra_keys
        ],
        "type_mismatches": type_mismatches,
        "option_mismatches": option_mismatches,
        "skip_mismatches": skip_mismatches,
        "filter_mismatches": filter_mismatches,
    }


def evaluate_json_files(ground_truth_path: str | Path,
                        extracted_path: str | Path) -> dict:
    expected = load_survey_document_json(ground_truth_path)
    actual = load_survey_document_json(extracted_path)
    return evaluate_documents(expected, actual)
