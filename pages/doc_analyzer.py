import os
import time

import streamlit as st
from services.pdf_parser import read_pdf
from services.llm_client import MODEL_DOC_ANALYZER
from services.postprocessor import apply_postprocessing
from services.docx_parser import parse_docx
from services.docx_renderer import render_sections_to_annotated_text
from services.chunker import chunk_sections, chunk_text
from services.llm_extractor import extract_survey_questions
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
        st.success(f"Loaded from session: **{doc.filename}** — {len(doc.questions)} questions", icon="✅")
        st.caption("💡 This session was loaded from a saved file. You can proceed to other tools.")
        _render_intelligence_summary(doc)
        _display_docx_results(doc)
        return

    if uploaded_file is not None:
        st.success("Here are the results from extracting question numbers, questions, and question types from the uploaded file.", icon="✅")
    else:
        st.info('Please upload your questionnaire on the sidebar.', icon="ℹ️")
        return

    if uploaded_file is not None:
        if uploaded_file.name.endswith('.pdf'):
            _process_pdf(uploaded_file, client)
        elif uploaded_file.name.endswith('.docx'):
            _process_docx(uploaded_file, client)
        else:
            st.error("Unsupported file type. Please upload a .pdf or .docx file.")


def _process_pdf(uploaded_file, client):
    """PDF AI 추출 파이프라인 (DOCX와 동일한 LLM 경로)"""

    # ── Study Brief (optional) ──
    with st.expander("Study Brief (optional — improves enrichment quality)", expanded=False):
        brief_col1, brief_col2 = st.columns(2)
        with brief_col1:
            client_brand = st.text_input(
                "Client Brand",
                value=st.session_state.get("study_client_brand", ""),
                placeholder="e.g. Hyundai, Samsung, LG",
                help="The brand commissioning the study.",
                key="pdf_study_client_brand_input",
            )
            st.session_state["study_client_brand"] = client_brand
        with brief_col2:
            study_objective = st.text_input(
                "Study Objective",
                value=st.session_state.get("study_objective", ""),
                placeholder="e.g. Brand health tracking, Customer satisfaction",
                help="Research purpose.",
                key="pdf_study_objective_input",
            )
            st.session_state["study_objective"] = study_objective

    # 추출 버튼
    extract_button = st.button('Extract Questions with AI', key='extract_pdf_button', use_container_width=True)

    # 이전 결과가 있으면 표시
    if 'survey_document' in st.session_state and not extract_button:
        _display_docx_results(st.session_state['survey_document'])
        return

    if not extract_button:
        st.info("Click 'Extract Questions with AI' to start AI-powered PDF analysis.", icon="🤖")
        return

    # ── 추출 파이프라인 시작 ──
    model = MODEL_DOC_ANALYZER

    with st.status("Phase 1/5: Parsing PDF...", expanded=True) as status:
        # Phase 1: PDF 파싱
        status.write("Extracting text from PDF pages...")
        texts = read_pdf(uploaded_file)

        if not texts:
            status.update(label="Failed to extract text from PDF.", state="error")
            st.warning("Could not extract text from PDF.")
            return

        total_pages = len(texts)
        total_chars = sum(len(t) for t in texts)
        status.write(f"Parsed: {total_pages} pages, {total_chars:,} characters")

        # 텍스트 청킹
        chunks = chunk_text(texts)
        status.write(f"Split into {len(chunks)} chunk(s) for AI processing")

        # Phase 3 준비: LLM 추출
        progress_bar = status.progress(0.0)
        stats_line = status.empty()

        start_time = time.time()
        chunks_done = [0]
        total_questions_found = [0]

        def on_progress(event, data):
            elapsed = time.time() - start_time

            if event == "regex_done":
                status.update(label="Phase 2/5: Scanning for question patterns...")
                status.write(f"Quick scan found ~{data['total_hints']} potential questions")

            elif event == "rechunk":
                status.write(
                    f"Adaptive split: {data['original_chunks']} -> "
                    f"{data['new_chunks']} chunks ({data['reason']})"
                )

            elif event == "chunk_start":
                total = data['total_chunks']
                status.update(
                    label=f"Phase 3/5: Extracting questions with AI... "
                          f"(Chunk {chunks_done[0]}/{total} done)"
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

                e_m, e_s = divmod(int(elapsed), 60)
                status.write(
                    f"Chunk {data['chunk_index'] + 1}/{total}: "
                    f"{extracted} questions ({e_m}:{e_s:02d})"
                )

                status.update(
                    label=f"Phase 3/5: Extracting questions with AI... "
                          f"(Chunk {done}/{total} done)"
                )

                remaining = (elapsed / done * (total - done)) if done > 0 else 0
                remain_m, remain_s = divmod(int(remaining), 60)
                stats_line.write(
                    f"**{total_questions_found[0]}** questions found so far "
                    f"| Elapsed: {e_m}:{e_s:02d} "
                    f"| Remaining: ~{remain_m}:{remain_s:02d}"
                )

            elif event == "merge_done":
                progress_bar.progress(1.0)
                stats_line.write(
                    f"**{data['total_questions']}** questions extracted in total"
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
            label=f"Phase 4/5: Finalizing — {len(questions)} questions in {em}:{es:02d}",
            state="running", expanded=True,
        )

    if not questions:
        st.warning("No questions could be extracted. Please check if the document contains survey questions.")
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
    with st.status("Phase 5/5: Enriching survey intelligence...", expanded=True) as enrich_status:
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
            enrich_status.update(label="Phase 5/5: Enrichment complete!", state="complete")
        except Exception as e:
            enrich_status.update(label=f"Phase 5/5: Enrichment skipped ({e})", state="error")

    # 세션 상태 저장
    st.session_state['survey_document'] = survey_doc
    st.session_state['edited_df'] = survey_doc.to_dataframe()

    st.success(f"Successfully extracted **{len(questions)}** questions from the PDF!", icon="✅")

    # Intelligence 요약 카드
    _render_intelligence_summary(survey_doc)

    # 세션 저장 유도 배너
    with st.container(border=True):
        save_col1, save_col2 = st.columns([3, 1])
        with save_col1:
            st.markdown(
                "💾 **Save your session** to skip this step next time.  \n"
                "Upload the saved `.json` file later to instantly restore all results."
            )
        with save_col2:
            st.download_button(
                label="💾 Save Session",
                data=survey_doc.to_json_bytes(),
                file_name=f"{os.path.splitext(uploaded_file.name)[0]}_session.json",
                mime='application/json',
                use_container_width=True,
                type="primary",
            )

    st.toast("Extraction complete! Save your session for future use.", icon="💾")

    # 결과 표시
    _display_docx_results(survey_doc)


def _process_docx(uploaded_file, client):
    """DOCX AI 추출 파이프라인"""

    # ── Study Brief (optional) ──
    with st.expander("Study Brief (optional — improves enrichment quality)", expanded=False):
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
    extract_button = st.button('Extract Questions with AI', key='extract_docx_button', use_container_width=True)

    # 이전 결과가 있으면 표시
    if 'survey_document' in st.session_state and not extract_button:
        _display_docx_results(st.session_state['survey_document'])
        return

    if not extract_button:
        st.info("Click 'Extract Questions with AI' to start AI-powered questionnaire analysis.", icon="🤖")
        return

    # ── 추출 파이프라인 시작 ──
    model = MODEL_DOC_ANALYZER

    with st.status("Phase 1/5: Parsing DOCX structure...", expanded=True) as status:
        # Phase 1: DOCX 파싱
        status.write("Parsing DOCX structure (styles, lists, tables)...")
        try:
            sections = parse_docx(uploaded_file)
        except Exception as e:
            status.update(label="Failed to parse DOCX file.", state="error")
            st.error(f"Error parsing DOCX: {e}")
            return

        if not sections:
            status.update(label="No content found in DOCX.", state="error")
            st.warning("Could not extract content from the DOCX file.")
            return

        total_paragraphs = sum(len(s.paragraphs) for s in sections)
        total_tables = sum(len(s.tables) for s in sections)
        status.write(f"✅ Parsed: {len(sections)} sections, "
                     f"{total_paragraphs} paragraphs, {total_tables} tables")

        # Phase 1 cont: 어노테이션 텍스트 + 청킹
        chunks = chunk_sections(sections)
        status.write(f"✅ Split into {len(chunks)} chunk(s) for AI processing")

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
                status.update(label="Phase 2/5: Scanning for question patterns...")
                status.write(f"✅ Quick scan found ~{data['total_hints']} potential questions")

            elif event == "rechunk":
                status.write(
                    f"ℹ️ Adaptive split: {data['original_chunks']} → "
                    f"{data['new_chunks']} chunks ({data['reason']})"
                )

            elif event == "chunk_start":
                total = data['total_chunks']
                status.update(
                    label=f"Phase 3/5: Extracting questions with AI... "
                          f"(Chunk {chunks_done[0]}/{total} done)"
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
                    f"✅ Chunk {data['chunk_index'] + 1}/{total}: "
                    f"{extracted} questions ({e_m}:{e_s:02d})"
                )

                # Phase label 업데이트
                status.update(
                    label=f"Phase 3/5: Extracting questions with AI... "
                          f"(Chunk {done}/{total} done)"
                )

                # ETA + 누적 통계 한 줄 요약
                remaining = (elapsed / done * (total - done)) if done > 0 else 0
                remain_m, remain_s = divmod(int(remaining), 60)
                stats_line.write(
                    f"📊 **{total_questions_found[0]}** questions found so far "
                    f"| ⏱ Elapsed: {e_m}:{e_s:02d} "
                    f"| Remaining: ~{remain_m}:{remain_s:02d}"
                )

            elif event == "merge_done":
                progress_bar.progress(1.0)
                stats_line.write(
                    f"📊 **{data['total_questions']}** questions extracted in total"
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
            label=f"Phase 4/5: Finalizing — {len(questions)} questions in {em}:{es:02d}",
            state="running", expanded=True,
        )

    if not questions:
        st.warning("No questions could be extracted. Please check if the document contains survey questions.")
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
    with st.status("Phase 5/5: Enriching survey intelligence...", expanded=True) as enrich_status:
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
            enrich_status.update(label="Phase 5/5: Enrichment complete!", state="complete")
        except Exception as e:
            enrich_status.update(label=f"Phase 5/5: Enrichment skipped ({e})", state="error")

    # 세션 상태 저장
    st.session_state['survey_document'] = survey_doc
    st.session_state['edited_df'] = survey_doc.to_dataframe()

    st.success(f"Successfully extracted **{len(questions)}** questions from the document!", icon="✅")

    # Intelligence 요약 카드
    _render_intelligence_summary(survey_doc)

    # 세션 저장 유도 배너
    with st.container(border=True):
        save_col1, save_col2 = st.columns([3, 1])
        with save_col1:
            st.markdown(
                "💾 **Save your session** to skip this step next time.  \n"
                "Upload the saved `.json` file later to instantly restore all results."
            )
        with save_col2:
            st.download_button(
                label="💾 Save Session",
                data=survey_doc.to_json_bytes(),
                file_name=f"{os.path.splitext(uploaded_file.name)[0]}_session.json",
                mime='application/json',
                use_container_width=True,
                type="primary",
            )

    st.toast("Extraction complete! Save your session for future use.", icon="💾")

    # 결과 표시
    _display_docx_results(survey_doc)


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
    """추출 결과를 트리뷰와 스프레드시트 탭으로 표시"""
    tab_tree, tab_sheet = st.tabs(["Tree View", "Spreadsheet"])

    with tab_tree:
        render_tree_view(survey_doc)

    with tab_sheet:
        edited_df = render_spreadsheet_view(survey_doc)
        st.session_state['edited_df'] = edited_df
