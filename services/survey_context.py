"""Survey Context & Enrichment Service.

- build_survey_context(): 설문 전체 맥락 텍스트 생성 (모든 LLM 프롬프트에 주입)
- enrich_document(): Intelligence 결과를 SurveyDocument + 개별 문항에 매핑
"""

from typing import List, Optional

from models.survey import SurveyDocument, SurveyQuestion


def build_survey_context(doc: SurveyDocument,
                         questions: Optional[List[SurveyQuestion]] = None,
                         df=None) -> str:
    """설문지 전체 맥락 요약 — 모든 LLM 프롬프트에 주입.

    Args:
        doc: SurveyDocument (client_brand, study_objective, survey_intelligence 등 포함).
        questions: 문항 리스트 오버라이드 (없으면 doc.questions 사용).
        df: DataFrame 폴백 (questions 없을 때).
    """
    lines = []
    client_brand = doc.client_brand
    study_objective = doc.study_objective
    intelligence = doc.survey_intelligence

    # ── 사용자 입력 (최우선 정보) ──
    if client_brand or study_objective:
        lines.append("## Study Brief")
        if client_brand:
            lines.append(f"Client Brand: {client_brand}")
        if study_objective:
            lines.append(f"Study Objective: {study_objective}")
        lines.append("")

    # ── Survey Intelligence 섹션 ──
    if intelligence and intelligence.get("study_type"):
        lines.append("## Survey Intelligence")
        client = intelligence.get("client_name", "") or client_brand
        study = intelligence.get("study_type", "")
        if client:
            lines.append(f"Client: {client}")
        lines.append(f"Study: {study}")

        objectives = intelligence.get("research_objectives", [])
        if objectives:
            lines.append("Objectives:")
            for i, obj in enumerate(objectives, 1):
                lines.append(f"  {i}. {obj}")

        framework = intelligence.get("analysis_framework", {})
        if framework:
            fw_parts = []
            for phase in ["screening", "demographics", "awareness",
                          "usage_experience", "evaluation", "intent_loyalty", "other"]:
                qns = framework.get(phase, [])
                if qns:
                    label = phase.replace("_", " ").title()
                    fw_parts.append(f"{','.join(qns)}({label})")
            if fw_parts:
                lines.append(f"Framework: {' -> '.join(fw_parts)}")

        segments = intelligence.get("key_segments", [])
        if segments:
            seg_strs = [f"{s.get('question', '?')}({s.get('name', '')}/{s.get('type', '')})"
                        for s in segments]
            lines.append(f"Key Segments: {', '.join(seg_strs)}")

        lines.append("")

    # ── Question Flow 섹션 ──
    lines.append("## Question Flow")

    qs = questions if questions is not None else doc.questions
    if qs:
        seen = set()
        unique_qs = []
        for q in qs:
            if q.question_number not in seen:
                seen.add(q.question_number)
                unique_qs.append(q)

        # 문항 유형 분포
        type_counts = {}
        for q in unique_qs:
            qtype = (q.question_type or "SA").strip()
            type_counts[qtype] = type_counts.get(qtype, 0) + 1
        type_str = ", ".join(
            f"{t} {c}" for t, c in sorted(type_counts.items(), key=lambda x: -x[1])
        )
        lines.append(f"Total: {len(unique_qs)} questions ({type_str})")
        lines.append("")

        # 전체 문항 흐름
        for q in unique_qs:
            text = (q.question_text or "").replace("\n", " ")[:60]
            qtype = q.question_type or ""
            opts = f", {len(q.answer_options)} opts" if q.answer_options else ""
            filt = f" [F: {(q.filter_condition or '')[:30]}]" if q.filter_condition else ""
            lines.append(f"  {q.question_number}. {text} ({qtype}{opts}){filt}")

    elif df is not None and not df.empty:
        # DataFrame 폴백
        groups = _group_rows_by_question_from_df(df)
        type_counts = {}
        for g in groups:
            qtype = g["qtype"] or "SA"
            type_counts[qtype] = type_counts.get(qtype, 0) + 1
        type_str = ", ".join(
            f"{t} {c}" for t, c in sorted(type_counts.items(), key=lambda x: -x[1])
        )
        lines.append(f"Total: {len(groups)} questions ({type_str})")
        lines.append("")
        for g in groups:
            text = (g["text"] or "").replace("\n", " ")[:60]
            lines.append(f"  {g['qn']}. {text} ({g['qtype']})")

    return "\n".join(lines)


def _group_rows_by_question_from_df(df) -> list:
    """DataFrame 행을 QuestionNumber 기준으로 그룹화 (context 생성용)."""
    groups = []
    seen = {}
    for _, row in df.iterrows():
        qn = str(row.get("QuestionNumber", "")).strip()
        if not qn:
            continue
        if qn not in seen:
            text = str(row.get("QuestionText", "")).strip()
            qtype = str(row.get("QuestionType", "")).strip()
            seen[qn] = len(groups)
            groups.append({"qn": qn, "text": text, "qtype": qtype})
    return groups


def enrich_document(doc: SurveyDocument, intelligence: dict) -> None:
    """Intelligence 결과를 SurveyDocument + 개별 문항에 매핑."""
    # Study-level
    doc.study_type = intelligence.get("study_type", "")
    doc.research_objectives = intelligence.get("research_objectives", [])
    doc.survey_intelligence = intelligence
    if not doc.client_brand:
        doc.client_brand = intelligence.get("client_name", "")

    # Question-level: role 매핑
    framework = intelligence.get("analysis_framework", {})
    qn_role_map = {}
    for role, qns in framework.items():
        if not isinstance(qns, list):
            continue
        for qn in qns:
            qn_role_map[qn.strip()] = role

    # Question-level: variable_type + analytical_value 매핑
    qn_segment_map = {}
    for seg in intelligence.get("key_segments", []):
        qn = seg.get("question", "").strip()
        if qn:
            qn_segment_map[qn] = seg.get("type", "")

    for q in doc.questions:
        qn = q.question_number
        if qn in qn_role_map:
            q.role = qn_role_map[qn]
        if qn in qn_segment_map:
            q.variable_type = qn_segment_map[qn]
            q.analytical_value = "high"
