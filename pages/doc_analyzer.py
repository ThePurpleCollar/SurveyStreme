import os
import time

import streamlit as st
from services.llm_client import MODEL_DOC_ANALYZER
from services.postprocessor import apply_postprocessing
from services.docx_parser import parse_docx
from services.docx_renderer import render_sections_to_annotated_text
from services.chunker import chunk_sections
from services.llm_extractor import extract_survey_questions
from services.coverage_checker import check_extraction_coverage
from models.survey import SurveyDocument, SurveyQuestion
from services.table_guide_service import analyze_survey_intelligence
from services.survey_context import enrich_document
from ui.tree_view import render_tree_view
from ui.spreadsheet import render_spreadsheet_view


def page_document_processing(uploaded_file, client):
    st.title('Questionnaire Analyzer')

    # 세션 로드 결과가 있으면 파일 업로드 없이도 즉시 표시
    if uploaded_file is None and 'survey_document' in st.session_state:
        doc = st.session_state['survey_document']
        st.success(f"세션 복원 완료: **{doc.filename}** — {len(doc.questions)}개 문항", icon="✅")
        st.caption("💡 저장된 세션 파일에서 불러왔습니다. 다른 도구로 바로 진행할 수 있습니다.")
        _render_intelligence_summary(doc)
        _display_docx_results(doc)
        return

    if uploaded_file is not None:
        st.success("업로드된 파일에서 문항 번호, 문항 텍스트, 문항 유형을 추출합니다.", icon="✅")
    else:
        st.info('사이드바에서 설문지 파일을 업로드해주세요.', icon="ℹ️")
        return

    if uploaded_file is not None:
        if uploaded_file.name.endswith('.docx'):
            _process_docx(uploaded_file, client)
        else:
            st.error("지원하지 않는 파일 형식입니다. .docx 파일을 업로드해주세요.")


def _process_docx(uploaded_file, client):
    """DOCX AI 추출 파이프라인"""

    # ── Study Brief (optional) ──
    with st.expander("Study Brief (선택사항 — 분석 품질 향상에 도움)", expanded=False):
        brief_col1, brief_col2 = st.columns(2)
        with brief_col1:
            client_brand = st.text_input(
                "Client Brand",
                value=st.session_state.get("study_client_brand", ""),
                placeholder="e.g. Hyundai, Samsung, LG",
                help="The brand commissioning the study.",
                key="study_client_brand_input",
            )
            st.session_state["study_client_brand"] = client_brand
        with brief_col2:
            study_objective = st.text_input(
                "Study Objective",
                value=st.session_state.get("study_objective", ""),
                placeholder="e.g. Brand health tracking, Customer satisfaction",
                help="Research purpose.",
                key="study_objective_input",
            )
            st.session_state["study_objective"] = study_objective

    # 추출 버튼
    extract_button = st.button('AI로 문항 추출 시작', key='extract_docx_button', use_container_width=True)

    # 이전 결과가 있으면 표시
    if 'survey_document' in st.session_state and not extract_button:
        _display_docx_results(st.session_state['survey_document'])
        return

    if not extract_button:
        st.info("'AI로 문항 추출 시작' 버튼을 눌러 설문지 분석을 시작하세요.", icon="🤖")
        return

    # ── 추출 파이프라인 시작 ──
    model = MODEL_DOC_ANALYZER

    with st.status("1/5단계: DOCX 구조 파싱 중...", expanded=True) as status:
        # Phase 1: DOCX 파싱
        status.write("DOCX 구조를 분석하고 있습니다 (스타일, 목록, 표)...")
        try:
            sections = parse_docx(uploaded_file)
        except Exception as e:
            status.update(label="DOCX 파싱 실패", state="error")
            st.error(f"DOCX 파싱 오류: {e}")
            return

        if not sections:
            status.update(label="DOCX에서 내용을 찾을 수 없습니다.", state="error")
            st.warning("DOCX 파일에서 내용을 추출할 수 없습니다.")
            return

        total_paragraphs = sum(len(s.paragraphs) for s in sections)
        total_tables = sum(len(s.tables) for s in sections)
        status.write(f"✅ 파싱 완료: {len(sections)}개 섹션, "
                     f"{total_paragraphs}개 단락, {total_tables}개 표")

        # Phase 1 cont: 어노테이션 텍스트 + 청킹
        chunks = chunk_sections(sections)
        status.write(f"✅ AI 처리를 위해 {len(chunks)}개 청크로 분할")

        # Phase 3 준비: LLM 추출 (적응형 재청킹 포함)
        # 동적 업데이트용 컨테이너
        progress_bar = status.progress(0.0)
        stats_line = status.empty()

        start_time = time.time()
        chunks_done = [0]  # mutable for closure
        total_questions_found = [0]  # 누적 문항 수

        def on_progress(event, data):
            elapsed = time.time() - start_time

            if event == "regex_done":
                status.update(label="2/5단계: 문항 패턴 스캔 중...")
                status.write(f"✅ 빠른 스캔으로 ~{data['total_hints']}개 문항 후보 발견")

            elif event == "rechunk":
                status.write(
                    f"ℹ️ 적응형 재분할: {data['original_chunks']} → "
                    f"{data['new_chunks']}개 청크 ({data['reason']})"
                )

            elif event == "chunk_start":
                total = data['total_chunks']
                status.update(
                    label=f"3/5단계: AI로 문항 추출 중... "
                          f"(청크 {chunks_done[0]}/{total} 완료)"
                )
                frac = max(chunks_done[0] / total, 0.0)
                progress_bar.progress(frac)

            elif event == "chunk_done":
                chunks_done[0] += 1
                extracted = data['questions_extracted']
                total_questions_found[0] += extracted
                done = chunks_done[0]
                total = data['total_chunks']
                progress_bar.progress(done / total)

                # 청크별 완료 로그
                e_m, e_s = divmod(int(elapsed), 60)
                status.write(
                    f"✅ 청크 {data['chunk_index'] + 1}/{total}: "
                    f"{extracted}개 문항 ({e_m}:{e_s:02d})"
                )

                status.update(
                    label=f"3/5단계: AI로 문항 추출 중... "
                          f"(청크 {done}/{total} 완료)"
                )

                remaining = (elapsed / done * (total - done)) if done > 0 else 0
                remain_m, remain_s = divmod(int(remaining), 60)
                stats_line.write(
                    f"📊 현재까지 **{total_questions_found[0]}**개 문항 발견 "
                    f"| ⏱ 경과: {e_m}:{e_s:02d} "
                    f"| 남은 시간: ~{remain_m}:{remain_s:02d}"
                )

            elif event == "chunk_error":
                status.write(
                    f"⚠️ 청크 {data['chunk_index'] + 1} 실패: {data['error']}"
                )

            elif event == "missed_questions":
                status.write(
                    f"⚠️ 패턴 스캔에서 감지되었으나 AI가 놓친 문항 {data['count']}건: "
                    f"{', '.join(data['question_numbers'][:10])}"
                    f"{'...' if data['count'] > 10 else ''}"
                )

            elif event == "merge_done":
                progress_bar.progress(1.0)
                missed = data.get('missed_count', 0)
                missed_note = f" (⚠️ {missed}건 누락 가능)" if missed else ""
                stats_line.write(
                    f"📊 총 **{data['total_questions']}**개 문항 추출 완료{missed_note}"
                )

        questions = extract_survey_questions(
            client=client,
            chunks=chunks,
            model=model,
            progress_callback=on_progress,
        )

        elapsed_total = time.time() - start_time
        em, es = divmod(int(elapsed_total), 60)
        status.update(
            label=f"4/5단계: 마무리 중 — {len(questions)}개 문항, {em}:{es:02d} 소요",
            state="running", expanded=True,
        )

    if not questions:
        st.warning("문항을 추출할 수 없습니다. 문서에 설문 문항이 포함되어 있는지 확인해주세요.")
        return

    # SurveyDocument 생성
    client_brand = st.session_state.get("study_client_brand", "")
    study_objective = st.session_state.get("study_objective", "")
    survey_doc = SurveyDocument(
        filename=uploaded_file.name,
        questions=questions,
        client_brand=client_brand,
        study_objective=study_objective,
    )

    # 후처리: SummaryType, TableNumber 계산
    apply_postprocessing(survey_doc)

    # ── Phase 5: Survey Enrichment ──
    with st.status("5/5단계: 설문 인텔리전스 분석 중...", expanded=True) as enrich_status:
        try:
            intelligence = analyze_survey_intelligence(
                questions, language="en",
                client_brand=client_brand,
                study_objective=study_objective,
            )
            enrich_document(survey_doc, intelligence)
            obj_count = len(intelligence.get("research_objectives", []))
            seg_count = len(intelligence.get("key_segments", []))
            enrich_status.write(
                f"Study: {intelligence.get('study_type', '')} | "
                f"{obj_count} objectives | {seg_count} key segments"
            )
            enrich_status.update(label="5/5단계: 인텔리전스 분석 완료!", state="complete")
        except Exception as e:
            enrich_status.update(label=f"5/5단계: 인텔리전스 분석 건너뜀 ({e})", state="error")

    # 세션 상태 저장
    st.session_state['survey_document'] = survey_doc
    st.session_state['edited_df'] = survey_doc.to_dataframe()

    st.success(f"**{len(questions)}**개 문항을 추출했습니다.", icon="✅")

    # Coverage Report — 원본과 추출 결과 비교
    coverage = check_extraction_coverage(sections, questions)
    _render_coverage_report(coverage)

    # Intelligence 요약 카드
    _render_intelligence_summary(survey_doc)

    # 세션 저장 유도 배너
    with st.container(border=True):
        save_col1, save_col2 = st.columns([3, 1])
        with save_col1:
            st.markdown(
                "💾 **세션을 저장**하면 다음에 이 단계를 건너뛸 수 있습니다.  \n"
                "저장된 `.json` 파일을 업로드하면 모든 결과를 즉시 복원합니다."
            )
        with save_col2:
            st.download_button(
                label="💾 세션 저장",
                data=survey_doc.to_json_bytes(),
                file_name=f"{os.path.splitext(uploaded_file.name)[0]}_session.json",
                mime='application/json',
                use_container_width=True,
                type="primary",
            )

    st.toast("추출이 완료되었습니다! 세션을 저장해두세요.", icon="💾")

    # 결과 표시
    _display_docx_results(survey_doc)


def _render_coverage_report(report):
    """Extraction Coverage Report UI 렌더링."""
    from services.coverage_checker import CoverageReport

    def _bar(label, extracted, total, emoji_ok="✅", emoji_warn="⚠️"):
        if total == 0:
            return f"{emoji_ok} **{label}**: 해당 없음"
        pct = extracted / total * 100
        emoji = emoji_ok if pct >= 80 else emoji_warn
        return f"{emoji} **{label}**: {extracted}/{total} ({pct:.0f}%)"

    lines = [
        _bar("문항", report.extracted_questions, report.detected_questions),
        _bar("보기", report.options_matched, report.tables_with_options),
        _bar("스킵 로직", report.skip_extracted, report.skip_patterns_found),
        _bar("필터", report.filter_extracted, report.filter_patterns_found),
        _bar("지시문", report.instruction_extracted, report.instruction_patterns_found),
    ]

    if report.has_issues:
        with st.expander(f"📊 추출 커버리지 — {len(report.items)}건 확인 필요", expanded=True):
            st.markdown("  \n".join(lines))
            st.markdown("---")
            st.markdown("**확인이 필요한 항목:**")
            for item in report.items:
                icon = "⚠️" if item.severity == "warning" else "ℹ️"
                st.markdown(f"- {icon} {item.description}")
    else:
        with st.expander("📊 추출 커버리지 — 누락 없음", expanded=False):
            st.markdown("  \n".join(lines))


def _render_intelligence_summary(doc: SurveyDocument):
    """Intelligence 결과 요약 카드 + Re-analyze 버튼."""
    intel = doc.survey_intelligence
    if not intel or not intel.get("study_type"):
        return

    client = intel.get("client_name", "") or doc.client_brand
    study = intel.get("study_type", "")
    header = f"{client} — {study}" if client else study
    objectives = intel.get("research_objectives", [])
    obj_str = " | ".join(objectives[:4]) if objectives else ""
    segments = intel.get("key_segments", [])
    seg_str = " · ".join(
        f"{s.get('name', '')}({s.get('type', '')})" for s in segments
    ) if segments else ""

    intel_lines = [f"**{header}**"]
    if obj_str:
        intel_lines.append(f"Objectives: {obj_str}")
    if seg_str:
        intel_lines.append(f"Key Segments: {seg_str}")
    st.info("\n\n".join(intel_lines), icon="\U0001f4cb")

    # Re-analyze 버튼
    if st.button("Re-analyze Intelligence", key="re_analyze_intel_btn"):
        client_brand = st.session_state.get("study_client_brand", doc.client_brand)
        study_objective = st.session_state.get("study_objective", doc.study_objective)
        doc.client_brand = client_brand
        doc.study_objective = study_objective
        with st.spinner("Re-analyzing survey intelligence..."):
            try:
                intelligence = analyze_survey_intelligence(
                    doc.questions, language="en",
                    client_brand=client_brand,
                    study_objective=study_objective,
                )
                enrich_document(doc, intelligence)
                st.session_state['survey_document'] = doc
                st.session_state['edited_df'] = doc.to_dataframe()
                st.success("Intelligence re-analyzed successfully!")
                st.rerun()
            except Exception as e:
                st.error(f"Re-analysis failed: {e}")


def _display_docx_results(survey_doc: SurveyDocument):
    """추출 결과를 스프레드시트(기본) + 트리뷰(접힘)로 표시"""
    edited_df = render_spreadsheet_view(survey_doc)
    st.session_state['edited_df'] = edited_df

    if st.checkbox("Show Tree View (detailed question cards)", value=False,
                    key="show_tree_view"):
        render_tree_view(survey_doc)
