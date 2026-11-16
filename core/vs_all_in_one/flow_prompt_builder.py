# -*- coding: utf-8 -*-
"""
core.vs_all_in_one.flow_prompt_builder
2단계 썸네일 확정 구도 및 스펙 데이터를 승계하여 Google Flow 전환 영상 프롬프트를 자동 완성하는 엔진
"""

from typing import Dict, Any
from core.generator import generate_vs_prompt_pipeline


def build_flow_prompts_from_thumbnail_state(
    canvas_state: Dict[str, Any],
    subject_a_ko: str = "",
    subject_b_ko: str = "",
    topic: str = "",
    motion_a_ko: str = "",
    motion_b_ko: str = "",
    sfx_theme: str = "general",
) -> Dict[str, Any]:
    """2단계 확정 캔버스 상태 JSON으로부터 4대 고정 규칙이 적용된 Google Flow 3단계 프롬프트를 자동 생성합니다."""
    canvas_info = canvas_state.get("canvas", {})
    layers = {l["id"]: l for l in canvas_state.get("layers", [])}

    # 레이어에서 데이터 추출
    subj_a_layer = layers.get("subject_a", {})
    subj_b_layer = layers.get("subject_b", {})
    spec_a_layer = layers.get("spec_tag_a", {})
    spec_b_layer = layers.get("spec_tag_b", {})
    headline_layer = layers.get("hook_headline", {})

    sa_name = subject_a_ko or subj_a_layer.get("name") or "Subject A"
    sb_name = subject_b_ko or subj_b_layer.get("name") or "Subject B"
    spec_a_txt = spec_a_layer.get("text") or "PRIMARY SPECIFICATION A"
    spec_b_txt = spec_b_layer.get("text") or "PRIMARY SPECIFICATION B"
    headline_txt = topic or headline_layer.get("text") or f"{sa_name} vs {sb_name}"

    # 구도 판별 (2단계 캔버스의 layout 설정 또는 y/x 좌표 비율)
    layout = canvas_info.get("layout", "stacked")
    if subj_a_layer.get("x") != subj_b_layer.get("x") and abs(subj_a_layer.get("y", 0) - subj_b_layer.get("y", 0)) < 200:
        layout = "split"

    data_payload = {
        "subject_a": sa_name,
        "subject_b": sb_name,
        "subject_a_ko": sa_name,
        "subject_b_ko": sb_name,
        "subject_a_en": sa_name,
        "subject_b_en": sb_name,
        "topic": headline_txt,
        "motion_a_ko": motion_a_ko or "동적 메커니즘 가동",
        "motion_b_ko": motion_b_ko or "동시 물리 반응 작동",
        "motion_a_en": motion_a_ko or "Active dynamic propulsion and mechanical actuation",
        "motion_b_en": motion_b_ko or "Simultaneous mechanical physical actuation and reactive exhaust vent",
        "spec_label_a": spec_a_txt,
        "spec_label_b": spec_b_txt,
        "layout": layout,
        "sfx_theme": sfx_theme,
    }

    # core.generator의 검증된 프롬프트 파이프라인 호출
    res = generate_vs_prompt_pipeline(data_payload)

    return {
        "layout_used": layout,
        "spec_a": spec_a_txt,
        "spec_b": spec_b_txt,
        "step1_clean": res["step1_clean"],
        "step2_info": res["step2_info"],
        "step3_flow": res["step3_flow"],
        "master_copy_text": res["master_copy_text"],
    }
