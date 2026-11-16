"""
voice_studio.py
🎬 Shorts Voice Studio Pro - 초경량 나레이션 음성 & 캡컷 1줄 싱크 자막 전용 스튜디오
- 씬 구분 없이 전체 대본을 자유롭게 입력하면, 하나의 완성된 전체 나레이션(.mp3)과 캡컷 1줄 싱크 자막(.srt)을 즉시 생성
- 대본 수정 시 즉시 나레이션과 자막에 100% 반영 (씬 동기화 오류 및 씬 분할 스트레스 제로)
- 유튜브 주소에서 15~30초 목소리 따기 & AI 보이스 클로닝
- 마이크 즉석 녹음 지원 (더듬거리거나 발음이 틀려도 아나운서 클린 딕션으로 자동 교정 합성)
"""

import datetime
import json
import math
import os
import re
import subprocess
import sys
from pathlib import Path

# Windows 콘솔 인코딩(CP949) 충돌 방지
if sys.platform == "win32":
    try:
        if sys.stdout and hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        if sys.stderr and hasattr(sys.stderr, "reconfigure"):
            sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

import streamlit as st

# ── 코어 유틸 및 엔진 임포트 ──
from core.ffmpeg_utils import ensure_ffmpeg, get_ffmpeg_exe
ensure_ffmpeg()

from core.project_manager import (
    create_project,
    list_projects,
    load_project_meta,
    open_folder_in_explorer,
    save_project_meta,
)
from core.tts_engine import (
    QWEN_MODELS,
    QWEN_SPEAKERS,
    VOICE_CHOICES,
    generate_narration_from_full_script,
    get_audio_duration,
    get_pinned_voice,
    has_cached_voice_dna,
    is_qwen_available,
    save_pinned_voice,
    save_pinned_voice_from_file,
)
from core.voice_extractor import extract_voice_clip_from_youtube

VOICE_PROJECTS_ROOT = r"D:\쇼츠_보이스_프로젝트"


def render_voice_studio(is_embedded: bool = False):
    """보이스 & 캡컷 자막 전용 스튜디오 메인 렌더러 (씬 구분 없는 전체 대본 전용)"""
    os.makedirs(VOICE_PROJECTS_ROOT, exist_ok=True)

    # ── 커스텀 CSS 스타일링 ──
    st.markdown("""
    <style>
        .voice-header {
            font-size: 26px;
            font-weight: 800;
            color: #1e293b;
            margin-bottom: 4px;
            display: flex;
            align-items: center;
            gap: 8px;
        }
        .voice-sub {
            font-size: 14px;
            color: #64748b;
            margin-bottom: 20px;
        }
        .badge-pill {
            display: inline-block;
            padding: 3px 10px;
            border-radius: 9999px;
            font-size: 12px;
            font-weight: 700;
        }
        .badge-green { background-color: #dcfce7; color: #166534; }
        .badge-blue { background-color: #dbeafe; color: #1e40af; }
        .badge-gray { background-color: #f1f5f9; color: #475569; }
        .stat-card {
            background-color: #f8fafc;
            border: 1px solid #e2e8f0;
            border-radius: 8px;
            padding: 8px 14px;
            display: inline-flex;
            gap: 16px;
            align-items: center;
            font-size: 13px;
            color: #334155;
            margin-top: 6px;
        }
    </style>
    """, unsafe_allow_html=True)

    # ── 프로젝트 목록 관리 ──
    v_projects = list_projects(custom_root=VOICE_PROJECTS_ROOT)
    if not v_projects:
        init_vp = create_project("첫_나레이션_프로젝트", custom_root=VOICE_PROJECTS_ROOT)
        v_projects = list_projects(custom_root=VOICE_PROJECTS_ROOT)

    if "current_voice_project_path" not in st.session_state or not os.path.exists(st.session_state.current_voice_project_path):
        st.session_state.current_voice_project_path = v_projects[0]["path"]

    cur_p_path = st.session_state.current_voice_project_path
    cur_meta = load_project_meta(cur_p_path)

    # 프로젝트 변경 감지 및 대본 동기화
    if st.session_state.get("_last_loaded_voice_proj") != cur_p_path:
        st.session_state["_last_loaded_voice_proj"] = cur_p_path
        script_file_p = os.path.join(cur_p_path, "script.txt")
        if os.path.exists(script_file_p):
            with open(script_file_p, "r", encoding="utf-8") as sf:
                saved_text = sf.read()
        else:
            saved_text = cur_meta.get("script", "")
        st.session_state.voice_script_text = saved_text
        st.session_state.voice_script_textarea = saved_text

    if "voice_script_text" not in st.session_state:
        st.session_state.voice_script_text = cur_meta.get("script", "")

    # ── 사이드바 영역 ──
    with st.sidebar:
        st.markdown("---")
        st.markdown("### 🎙️ 보이스 프로젝트")
        p_names = [p["name"] for p in v_projects]
        cur_p_name = os.path.basename(cur_p_path)
        sel_idx = p_names.index(cur_p_name) if cur_p_name in p_names else 0

        chosen_p_name = st.selectbox(
            "보이스 프로젝트 선택",
            options=p_names,
            index=sel_idx,
            key="sel_voice_project_widget",
        )
        new_p_path = os.path.join(VOICE_PROJECTS_ROOT, chosen_p_name)
        if new_p_path != cur_p_path:
            st.session_state.current_voice_project_path = new_p_path
            loaded_sc = load_project_meta(new_p_path).get("script", "")
            sf_path = os.path.join(new_p_path, "script.txt")
            if os.path.exists(sf_path):
                try:
                    with open(sf_path, "r", encoding="utf-8") as f:
                        loaded_sc = f.read()
                except Exception:
                    pass
            st.session_state.voice_script_text = loaded_sc
            st.session_state.voice_script_textarea = loaded_sc
            st.rerun()

        with st.popover("➕ 새 음성 프로젝트 생성", use_container_width=True):
            new_v_title = st.text_input("새 프로젝트 주제명 입력", placeholder="예: 우주망원경_쇼츠", key="input_new_voice_title")
            if st.button("🚀 프로젝트 생성", type="primary", use_container_width=True, key="btn_create_v_proj"):
                if new_v_title.strip():
                    np = create_project(new_v_title.strip(), custom_root=VOICE_PROJECTS_ROOT)
                    st.session_state.current_voice_project_path = np["path"]
                    st.session_state.voice_script_text = ""
                    st.session_state.voice_script_textarea = ""
                    st.toast(f"✅ 새 프로젝트 '{np['name']}' 생성 완료!", icon="🎉")
                    st.rerun()

        if st.button("📁 현재 프로젝트 폴더 열기", use_container_width=True, key="btn_open_v_folder"):
            open_folder_in_explorer(cur_p_path)
            st.toast("📁 프로젝트 폴더를 탐색기에서 열었습니다!", icon="📂")

        st.markdown("---")
        st.markdown("#### 📌 대표 복제 보이스 상태")
        pinned_v = get_pinned_voice()
        has_pinned = bool(pinned_v and os.path.exists(pinned_v.get("audio_path", "")))
        dna_cached = has_cached_voice_dna()

        if has_pinned:
            st.markdown(f"**보이스명**: `{pinned_v.get('name', '대표 보이스')}`")
            st.audio(pinned_v["audio_path"])
            st.markdown("<span class='badge-pill badge-green'>✅ 메인 보이스 영구 고정</span>", unsafe_allow_html=True)
            if dna_cached:
                st.markdown("<div style='height:4px;'></div><span class='badge-pill badge-blue'>⚡ 목소리 DNA 캐시 활성 (0초 적용)</span>", unsafe_allow_html=True)
        else:
            st.info("아직 등록된 대표 목소리가 없습니다. 본문에서 마이크로 말하거나 유튜브에서 따올 수 있습니다.")

        st.caption(f"📍 저장 위치: `{VOICE_PROJECTS_ROOT}`")

    # ── 메인 화면 ──
    st.markdown("<div class='voice-header'>🎙️ Shorts Voice Studio Pro</div>", unsafe_allow_html=True)
    st.markdown("<div class='voice-sub'>씬 구분 없이 전체 대본을 자유롭게 입력하면, 하나의 완성형 나레이션(.mp3)과 캡컷 1줄 싱크 자막(.srt)을 즉시 생성합니다.</div>", unsafe_allow_html=True)

    # ────────────────────────────────────────────────────────────
    # [단계 1]: 📝 전체 대본 입력 및 실시간 편집 (씬 분할 없음)
    # ────────────────────────────────────────────────────────────
    with st.container(border=True):
        st.markdown("### 1. 📝 전체 대본 입력 (자유 작성 및 수정)")
        st.caption("💡 씬(Scene)을 나눌 필요가 없습니다! 전체 대본을 여기에 자유롭게 작성하거나 수정하세요. 대본을 고치고 생성 버튼을 누르면 수정한 내용 그대로 즉시 나레이션과 자막이 다시 생성됩니다.")

        SAMPLE_VOICE_SCRIPT = """지구상에서 가장 위험하고 신비로운 심해의 비밀이 마침내 밝혀졌습니다.
수심 1만 미터의 초고압 환경에서도 빛을 발하며 살아 숨쉬는 거대 생명체들이 발견된 것입니다!
인류가 달 표면보다도 알지 못했던 심해 해구의 수수께끼가 풀리고 있습니다.
다음 세대를 놀라게 할 최첨단 탐사 잠수정의 경이로운 기록을 지금 확인해 보세요."""

        col_s_top1, col_s_top2 = st.columns([1.5, 3.5])
        with col_s_top1:
            if st.button("💡 예시 대본 채우기", key="btn_fill_sample_v"):
                st.session_state.voice_script_text = SAMPLE_VOICE_SCRIPT
                st.session_state.voice_script_textarea = SAMPLE_VOICE_SCRIPT
                save_project_meta(cur_p_path, {"script": SAMPLE_VOICE_SCRIPT})
                try:
                    with open(os.path.join(cur_p_path, "script.txt"), "w", encoding="utf-8") as sf:
                        sf.write(SAMPLE_VOICE_SCRIPT)
                except Exception:
                    pass
                st.rerun()

        v_script_input = st.text_area(
            "전체 영상 대본 입력",
            value=st.session_state.voice_script_text,
            height=220,
            placeholder="여기에 쇼츠 전체 대본을 자유롭게 입력하거나 붙여넣으세요...\n\n대본을 수정하면 즉시 나레이션 음성과 캡컷 자막에 100% 그대로 반영됩니다.",
            key="voice_script_textarea",
            label_visibility="collapsed",
        )

        # 실시간 자동 저장 동기화
        if v_script_input != st.session_state.voice_script_text:
            st.session_state.voice_script_text = v_script_input
            save_project_meta(cur_p_path, {"script": v_script_input})
            try:
                with open(os.path.join(cur_p_path, "script.txt"), "w", encoding="utf-8") as sf:
                    sf.write(v_script_input)
            except Exception:
                pass

        # 글자 수 및 예상 시간 실시간 통계
        clean_text_for_stat = re.sub(r'\[Scene\s*\d+\]|\(Scene\s*\d+\)', '', v_script_input).strip()
        total_chars = len(clean_text_for_stat)
        no_spaces = len(re.sub(r'\s+', '', clean_text_for_stat))
        est_seconds = round(no_spaces / 7.5, 1) if no_spaces > 0 else 0.0

        col_st1, col_st2 = st.columns([3.5, 1.2])
        with col_st1:
            st.markdown(
                f"""
                <div class='stat-card'>
                    <span>📝 전체 글자 수: <b>{total_chars}자</b></span>
                    <span>🔤 공백 제외: <b>{no_spaces}자</b></span>
                    <span>⏱️ 예상 나레이션 길이: 약 <b>{est_seconds}초</b> (쇼츠 60초 최적화)</span>
                </div>
                """,
                unsafe_allow_html=True,
            )
        with col_st2:
            if st.button("💾 대본 즉시 저장", use_container_width=True, key="btn_save_v_script"):
                save_project_meta(cur_p_path, {"script": v_script_input})
                with open(os.path.join(cur_p_path, "script.txt"), "w", encoding="utf-8") as sf:
                    sf.write(v_script_input)
                st.toast("✅ 대본이 안전하게 저장되었습니다!", icon="💾")

    # ────────────────────────────────────────────────────────────
    # [단계 2]: 🎙️ 목소리 선택 & 복제 (15~30초 롱샘플 딕션 극대화)
    # ────────────────────────────────────────────────────────────
    with st.container(border=True):
        st.markdown("### 2. 🎙️ 목소리 선택 & 내 목소리 복제 (15~30초 롱샘플 딕션 극대화)")
        st.caption("유튜브 주소로 목소리를 따오거나, 브라우저 마이크로 15초 편하게 말하여 내 목소리(Voice Clone)로 즉시 등록할 수 있습니다.")

        mode_options = ["voice_clone", "custom_voice", "edge_tts"]
        mode_labels = {
            "voice_clone": "🎙️ [대표 고정] 내 복제 음성 (Voice Clone)",
            "custom_voice": "🤖 Qwen3-TTS 공식 AI 프리셋 (소희/에이든/딜런)",
            "edge_tts": "⚡ Edge-TTS 초고속 쇼츠 음성 (인준/선희/현수)",
        }

        col_m_sel1, col_m_sel2 = st.columns([2.5, 1.5])
        with col_m_sel1:
            chosen_mode = st.radio(
                "합성 엔진 및 목소리 방식",
                options=mode_options,
                format_func=lambda x: mode_labels[x],
                horizontal=True,
                index=0 if has_pinned else 2,
                key="vstudio_voice_mode",
            )

        if chosen_mode == "voice_clone":
            tts_engine_type = "qwen-tts"
            qwen_mode = "voice_clone"
            qwen_model_size = "0.6B"
            qwen_speaker = "Sohee"
            qwen_instruct = ""
            chosen_voice = "ko-KR-InJoonNeural"
            chosen_rate = "+20%"

            if has_pinned:
                qwen_ref_audio = pinned_v["audio_path"]
                qwen_ref_text = pinned_v.get("ref_text", "")
                st.info(f"✨ 현재 등록된 대표 메인 보이스(`{pinned_v.get('name', '대표 보이스')}`)가 전체 대본 합성에 적용됩니다.")
            else:
                qwen_ref_audio = ""
                qwen_ref_text = ""
                st.warning("⚠️ 아직 등록된 메인 복제 보이스가 없습니다. 아래에서 유튜브 주소나 마이크 녹음으로 등록해 주세요.")

            # 목소리 변경/새로 따기 통합 패널
            with st.expander("🔄 [목소리 새로 등록 / 변경] 유튜브 링크 / 마이크 녹음 / 파일 업로드", expanded=(not has_pinned)):
                tab_yt, tab_mic, tab_file = st.tabs([
                    "🔗 유튜브에서 15~30초 목소리 따기",
                    "🎙️ 마이크로 말해서 내 목소리 등록",
                    "📁 오디오 파일 직접 등록",
                ])

                # 방법 1: 유튜브에서 목소리 따기
                with tab_yt:
                    st.markdown("좋아하는 유튜버나 롤모델 채널 주소(`@채널명` 또는 `영상 링크`)를 넣으면, **15~30초 분량의 깨끗한 음성을 5초 만에 추출**하여 등록합니다.")
                    yt_url_in = st.text_input("유튜브 채널 또는 영상 주소 입력", placeholder="예: https://www.youtube.com/@Channel or 영상 주소", key="vstudio_yt_url")

                    col_y1, col_y2, col_y3 = st.columns([1.5, 1.5, 2.0])
                    with col_y1:
                        y_start = st.number_input("추출 시작 위치(초)", min_value=0.0, value=15.0, step=1.0, key="vstudio_yt_start", help="나레이션이 시작되는 시간대(초)")
                    with col_y2:
                        y_dur = st.slider("추출 길이(초 - 딕션 극대화)", min_value=5.0, max_value=30.0, value=15.0, step=1.0, key="vstudio_yt_dur", help="15초~30초 정도로 충분히 길수록 AI의 딕션(발음 전달력)이 극대화됩니다.")
                    with col_y3:
                        st.markdown("<div style='height:28px;'></div>", unsafe_allow_html=True)
                        btn_y_ext = st.button("📥 유튜브에서 목소리 추출 & 미리듣기", key="btn_vstudio_y_ext", use_container_width=True)

                    if btn_y_ext:
                        if not yt_url_in.strip():
                            st.error("유튜브 URL을 입력해 주세요.")
                        else:
                            try:
                                with st.spinner("🔍 유튜브 오디오 스트림 분석 및 나레이션 추출 중... (수 초 소요)"):
                                    res_yt = extract_voice_clip_from_youtube(
                                        video_url=yt_url_in.strip(),
                                        start_sec=float(y_start),
                                        duration_sec=float(y_dur),
                                    )
                                    st.session_state.vstudio_yt_ext = res_yt
                                    st.toast("🎉 유튜브 음성 추출 성공!", icon="🎧")
                                    st.rerun()
                            except Exception as err:
                                st.error(f"유튜브 음성 추출 실패: {err}")

                    if "vstudio_yt_ext" in st.session_state and st.session_state.vstudio_yt_ext:
                        ext_i = st.session_state.vstudio_yt_ext
                        with st.container(border=True):
                            st.markdown(f"#### 🎧 추출된 목소리 미리듣기 (`{ext_i['start_sec']:.1f}초 ~ {ext_i['start_sec']+ext_i['duration_sec']:.1f}초` 구간)")
                            st.caption(f"📺 원본 영상: **{ext_i.get('title', '유튜브 영상')}**")
                            st.audio(ext_i["audio_path"])

                            col_y_s1, col_y_s2 = st.columns([1.5, 2.5])
                            with col_y_s1:
                                y_name = st.text_input("음성 별칭", value=f"{ext_i.get('title', '유튜브')[:15]} 나레이터", key="vstudio_y_alias")
                            with col_y_s2:
                                y_ref_t = st.text_input("나레이터가 말하는 대사 (비워두면 음색만 복제)", value=ext_i.get("suggested_text", ""), key="vstudio_y_reftxt")

                            col_b_reg, col_b_can = st.columns([2.5, 1.0])
                            with col_b_reg:
                                if st.button("⭐ 이 목소리를 내 대표 메인 보이스로 영구 고정 등록", type="primary", use_container_width=True, key="btn_confirm_vstudio_yt"):
                                    save_pinned_voice_from_file(
                                        ext_i["audio_path"],
                                        voice_name=y_name,
                                        ref_text=y_ref_t,
                                    )
                                    st.toast("🎉 대표 보이스로 등록 완료! 이제 모든 대본이 이 목소리로 생성됩니다.", icon="🎙️")
                                    st.session_state.pop("vstudio_yt_ext", None)
                                    st.rerun()
                            with col_b_can:
                                if st.button("취소", use_container_width=True, key="btn_cancel_vstudio_yt"):
                                    st.session_state.pop("vstudio_yt_ext", None)
                                    st.rerun()

                # 방법 2: 마이크 즉석 녹음
                with tab_mic:
                    st.markdown("#### 🎙️ 마이크로 15~20초 편하게 말하기")
                    st.markdown("""
                    > [!TIP]
                    > **발음이 꼬이거나 더듬거려도 괜찮습니다!**
                    > AI는 사용자의 **'목소리 음색(톤, 주파수)'**만 흡수하며, 대본을 읽을 때는 **지상파 아나운서처럼 100% 또렷한 클린 딕션**으로 자동 교정 합성합니다!
                    """)

                    mic_audio = st.audio_input("마이크 버튼을 누르고 15~20초 동안 아무 문장이나 읽어보세요", key="vstudio_mic_input")
                    if mic_audio:
                        st.audio(mic_audio)
                        col_m1, col_m2 = st.columns([1.5, 2.5])
                        with col_m1:
                            mic_name = st.text_input("내 목소리 별칭", value="내 오리지널 보이스", key="vstudio_mic_name")
                        with col_m2:
                            mic_text = st.text_input("녹음 시 읽은 대사 (대략 적어주시면 딕션이 더 좋아집니다)", value="", placeholder="비워두셔도 음색만 복제됩니다", key="vstudio_mic_txt")

                        if st.button("⭐ 이 녹음 음성을 내 대표 메인 보이스로 영구 등록", type="primary", use_container_width=True, key="btn_confirm_mic"):
                            save_pinned_voice(mic_audio.getbuffer(), "mic_recording.wav", voice_name=mic_name, ref_text=mic_text)
                            st.toast("🎉 내 목소리가 대표 메인 보이스로 영구 등록되었습니다!", icon="🎙️")
                            st.rerun()

                # 방법 3: 파일 직접 업로드
                with tab_file:
                    st.markdown("컴퓨터에 보관된 15~30초 분량의 깨끗한 음성 파일(mp3, wav, m4a)을 직접 등록합니다.")
                    up_f = st.file_uploader("참조 음성 파일 올리기", type=["mp3", "wav", "m4a"], key="vstudio_file_up")
                    if up_f:
                        st.audio(up_f)
                        col_f1, col_f2 = st.columns([1.5, 2.5])
                        with col_f1:
                            f_name = st.text_input("음성 별칭", value="내 대표 메인 보이스", key="vstudio_f_alias")
                        with col_f2:
                            f_ref_t = st.text_input("참조 대사 (오디오 대사)", value="", placeholder="비워두셔도 음색만 복제됩니다", key="vstudio_f_txt")
                        if st.button("📌 이 음성을 대표 메인 보이스로 영구 고정 저장", type="primary", use_container_width=True, key="btn_confirm_f_up"):
                            save_pinned_voice(up_f.getbuffer(), up_f.name, voice_name=f_name, ref_text=f_ref_t)
                            st.toast("🎉 대표 복제 음성이 성공적으로 등록되었습니다!", icon="🎙️")
                            st.rerun()

        elif chosen_mode == "custom_voice":
            tts_engine_type = "qwen-tts"
            qwen_mode = "custom_voice"
            qwen_model_size = "0.6B"
            qwen_ref_audio = ""
            qwen_ref_text = ""
            chosen_voice = "ko-KR-InJoonNeural"
            chosen_rate = "+20%"

            col_q1, col_q2 = st.columns([1.5, 1.2])
            with col_q1:
                qwen_speaker = st.selectbox(
                    "Qwen 프리셋 보이스 선택",
                    options=list(QWEN_SPEAKERS.keys()),
                    format_func=lambda x: QWEN_SPEAKERS[x],
                    index=2 if "Dylan" in QWEN_SPEAKERS else 0,
                    key="vstudio_sel_speaker",
                )
            with col_q2:
                qwen_instruct = st.text_input("목소리 스타일 연출", value="자신감 넘치고 긴박한 쇼츠 나레이션 톤", key="vstudio_instruct")

        else:
            tts_engine_type = "edge-tts"
            qwen_mode = "custom_voice"
            qwen_speaker = "Sohee"
            qwen_instruct = ""
            qwen_model_size = "0.6B"
            qwen_ref_audio = ""
            qwen_ref_text = ""

            col_e1, col_e2 = st.columns([1.5, 1.2])
            with col_e1:
                chosen_voice = st.selectbox("Edge 보이스 선택", options=list(VOICE_CHOICES.keys()), format_func=lambda x: VOICE_CHOICES[x], key="vstudio_sel_edge")
            with col_e2:
                chosen_rate = st.selectbox("재생 속도", options=["+10%", "+15%", "+20%", "+25%"], index=2, key="vstudio_sel_rate")

    # ────────────────────────────────────────────────────────────
    # [단계 3]: 🚀 원클릭 전체 나레이션 & 캡컷 1줄 싱크 자막 생성
    # ────────────────────────────────────────────────────────────
    with st.container(border=True):
        st.markdown("### 3. 🚀 전체 나레이션 & 캡컷 1줄 싱크 자막 원클릭 생성")

        current_script = st.session_state.voice_script_text.strip()
        if not current_script:
            st.warning("⚠️ 대본이 비어 있습니다. 1단계에서 전체 대본을 먼저 입력해 주세요!")
        else:
            st.markdown(f"**현재 설정**: 전체 대본 **{no_spaces}자** (공백 제외) | 엔진: `{tts_engine_type}`")

            if st.button("🎙️ 전체 나레이션 음성 & 캡컷 1줄 자막(.srt) 일괄 동시 생성하기", type="primary", use_container_width=True, key="btn_vstudio_gen"):
                status_box = st.status("🚀 전체 대본 고음질 나레이션 합성 및 캡컷 1줄 싱크 자막 계산 시작...", expanded=True)

                def _tts_prog(done, total, msg):
                    status_box.write(f"🔄 {msg}")

                try:
                    res = generate_narration_from_full_script(
                        script_text=current_script,
                        output_dir=cur_p_path,
                        voice=chosen_voice,
                        rate=chosen_rate,
                        title="쇼츠 나레이션",
                        progress_callback=_tts_prog,
                        engine=tts_engine_type,
                        qwen_mode=qwen_mode,
                        qwen_speaker=qwen_speaker,
                        qwen_instruct=qwen_instruct,
                        qwen_model_size=qwen_model_size,
                        qwen_ref_audio=qwen_ref_audio,
                        qwen_ref_text=qwen_ref_text,
                    )
                    status_box.update(label="🎉 전체 나레이션 음성 및 캡컷 자막(.srt) 생성 완료!", state="complete")
                    st.success(f"✅ 총 재생 시간: **{res['total_duration']:.1f}초** (총 {res.get('sentence_count', 1)}개 문장 합성) | 파일이 프로젝트 폴더에 완벽 저장되었습니다!")
                    st.rerun()
                except Exception as e:
                    status_box.update(label="❌ 음성 생성 중 오류 발생", state="error")
                    st.error(f"오류 상세: {e}")

        # 생성된 오디오 및 자막 프리뷰
        narration_p = os.path.join(cur_p_path, "narration.mp3")
        srt_p = os.path.join(cur_p_path, "subtitles.srt")

        if os.path.exists(narration_p) and os.path.exists(srt_p):
            st.markdown("---")
            st.markdown("#### 🎧 생성된 결과물 확인 & 캡컷 내보내기")

            col_a1, col_a2 = st.columns([2.5, 1.5])
            with col_a1:
                st.audio(narration_p)
                dur = get_audio_duration(narration_p)
                st.caption(f"⏱️ 총 오디오 길이: **{dur:.1f}초** | 📍 `{narration_p}`")
            with col_a2:
                with open(narration_p, "rb") as af:
                    st.download_button("⬇️ narration.mp3 다운로드", data=af, file_name="narration.mp3", mime="audio/mp3", use_container_width=True)
                with open(srt_p, "rb") as sf:
                    st.download_button("⬇️ subtitles.srt 다운로드", data=sf, file_name="subtitles.srt", mime="text/plain", use_container_width=True)

            col_open_f, col_spacer_f = st.columns([2, 2])
            with col_open_f:
                if st.button("✂️ 캡컷 타임라인으로 바로 드래그할 수 있게 폴더 열기", type="primary", use_container_width=True, key="btn_open_v_capcut"):
                    open_folder_in_explorer(cur_p_path)
                    st.toast("📁 작업 폴더를 열었습니다! narration.mp3와 subtitles.srt를 캡컷으로 드래그하세요.", icon="✂️")

            with st.expander("📝 캡컷 1줄 싱크 자막 (.srt) 실시간 편집 및 저장", expanded=False):
                with open(srt_p, "r", encoding="utf-8") as sf:
                    cur_srt_text = sf.read()
                st.caption("💡 자막 오타나 문장을 여기서 직접 수정한 뒤 [💾 수정한 자막 즉시 저장]을 누르면 subtitles.srt에 즉시 반영됩니다.")
                edited_srt = st.text_area("자막 내용 직접 수정", value=cur_srt_text, height=240, key="vstudio_textarea_srt")
                if st.button("💾 수정한 자막 (.srt) 즉시 저장", type="primary", use_container_width=True, key="btn_save_v_srt"):
                    with open(srt_p, "w", encoding="utf-8") as sf:
                        sf.write(edited_srt)
                    st.toast("✅ subtitles.srt 자막 파일이 성공적으로 저장되었습니다!", icon="💾")
                    st.rerun()


if __name__ == "__main__":
    st.set_page_config(
        page_title="Shorts Voice Studio Pro",
        page_icon="🎙️",
        layout="wide",
        initial_sidebar_state="expanded",
    )
    render_voice_studio(is_embedded=False)
