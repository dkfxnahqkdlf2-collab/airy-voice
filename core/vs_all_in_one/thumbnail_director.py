# -*- coding: utf-8 -*-
"""
core.vs_all_in_one.thumbnail_director
Gemini 기반 대화형 썸네일 레이아웃 상태(JSON) 제어 디렉터 엔진
(지능형 다이내믹 구도 프리셋: 정면 대치, 다이내믹 사선, 체급 압살, 상하/좌우 분할 지원)
"""

import json
import re
from typing import Dict, Any, Tuple

from core.generator import _call_gemini_api
from core.vs_all_in_one import load_env_api_key


def get_initial_canvas_state(
    subject_a: str = "피사체 A",
    subject_b: str = "피사체 B",
    img_a_path: str = "",
    img_b_path: str = "",
    spec_a: str = "",
    spec_b: str = "",
    topic: str = "",
    layout: str = "facing",
) -> Dict[str, Any]:
    """1080x1920 (9:16) 규격의 초기 썸네일 캔버스 레이아웃 JSON을 생성합니다. (기본값: 정면 맞짱 대치 구도)"""
    hook_text = topic if topic else f"{subject_a} VS {subject_b}"
    if len(hook_text) > 18:
        hook_text = hook_text[:18]

    base_state = {
        "canvas": {
            "width": 1080,
            "height": 1920,
            "bg_color": "#ffffff",
            "bg_style": "cyclorama_pure_white",
            "shadow_enabled": True,
            "layout": layout,
        },
        "layers": [
            {
                "id": "subject_a",
                "name": subject_a,
                "type": "image",
                "src": img_a_path,
                "x": 300,
                "y": 780,
                "scale": 1.1,
                "rotation": 0,
                "flip_x": False,
                "visible": True,
                "is_clean_layer": True,
            },
            {
                "id": "subject_b",
                "name": subject_b,
                "type": "image",
                "src": img_b_path,
                "x": 780,
                "y": 1140,
                "scale": 1.1,
                "rotation": 0,
                "flip_x": True,
                "visible": True,
                "is_clean_layer": True,
            },
            {
                "id": "vs_badge",
                "name": "VS 배지",
                "type": "badge",
                "text": "VS",
                "x": 540,
                "y": 960,
                "size": 150,
                "style": "metallic_red_neon",
                "visible": True,
                "is_clean_layer": False,
            },
            {
                "id": "hook_headline",
                "name": "후킹 메인 타이틀",
                "type": "text",
                "text": hook_text,
                "x": 540,
                "y": 170,
                "font_size": 76,
                "color": "#FACC15",
                "stroke_color": "#000000",
                "stroke_width": 10,
                "font_weight": "900",
                "visible": True,
                "is_clean_layer": False,
            },
            {
                "id": "spec_tag_a",
                "name": f"{subject_a} 스펙 라벨",
                "type": "spec_hud",
                "text": spec_a if spec_a else f"{subject_a} SPEC",
                "x": 300,
                "y": 1400,
                "font_size": 36,
                "color": "#0284C7",
                "bg_color": "rgba(2, 132, 199, 0.15)",
                "border_color": "#38BDF8",
                "visible": True,
                "is_clean_layer": False,
            },
            {
                "id": "spec_tag_b",
                "name": f"{subject_b} 스펙 라벨",
                "type": "spec_hud",
                "text": spec_b if spec_b else f"{subject_b} SPEC",
                "x": 780,
                "y": 1400,
                "font_size": 36,
                "color": "#EA580C",
                "bg_color": "rgba(234, 88, 12, 0.15)",
                "border_color": "#FB923C",
                "visible": True,
                "is_clean_layer": False,
            },
        ],
    }

    # 지정된 레이아웃 프리셋 적용
    return apply_composition_preset(base_state, layout)


def apply_composition_preset(current_state: Dict[str, Any], preset_name: str) -> Dict[str, Any]:
    """
    순백색 스튜디오의 특성을 극대화하여 5대 핵심 썸네일 구도를 원클릭으로 변경합니다:
    - facing: ⚔️ 정면 맞짱 대치 (A 우측 응시, B 좌측 반전 응시, 중앙 VS)
    - diagonal: 📐 다이내믹 사선 액션 (좌상-우하 교차 돌진 앵글)
    - depth: 👑 체급 압살 원근 (A 전면 거대화, B 후면 원근 축소)
    - stacked: ↕️ 정통 상하 분할 (스펙 비교 최적화)
    - split: ↔️ 좌우 대칭 분할 (나란히 대칭 비교)
    """
    state = json.loads(json.dumps(current_state))
    state["canvas"]["layout"] = preset_name

    p = preset_name.lower().strip()

    for layer in state.get("layers", []):
        lid = layer.get("id")

        if p == "facing":  # ⚔️ 정면 맞짱 대치 구도
            if lid == "subject_a":
                layer.update({"x": 300, "y": 780, "scale": 1.1, "rotation": 0, "flip_x": False})
            elif lid == "subject_b":
                layer.update({"x": 780, "y": 1140, "scale": 1.1, "rotation": 0, "flip_x": True})
            elif lid == "vs_badge":
                layer.update({"x": 540, "y": 960, "size": 150})
            elif lid == "spec_tag_a":
                layer.update({"x": 300, "y": 1400})
            elif lid == "spec_tag_b":
                layer.update({"x": 780, "y": 1400})

        elif p == "diagonal":  # 📐 다이내믹 사선 액션 구도
            if lid == "subject_a":
                layer.update({"x": 360, "y": 620, "scale": 1.05, "rotation": 12, "flip_x": False})
            elif lid == "subject_b":
                layer.update({"x": 720, "y": 1300, "scale": 1.05, "rotation": -12, "flip_x": True})
            elif lid == "vs_badge":
                layer.update({"x": 540, "y": 960, "size": 140})
            elif lid == "spec_tag_a":
                layer.update({"x": 360, "y": 900})
            elif lid == "spec_tag_b":
                layer.update({"x": 720, "y": 1580})

        elif p == "depth":  # 👑 체급 압살 원근 구도 (A 전면 거대화)
            if lid == "subject_a":
                layer.update({"x": 540, "y": 1280, "scale": 1.35, "rotation": 0, "flip_x": False})
            elif lid == "subject_b":
                layer.update({"x": 540, "y": 580, "scale": 0.76, "rotation": 0, "flip_x": False})
            elif lid == "vs_badge":
                layer.update({"x": 540, "y": 860, "size": 130})
            elif lid == "spec_tag_a":
                layer.update({"x": 540, "y": 1680})
            elif lid == "spec_tag_b":
                layer.update({"x": 540, "y": 780})

        elif p == "split":  # ↔️ 좌우 대칭 분할 구도
            if lid == "subject_a":
                layer.update({"x": 300, "y": 960, "scale": 1.0, "rotation": 0, "flip_x": False})
            elif lid == "subject_b":
                layer.update({"x": 780, "y": 960, "scale": 1.0, "rotation": 0, "flip_x": True})
            elif lid == "vs_badge":
                layer.update({"x": 540, "y": 960, "size": 130})
            elif lid == "spec_tag_a":
                layer.update({"x": 300, "y": 1450})
            elif lid == "spec_tag_b":
                layer.update({"x": 780, "y": 1450})

        else:  # ↕️ stacked (정통 상하 분할) 기본값
            if lid == "subject_a":
                layer.update({"x": 540, "y": 500, "scale": 1.0, "rotation": 0, "flip_x": False})
            elif lid == "subject_b":
                layer.update({"x": 540, "y": 1420, "scale": 1.0, "rotation": 0, "flip_x": False})
            elif lid == "vs_badge":
                layer.update({"x": 540, "y": 960, "size": 140})
            elif lid == "spec_tag_a":
                layer.update({"x": 540, "y": 780})
            elif lid == "spec_tag_b":
                layer.update({"x": 540, "y": 1700})

    return state


def determine_best_composition(
    subject_a: str,
    subject_b: str,
    topic: str = "",
    gemini_api_key: str = "",
) -> str:
    """비교 대상과 주제의 특성을 Gemini가 분석하여 가장 클릭률(CTR)이 높은 최적 썸네일 구도를 자동 판정합니다."""
    key = gemini_api_key or load_env_api_key()
    if not key:
        return "facing"  # 기본값: 정면 대치

    prompt = f"""당신은 유튜브 쇼츠 썸네일 알고리즘 총괄 디렉터입니다.
비교 대상 [{subject_a}] vs [{subject_b}] (주제: {topic or '스펙 비교'})의 시각적 긴장감과 클릭률(CTR)을 극대화할 최적의 썸네일 구도 1가지를 선택하세요:

선택지:
1. "facing" : 두 피사체가 서로를 노려보며 마주보는 정면 맞짱 대치 (화력 대결, 라이벌 맞대결, 격돌 등에 최고)
2. "diagonal" : 두 피사체가 비스듬히 돌진하며 교차하는 사선 액션 (초음속 기동, 속도, 공중전 등에 최고)
3. "depth" : 한 피사체가 거대하게 앞쪽에 배치되고 상대는 뒤에 작게 배치되는 체급 압살 (체급 차이, 압도적 우위 등에 최고)
4. "stacked" : 위아래 1:1 수직 스택 (정밀 제원 수치 팩트 비교에 최고)

반드시 오직 단어 1개 (facing, diagonal, depth, stacked) 중 하나만 소문자로 출력하세요."""

    try:
        res = _call_gemini_api(prompt, key, json_mode=False)
        m = re.search(r"(facing|diagonal|depth|stacked)", res.lower())
        return m.group(1) if m else "facing"
    except Exception:
        return "facing"


def apply_director_instruction(
    current_state: Dict[str, Any],
    user_instruction: str,
    gemini_api_key: str = "",
) -> Tuple[Dict[str, Any], str]:
    """사용자의 자연어 편집 지시를 바탕으로 Gemini API가 캔버스 State JSON(구도, 위치, 크기, 반전, 각도)을 정밀 수정합니다."""
    key = gemini_api_key or load_env_api_key()

    # 빠른 키워드 구도 전환 프리셋 우선 처리
    inst_lower = user_instruction.lower().strip()
    if any(k in inst_lower for k in ["마주보", "대치", "맞짱", "정면 대치"]):
        new_st = apply_composition_preset(current_state, "facing")
        return new_st, "두 피사체가 서로를 향해 마주보는 '정면 맞짱 대치 구도'로 전환했습니다!"
    elif any(k in inst_lower for k in ["사선", "비스듬", "대각선", "교차"]):
        new_st = apply_composition_preset(current_state, "diagonal")
        return new_st, "두 피사체가 역동적으로 교차하는 '다이내믹 사선 액션 구도'로 전환했습니다!"
    elif any(k in inst_lower for k in ["체급", "압살", "앞에 크게", "원근"]):
        new_st = apply_composition_preset(current_state, "depth")
        return new_st, "주요 피사체를 전면에 거대하게 배치한 '체급 압살 원근 구도'로 전환했습니다!"
    elif any(k in inst_lower for k in ["상하", "위아래", "위 아래", "기본 분할"]):
        new_st = apply_composition_preset(current_state, "stacked")
        return new_st, "상단과 하단에 균등하게 배치된 '정통 상하 비교 구도'로 전환했습니다!"

    prompt = f"""당신은 유튜브 쇼츠(9:16) 비교 영상 및 썸네일 제작을 총괄하는 AI 제미나이 디렉터입니다.
사용자는 당신과 실시간 대화창을 통해 썸네일 캔버스 편집뿐만 아니라 쇼츠 영상 기획, 타이틀 추천, Google Flow 프롬프트 요청, 두 무기/대상의 스펙 및 팩트 질문 등 다양한 요청을 보냅니다.

[현재 캔버스 상태 JSON]
{json.dumps(current_state, ensure_ascii=False, indent=2)}

[사용자의 자연어 메시지]
"{user_instruction}"

[디렉터 행동 지침]
1. 사용자의 메시지가 **캔버스 레이아웃 수정 지시**인 경우:
   - 캔버스 해상도는 가로 1080, 세로 1920 (중심점: x=540, y=960)입니다.
   - 레이어(`subject_a`, `subject_b`, `vs_badge`, `hook_headline`, `spec_tag_a`, `spec_tag_b`)의 x, y, scale(0.3~2.5), rotation(-45~45), flip_x(true/false), text, color 등을 정확히 수정하세요.
   - director_comment에 무엇을 어떻게 수정했는지 1~2줄로 시원하고 친절하게 설명하세요.

2. 사용자의 메시지가 **기획/질문/추천/대화**인 경우:
   (예: "쇼츠 제목 3개 추천해줘", "Flow 프롬프트 짜줘", "비호2와 구르주 화력 차이가 뭐야?", "이 구도 괜찮아?" 등)
   - 캔버스 레이아웃(`updated_state`)은 현재 상태를 그대로 보존하세요.
   - director_comment에 질문에 대한 핵심적이고 프로페셔널한 답변(타이틀 후보, Flow 프롬프트 팁, 스펙 팩트 비교 등)을 2~4줄로 명쾌하게 제공하세요.

반드시 다음 JSON 형식으로만 응답하세요:
{{
  "director_comment": "사용자에게 전달할 답변 또는 수정 완료 코멘트",
  "updated_state": {{
    "canvas": {{ ... }},
    "layers": [ ... ]
  }}
}}
"""
    if not key:
        return _fallback_apply_instruction(current_state, user_instruction)

    try:
        raw_res = _call_gemini_api(prompt, key, json_mode=True)
        if not raw_res:
            return _fallback_apply_instruction(current_state, user_instruction)

        clean_json = re.sub(r"^```(?:json)?\s*", "", raw_res.strip(), flags=re.MULTILINE)
        clean_json = re.sub(r"\s*```$", "", clean_json.strip())
        res_data = json.loads(clean_json)

        comment = res_data.get("director_comment", "썸네일 레이아웃 수정을 완료했습니다.")
        updated_state = res_data.get("updated_state", current_state)
        return updated_state, comment
    except Exception as e:
        print(f"[apply_director_instruction] Error: {e}")
        return _fallback_apply_instruction(current_state, user_instruction)


def _fallback_apply_instruction(
    current_state: Dict[str, Any],
    user_instruction: str,
) -> Tuple[Dict[str, Any], str]:
    """API 호출 실패 시 키워드 기반 기본 조정 폴백"""
    state = json.loads(json.dumps(current_state))
    inst = user_instruction.lower()
    comment = "지시사항에 맞춰 썸네일 레이아웃을 조정했습니다."

    scale_delta = 0.0
    if "키워" in inst or "크게" in inst or "확대" in inst:
        scale_delta = 0.2
        comment = "피사체 크기를 20% 확대했습니다."
    elif "줄여" in inst or "작게" in inst or "축소" in inst:
        scale_delta = -0.2
        comment = "피사체 크기를 20% 축소했습니다."

    target_id = None
    if "위" in inst or "상단" in inst or "a" in inst or "1" in inst:
        target_id = "subject_a"
    elif "아래" in inst or "하단" in inst or "b" in inst or "2" in inst:
        target_id = "subject_b"

    for layer in state.get("layers", []):
        if target_id and layer["id"] == target_id and scale_delta != 0.0:
            layer["scale"] = max(0.3, min(2.5, round(layer.get("scale", 1.0) + scale_delta, 2)))
        elif not target_id and layer["type"] == "image" and scale_delta != 0.0:
            layer["scale"] = max(0.3, min(2.5, round(layer.get("scale", 1.0) + scale_delta, 2)))

        quote_m = re.search(r"['\"]([^'\"]+)['\"]", user_instruction)
        if quote_m and layer["id"] == "hook_headline":
            layer["text"] = quote_m.group(1)
            comment = f"헤드라인 타이틀을 '{quote_m.group(1)}'로 변경했습니다."

    return state, comment
