# -*- coding: utf-8 -*-
"""
core.vs_all_in_one.studio_generator
[신규 고도화 파이프라인] 1단계 선정 실물 사진(Reference Image) 100% 고정 ➡️ 순백색 스튜디오 3D CAD 4단 멀티시트 및 1:1 맞짱 프롬프트 생성기
(Gemini Vision 멀티모달 외형 추출 & 레퍼런스 이미지 엄격 고정 가드레일 탑재)
"""

import os
import re
import json
import time
from typing import Dict, Any, Optional, List
from pathlib import Path
from PIL import Image

try:
    from google import genai
    from google.genai import types as genai_types
    HAS_NEW_GENAI = True
except ImportError:
    HAS_NEW_GENAI = False

from core.generator import _call_gemini_api
from core.searcher import generate_ai_image_pollinations
from core.vs_all_in_one import load_env_api_key, SOURCES_DIR


def extract_visual_features_from_image_or_text(
    subject_name: str,
    img_path: str = "",
    topic: str = "",
    spec_hint: str = "",
    gemini_api_key: str = "",
) -> str:
    """
    1단계에서 선정한 실물 사진이 존재할 경우 Gemini Vision 멀티모달로 실제 사진 속의
    외형(차륜형 바퀴/궤도, 포탑 구조, 주무장, 미사일 런처, 레이더 형태)을 1.5~2초 만에 직접 추출합니다.
    사진이 없거나 호출 실패 시 최신 스펙 힌트를 기반으로 텍스트 모델을 통해 고증 부품을 추출합니다.
    """
    key = gemini_api_key or load_env_api_key()
    s = subject_name.strip()
    if not s:
        return "accurate scale and physical military specifications"

    # 1. 1단계 실물 사진이 있는 경우: Gemini Vision 멀티모달 직접 분석 (최우선)
    if img_path and os.path.exists(img_path) and HAS_NEW_GENAI and key:
        try:
            http_opt = None
            if hasattr(genai_types, "HttpOptions") and hasattr(genai_types, "HttpRetryOptions"):
                retry_opt = genai_types.HttpRetryOptions(attempts=1)
                http_opt = genai_types.HttpOptions(timeout=12000, retry_options=retry_opt)
            client = genai.Client(api_key=key, http_options=http_opt)

            im = Image.open(img_path).convert("RGB")
            im.thumbnail((512, 512))

            vision_prompt = (
                f"Describe the exact physical military vehicle in this photo in 30~40 English words for 3D CAD modeling. "
                f"Identify chassis type (e.g. 8x8 wheeled armored vehicle or tracked chassis), exact wheel/track count, "
                f"turret shape, primary autocannon, missile pods, and radar sensor: "
            )

            resp = client.models.generate_content(
                model="gemini-3.1-flash-lite",
                contents=[im, vision_prompt],
            )
            if resp and resp.text:
                clean_vision = re.sub(r"[\n\r]+", ", ", resp.text.strip())
                clean_vision = re.sub(r'["\']', '', clean_vision)
                print(f"[extract_visual_features] Vision 추출 성공 for {s}: {clean_vision[:60]}...")
                return clean_vision
        except Exception as ve:
            print(f"[extract_visual_features] Vision error for {s}: {ve}, falling back to text prompt...")

    # 2. 텍스트 고증 분석 폴백 (구형 궤도형 착오 원천 방지)
    prompt = f"""당신은 세계 최고 수준의 군사 무기/산업 장비 고증 전문가입니다.
비교 대상 [{s}] (주제: {topic or '외형 및 스펙'}, 참고 스펙: {spec_hint or '최신 무기체계'})의 실제 외형을 AI가 엉뚱한 구형 모델이나 탱크로 왜곡하지 않고 100% 최신 실물 고증대로 재현할 수 있도록,
반드시 들어가야 할 핵심 외형 부품(예: 8×8 차륜형 장갑차 차체, 무인포탑, 기관포, 미사일 포드, AESA 레이더 등)을 영어 명사구 30~45단어로 정확히 나열하세요.

[🚨 절대 주의]
구형 모델(예: 구형 궤도식 탱크/장갑차)의 스펙을 절대 기재하지 마시고, 반드시 실제 최신 양산/시제 모델의 플랫폼(차륜형 vs 궤도형)과 무장에 맞추어 작성하세요.
응답은 오직 쉼표로 구분된 영문 명사구들만 출력하세요:"""

    try:
        res = _call_gemini_api(prompt, key, json_mode=False)
        clean = re.sub(r"[\n\r]+", ", ", res.strip())
        return clean if clean else f"{s}, modern combat chassis, advanced turret system, true physical military specifications"
    except Exception as e:
        print(f"[extract_visual_features] Text Error: {e}")
        return f"{s}, modern combat chassis, advanced turret system, true physical military specifications"


def format_strict_reference_sheet_prompt(subject: str, features: str) -> str:
    """첨부된 실물 사진을 100% 기준으로 고정하는 유튜브 쇼츠 9:16 4단 멀티시트 프롬프트를 포맷팅합니다."""
    feat_text = f" ({features})" if features else ""
    return (
        f"【🚨 제미나이 절대 필수: 첨부된 [{subject}] 실물 사진 100% 외형 고정】\n"
        f"1. 이 프롬프트와 함께 첨부된 [{subject}]의 실물 사진을 '유일하고 절대적인 외형 기준(Ground Truth Reference)'으로 삼으세요.\n"
        f"2. 사진 속에 나타난 포탑/동체 형태, 차체/기체 구조, 주무장 및 미사일 런처, 센서/레이더의 위치와 비율을 100% 동일하게 유지해야 합니다. (임의로 다른 구형 모델이나 가상의 무기로 변경 절대 금지!)\n"
        f"3. 이 첨부 사진의 무기 체계를 순백색 스튜디오(#FFFFFF) 배경의 '유튜브 쇼츠 9:16 세로형 4단 멀티앵글 스펙 시트(정면/측면/45도뷰티/무장클로즈업)'로 3D CAD 정밀 렌더링하세요.\n\n"
        f"(Vertical 9:16 aspect ratio, full mobile portrait format 1080x1920, --ar 9:16)\n"
        f"CRITICAL INSTRUCTION: You MUST use the attached reference photo as the STRICT, 100% SOURCE OF TRUTH for the physical geometry, turret, chassis/airframe structure, propulsion, and weapon systems of {subject}. "
        f"Maintain 100% morphological consistency with the physical subject shown in the uploaded reference photo{feat_text}. Do NOT invent different parts, do NOT change chassis/airframe configuration, and do NOT alter the weapon loadout.\n\n"
        f"Render a professional technical 4-panel multi-angle 3D CAD character model turnaround sheet of this EXACT subject from the attached photo on a pure solid seamless white studio cyclorama background (#FFFFFF), soft ground contact shadow:\n"
        f"- Panel 1 (Top-Left): Front ortho view showing front armor/cockpit, optics, and main silhouette\n"
        f"- Panel 2 (Top-Right): Side profile ortho view displaying complete chassis/hull/fuselage length and silhouette\n"
        f"- Panel 3 (Bottom-Left): 45-degree isometric beauty perspective view showing dynamic full 3D volume\n"
        f"- Panel 4 (Bottom-Right): Macro close-up view focusing on the primary turret/fuselage weapons, missile pods, and sensor suite\n\n"
        f"Style: Ultra-detailed 8K Octane 3D CAD industrial technical render, Unreal Engine 5.4 mechanical visualization, precision engineering panel lines, clean directional studio softbox lighting, pristine clean, uncropped, no background scenery, no text, no watermark, no human, full vertical 9:16 composition."
    )


def format_strict_facing_prompt(meta_a: Dict[str, str], meta_b: Dict[str, str]) -> str:
    """
    [에셋 3] 1:1 대각선 맞짱 대치 9:16 쇼츠 썸네일 프롬프트 (세이프 존 y축 18%~72% + 양국 국기 + 범용 무기 대응)
    """
    w1_name = (meta_a.get("name_en") or "WEAPON A").upper().strip()
    w2_name = (meta_b.get("name_en") or "WEAPON B").upper().strip()
    w1_flag = meta_a.get("country_en") or "South Korean"
    w2_flag = meta_b.get("country_en") or "Turkish"
    weapon_1_desc = meta_a.get("desc_en") or "tactical combat vehicle"
    weapon_2_desc = meta_b.get("desc_en") or "advanced combat platform"

    return f"""【🚨 제미나이 1:1 맞짱 대치 썸네일: 두 무기 첨부 사진 100% 외형 고정 + 쇼츠 세이프 존】
1. 첨부된 두 무기 [{w1_name}]와 [{w2_name}]의 사진(또는 4단 멀티앵글 스펙 시트) 속 외형과 도색을 100% 그대로 유지하세요.
2. 화면 상단 18%와 하단 28%는 유튜브 쇼츠 UI(아이콘, 제목, 자막 등)를 위해 순백색(#FFFFFF) 공백으로 완벽히 비워두세요. 두 기체와 텍스트를 포함한 모든 핵심 요소는 오직 화면 중앙 54% 영역(y축 18% ~ 72% 사이)에만 조밀하게 몰아서 배치해야 합니다.
3. 두 무기 전체(모든 궤도, 차체, 날개 끝, 선체, 포신, 안테나 끝까지)가 화면 안쪽으로 완전히 들어오도록 카메라 줌을 뒤로 훨씬 넓게 빼서(camera zoomed out significantly), 기체 외곽선과 화면 가장자리 사이에 충분한 여백을 확보하세요. (100% Uncropped, 100% full body visible inside center frame).

(Vertical 9:16 aspect ratio, YouTube Shorts safe-zone framing, y-axis 18% to 72% active zone, 1080x1920, --ar 9:16)
CRITICAL INSTRUCTION: You MUST reference the attached photos or 4-angle technical sheets of {w1_name} (left/bottom) and {w2_name} (right/top). Maintain 100% morphological fidelity to each weapon's attached reference image.
- Strict Safe-Zone Constraint: The top 18% (y: 0-18%) and bottom 28% (y: 72-100%) of the vertical 9:16 canvas MUST be completely empty, pure solid white (#FFFFFF) with absolutely zero graphics, shadows, or text extending into these areas. Everything must be scaled down and centered to fit within the y-axis range of 18% to 72%.
- Zoom & Padding: The camera is zoomed out heavily to ensure BOTH subjects are 100% uncropped with massive whitespace buffering all 4 borders.

Detailed Diagonal Layout:
- Middle-Left (y: 48% to 70%): {w1_name} ({weapon_1_desc}) must be scaled down significantly and placed in the lower-middle left, angled at 45 degrees towards the upper-right, aiming its nose/turret and main weapons aggressively UPWARD and to the right toward {w2_name}. It must sit comfortably above the y: 72% mark, entirely within the center canvas with the bottom edge/track/hull perfectly visible and well-elevated from the lower edge. Above it on the left, display a battle-worn waving {w1_flag} national flag and bold red '{w1_name}' typography with a subtle crisp dark drop-shadow, kept strictly below the top 18% line.
- Middle-Right (y: 20% to 42%): {w2_name} ({weapon_2_desc}) is scaled down and placed in the upper-middle right, angled at 45 degrees towards the lower-left, aiming its nose/turret and weapons directly DOWNWARD and to the left toward {w1_name}. Its highest antenna/tail/radar mast must stay well below the y: 18% top margin. Behind/above it on the right, display a waving {w2_flag} national flag, and below it on the right, display bold dark-olive '{w2_name}' typography with a subtle crisp drop-shadow.
- Center Split (y: 45%): A long, continuous, razor-sharp diagonal metallic slash line stretching across the center split between the two weapons, anchored by a high-contrast metallic 'VS' emblem with intense fiery sparks and glowing embers at the center point, entirely within the active middle zone.

Lighting & Render Style: Pure seamless solid white studio cyclorama background (#FFFFFF), high-contrast dramatic directional studio rim lighting carving out sharp edges, rich specular highlights on metallic and matte composite surfaces, deep crisp studio contact/drop shadows, 8K Octane 3D CAD industrial render, Unreal Engine 5.4 mechanical visualization, photorealistic, completely uncropped, no background scenery, no watermark, no human."""


def build_visual_features_from_specs(subject_name: str, spec_table: List[Dict[str, Any]], is_a: bool = True) -> str:
    """2단계에서 확정된 최신 팩트체크 스펙표로부터 0.001초 만에 고증 영문 부품 구문을 동적 추출합니다 (API 대기 0초)."""
    from core.vs_all_in_one.spec_analyzer import derive_weapon_metadata
    meta = derive_weapon_metadata(subject_name, spec_table, is_a=is_a)
    return meta.get("desc_en", "")


def build_unified_studio_prompts(
    subject_a: str,
    subject_b: str,
    topic: str = "",
    ref_img_a: str = "",
    ref_img_b: str = "",
    spec_table: List[Dict[str, Any]] = None,
    weapon_meta_a: Dict[str, str] = None,
    weapon_meta_b: Dict[str, str] = None,
    gemini_api_key: str = "",
) -> Dict[str, Any]:
    """1단계에서 선정한 실물 사진(Reference Image)과 최신 스펙을 기반으로 3대 핵심 에셋 프롬프트를 0초 대기로 즉각 생성합니다."""
    from core.vs_all_in_one.spec_analyzer import derive_weapon_metadata

    key = gemini_api_key or load_env_api_key()
    sa = subject_a.strip() or "비교 대상 A"
    sb = subject_b.strip() or "비교 대상 B"

    # 무기 메타데이터 (영문명, 소속 국가 영문 형용사, 외형·무장 요약) 자동 추출/보정
    meta_a = weapon_meta_a or derive_weapon_metadata(sa, spec_table, is_a=True)
    meta_b = weapon_meta_b or derive_weapon_metadata(sb, spec_table, is_a=False)

    # 1. 2단계 스펙표 기반 고증 데이터 우선 매핑 ({WEAPON_DESC})
    feat_a = (meta_a.get("desc_en") or "").strip()
    feat_b = (meta_b.get("desc_en") or "").strip()

    if not feat_a:
        feat_a = build_visual_features_from_specs(sa, spec_table, is_a=True)
    if not feat_b:
        feat_b = build_visual_features_from_specs(sb, spec_table, is_a=False)

    # 스펙표가 없거나 비어있는 경우에만 Vision/Text 질의 폴백
    if not feat_a:
        feat_a = extract_visual_features_from_image_or_text(sa, ref_img_a, topic, "", key)
    if not feat_b:
        feat_b = extract_visual_features_from_image_or_text(sb, ref_img_b, topic, "", key)

    # 2. 3대 핵심 에셋 프롬프트 엄격 포맷팅
    sheet_a = format_strict_reference_sheet_prompt(sa, feat_a)
    sheet_b = format_strict_reference_sheet_prompt(sb, feat_b)
    # [에셋 3] 맞짱 썸네일: 세이프 존 + 양국 국기 + 범용 무기 대응 템플릿
    facing_vs = format_strict_facing_prompt(meta_a, meta_b)

    base_style = "vertical 9:16 aspect ratio (1080x1920 full portrait orientation, --ar 9:16), isolated on a pure solid seamless white studio cyclorama background #FFFFFF, soft floor contact shadow, 8k 3D CAD industrial technical render, Unreal Engine 5.4 mechanical visualization, directional crisp studio rim lighting on metallic alloy edges, centered isometric beauty view, pristine clean, uncropped, no text, no watermark"
    hero_a = f"Vertical 9:16 YouTube Shorts portrait format, strictly replicating attached photo of {sa}, {feat_a}, {base_style}"
    hero_b = f"Vertical 9:16 YouTube Shorts portrait format, strictly replicating attached photo of {sb}, {feat_b}, {base_style}"

    return {
        "success": True,
        "visual_summary": f"🎯 [{meta_a.get('name_en')}] 및 [{meta_b.get('name_en')}] 실물 사진 및 세이프 존을 100% 고정한 3대 에셋 프롬프트 완성",
        # 메타데이터 포함
        "weapon_meta_a": meta_a,
        "weapon_meta_b": meta_b,
        # 3대 핵심 에셋
        "sheet_prompt_a": sheet_a,
        "sheet_prompt_b": sheet_b,
        "facing_prompt_vs": facing_vs,
        "hero_prompt_a": hero_a,
        "hero_prompt_b": hero_b,
        # Flow 카메라 무빙
        "motion_a_turn": f"Slow smooth 360-degree turntable product showcase orbit around {sa}, subtle metallic rim reflections, stable camera, no text",
        "motion_a_zoom": f"Slow dramatic macro push-in towards the turret and missile pods of {sa}, high tension, no text",
        "motion_b_turn": f"Slow smooth 360-degree turntable product showcase orbit around {sb}, subtle metallic rim reflections, stable camera, no text",
        "motion_b_zoom": f"Slow dramatic macro push-in towards the turret and weapon system of {sb}, high tension, no text",
        # 하위 호환 필드
        "flow_prompt_a": hero_a,
        "flow_prompt_b": hero_b,
        "flow_prompt_vs_facing": facing_vs,
        "flow_motion_a": f"Slow smooth 360-degree turntable orbit around {sa}, no text",
        "flow_motion_b": f"Slow smooth 360-degree turntable orbit around {sb}, no text",
        "prompt_a": hero_a,
        "prompt_b": hero_b,
        "prompt_head_to_head_916": facing_vs,
    }


def _fallback_studio_prompts(subject_a: str, subject_b: str, topic: str, feat_a: str = "", feat_b: str = "") -> Dict[str, Any]:
    """폴백 프롬프트"""
    sa = subject_a.strip() or "비교 대상 A"
    sb = subject_b.strip() or "비교 대상 B"
    fa = feat_a or f"{sa}, true physical military specifications"
    fb = feat_b or f"{sb}, true physical military specifications"
    return build_unified_studio_prompts(sa, sb, topic)

    p_facing = f"Vertical 9:16 full portrait aspect ratio (1080x1920) face-to-face confrontation between South Korea's {sa} on left facing right and {sb} on right facing left. Centered on a pure seamless white studio cyclorama background #FFFFFF, 8k Octane 3D CAD render, high-contrast studio rim lighting, photorealistic mechanical detail, no text, no watermark, --ar 9:16"

    return {
        "success": True,
        "visual_summary": f"{sa}와 {sb}의 황금 4대 에셋 고증 부품이 정밀 분석되었습니다.",
        "hero_prompt_a": hero_a,
        "sheet_prompt_a": sheet_a,
        "hero_prompt_b": hero_b,
        "sheet_prompt_b": sheet_b,
        "facing_prompt_vs": p_facing,
        "motion_a_turn": f"Slow smooth 360-degree turntable product showcase orbit around {sa}, subtle metallic rim reflections, no text",
        "motion_a_zoom": f"Slow dramatic macro push-in towards the turret and missile pods of {sa}, high tension, no text",
        "motion_b_turn": f"Slow smooth 360-degree turntable product showcase orbit around {sb}, subtle metallic rim reflections, no text",
        "motion_b_zoom": f"Slow dramatic macro push-in towards the turret and weapon system of {sb}, high tension, no text",
        # 호환용
        "flow_prompt_a": hero_a,
        "flow_prompt_b": hero_b,
        "flow_prompt_vs_facing": p_facing,
        "flow_motion_a": f"Slow smooth 360-degree turntable orbit around {sa}, no text",
        "flow_motion_b": f"Slow smooth 360-degree turntable orbit around {sb}, no text",
        "prompt_a": hero_a,
        "prompt_b": hero_b,
        "prompt_head_to_head_916": p_facing,
    }


def generate_studio_image(prompt: str, output_path: str, width: int = 1024, height: int = 1024) -> bool:
    """FLUX AI 모델을 호출하여 순백색 스튜디오 대표 이미지를 생성하고 로컬에 저장합니다."""
    if not prompt or not output_path:
        return False
    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
    return generate_ai_image_pollinations(prompt, output_path, width=width, height=height)


def create_studio_pair(
    subject_a: str,
    subject_b: str,
    topic: str = "",
    dest_dir: Optional[str] = None,
    gemini_api_key: str = "",
    width: int = 1024,
    height: int = 1024,
    progress_callback=None,
) -> Dict[str, Any]:
    """두 대상의 스튜디오 프롬프트 생성부터 실제 AI 대표 이미지 2장 생성까지 한 번에 수행합니다."""
    target_dir = Path(dest_dir) if dest_dir else SOURCES_DIR
    target_dir.mkdir(parents=True, exist_ok=True)

    if progress_callback:
        progress_callback(15, f"Gemini가 '{subject_a}'와 '{subject_b}'의 실제 외형 부품 고증을 분석 중...")

    prompts_data = build_unified_studio_prompts(
        subject_a=subject_a,
        subject_b=subject_b,
        topic=topic,
        gemini_api_key=gemini_api_key,
    )

    prompt_a = prompts_data.get("prompt_a", "")
    prompt_b = prompts_data.get("prompt_b", "")

    ts = int(time.time())
    file_a = str(target_dir / f"studio_rep_A_{ts}.png")
    file_b = str(target_dir / f"studio_rep_B_{ts}.png")

    # 대상 A 이미지 생성
    if progress_callback:
        progress_callback(40, f"🎨 [1/2] '{subject_a}' 고증 부품 반영 3D 스튜디오 이미지 생성 중...")
    ok_a = generate_studio_image(prompt_a, file_a, width=width, height=height)

    # 대상 B 이미지 생성
    if progress_callback:
        progress_callback(75, f"🎨 [2/2] '{subject_b}' 고증 부품 반영 3D 스튜디오 이미지 생성 중...")
    ok_b = generate_studio_image(prompt_b, file_b, width=width, height=height)

    if progress_callback:
        progress_callback(100, "🎉 두 대상의 스튜디오 대표 이미지 생성 완료!")

    return {
        "success": bool(ok_a or ok_b),
        "visual_summary": prompts_data.get("visual_summary", ""),
        "prompt_a": prompt_a,
        "prompt_b": prompt_b,
        "prompt_gemini_pro_a": prompts_data.get("prompt_gemini_pro_a", ""),
        "prompt_gemini_pro_b": prompts_data.get("prompt_gemini_pro_b", ""),
        "prompt_head_to_head_916": prompts_data.get("prompt_head_to_head_916", ""),
        "prompt_diagonal_916": prompts_data.get("prompt_diagonal_916", ""),
        "img_a_path": file_a if (ok_a and os.path.exists(file_a)) else "",
        "img_b_path": file_b if (ok_b and os.path.exists(file_b)) else "",
    }
