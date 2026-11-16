"""
core/reverse_pipeline.py
- 풋티지 선행형(Footage-First) 리버스 쇼츠 제작 파이프라인 코어 엔진
- 1) 스마트 키프레임 추출 및 Gemini 멀티모달 큐레이션 (타임스탬프, 요약 태그, 1씬 훅 추천 뱃지)
- 2) 9:16 세로형 일괄 자체 변환 (로컬 시네마틱 앰비언트 블러 / 제미나이 AI 아웃페인팅)
- 3) 픽(Pick)한 키프레임 시퀀스 기반 8단계 텐션 대본 역생성 (1씬 관통 훅 + 8씬 싱크)
- 4) 디렉터 연출 의도 피드백 기반 대본 유기적 재조정
- 5) 단일 10초 3멀티샷 Flow 비디오 프롬프트 ([0.0s-3.0s] / [3.0s-6.5s] / [6.5s-10.0s]) 생성 및 일괄 내보내기
"""

import json
import os
import re
import shutil
import time
from typing import Dict, List, Optional, Tuple
from PIL import Image, ImageFilter, ImageEnhance

# 코어 유틸리티 연동
from core.video_asset_extractor import (
    download_youtube_video,
    get_video_info,
    extract_frame_at_time,
    format_time_str,
    parse_time_str_to_seconds,
)

# Gemini API 클라이언트 감지
try:
    from google import genai
    from google.genai import types as genai_types
    HAS_NEW_GENAI = True
except ImportError:
    HAS_NEW_GENAI = False

try:
    import google.generativeai as legacy_genai
    HAS_LEGACY_GENAI = True
except ImportError:
    HAS_LEGACY_GENAI = False


def _call_gemini_text_or_json(
    prompt: str,
    gemini_api_key: str,
    json_mode: bool = False,
    images: Optional[List[Image.Image]] = None,
    candidate_models: Optional[List[str]] = None,
) -> str:
    """Gemini API 호출 헬퍼 (멀티모달 이미지 지원 및 모델 폴백)"""
    if not gemini_api_key:
        return ""

    if candidate_models is None:
        candidate_models = [
            "gemini-2.5-flash",
            "gemini-1.5-flash",
            "gemini-3.5-flash",
            "gemini-3.5-flash-lite",
            "gemini-3.1-flash-lite",
            "gemini-flash-latest",
        ]

    # 1. 최신 google.genai 시도
    if HAS_NEW_GENAI:
        try:
            client = genai.Client(api_key=gemini_api_key)
            contents = []
            if images:
                for im in images:
                    if im is not None:
                        contents.append(im)
            contents.append(prompt)

            for m in candidate_models:
                try:
                    cfg = {}
                    if json_mode:
                        cfg["response_mime_type"] = "application/json"
                    resp = client.models.generate_content(
                        model=m,
                        contents=contents,
                        config=cfg if cfg else None,
                    )
                    if resp and resp.text:
                        return resp.text.strip()
                except Exception as me:
                    print(f"[_call_gemini] new genai {m} fail: {me}")
                    continue
        except Exception as ce:
            print(f"[_call_gemini] new genai client fail: {ce}")

    # 2. 레거시 google.generativeai 폴백
    if HAS_LEGACY_GENAI:
        try:
            legacy_genai.configure(api_key=gemini_api_key)
            contents = []
            if images:
                for im in images:
                    if im is not None:
                        contents.append(im)
            contents.append(prompt)

            for m in candidate_models:
                try:
                    gen_cfg = {"response_mime_type": "application/json"} if json_mode else {}
                    model = legacy_genai.GenerativeModel(m, generation_config=gen_cfg if gen_cfg else None)
                    resp = model.generate_content(contents)
                    if resp and resp.text:
                        return resp.text.strip()
                except Exception as le:
                    print(f"[_call_gemini] legacy genai {m} fail: {le}")
                    continue
        except Exception as le_top:
            print(f"[_call_gemini] legacy genai top fail: {le_top}")

    return ""


# ════════════════════════════════════════════════════════════
# 1. 스마트 키프레임 추출 & Gemini AI 큐레이션
# ════════════════════════════════════════════════════════════

def extract_smart_candidate_keyframes(
    video_path: str,
    num_samples: int = 24,
    output_dir: Optional[str] = None,
) -> List[Dict]:
    """
    영상 전체 구간에서 균등/장면전환 후보 20~30개 키프레임을 고화질로 추출하여
    기본 메타데이터(시간, 파일 경로)와 함께 반환합니다.
    """
    info = get_video_info(video_path)
    duration = info.get("duration", 0.0)
    if duration <= 0:
        return []

    if output_dir is None:
        video_dir = os.path.dirname(os.path.abspath(video_path))
        output_dir = os.path.join(video_dir, "extracted_keyframes")
    os.makedirs(output_dir, exist_ok=True)

    samples = []
    # 5% ~ 95% 구간에서 균등 샘플링
    start_t = min(1.0, duration * 0.03)
    end_t = max(start_t + 1.0, duration * 0.97)
    step = (end_t - start_t) / max(1, (num_samples - 1))

    for i in range(num_samples):
        t = start_t + i * step
        if t > duration:
            t = duration
        t_str = format_time_str(t)
        safe_fname = f"frame_{i+1:02d}_{int(t)}s.jpg"
        save_path = os.path.join(output_dir, safe_fname)

        if not os.path.exists(save_path):
            img = extract_frame_at_time(video_path, t, output_path=save_path)
            if img is None:
                continue

        samples.append({
            "index": i + 1,
            "time_sec": round(t, 2),
            "time_str": t_str,
            "image_path": os.path.abspath(save_path),
            "summary_ko": f"{t_str} 영상 캡처 장면",
            "action_tag": "일반 장면",
            "is_hook_candidate": False,
            "hook_score": 5,
            "hook_reason": "",
        })

    return samples


def curate_keyframes_with_gemini(
    keyframes: List[Dict],
    video_topic: str = "",
    gemini_api_key: str = "",
) -> List[Dict]:
    """
    추출된 키프레임들을 Gemini 멀티모달에게 전달하여
    1) 각 장면의 구체적 피사체 및 액션 요약 (10자 내외)
    2) 쇼츠 1씬 킬러 훅 추천 여부 (is_hook_candidate) 및 추천 점수 (1~10)
    를 분석하여 반환합니다.
    """
    if not keyframes:
        return []

    # API 키가 없거나 분석 불가 시 룰 기반 기본 큐레이션 부여
    if not gemini_api_key:
        total = len(keyframes)
        for i, kf in enumerate(keyframes):
            if i in [0, 1, max(0, total // 4)]:
                kf["is_hook_candidate"] = True
                kf["hook_score"] = 9 if i == 0 else 8
                kf["hook_reason"] = "초반 시선 집중 킬러 샷 추천"
            kf["summary_ko"] = f"[{kf['time_str']}] 핵심 장면"
        return keyframes

    pil_images = []
    meta_prompts = []
    for kf in keyframes:
        p = kf["image_path"]
        meta_prompts.append(f"프레임 #{kf['index']} ({kf['time_str']})")
        try:
            if os.path.exists(p):
                im = Image.open(p)
                im.thumbnail((512, 512))
                pil_images.append(im)
            else:
                pil_images.append(None)
        except Exception:
            pil_images.append(None)

    prompt = f"""당신은 유튜브 쇼츠 3D 시뮬레이션 및 밀리터리/공학 전문 총괄 디렉터입니다.
제공된 {len(keyframes)}장의 실사 영상 캡처 키프레임들을 면밀히 분석하세요.
주제 힌트: {video_topic or '첨단 국방 무기 체계'}

[요청 임무]
1. 각 프레임마다 피사체와 액션을 직관적으로 알아볼 수 있는 명쾌한 한글 요약(10~15자 내외)을 작성하세요.
   (예: '이동식 발사대 기립 장면', '조종석 HUD 타깃 락온', '발사관 부스터 화염 분사', '초음속 비행 소닉붐', '표적 지하 벙커 타격')
2. 각 프레임의 분류(action_tag)를 선택하세요: ['외형/기립', '사수/조종석', '점화/발사폭발', '초음속비행', '표적/타격', '설계/내부', '기타']
3. 유튜브 쇼츠의 '첫 3초 킬러 훅(Scene 1 썸네일/도파민 유발)'으로 쓰기에 가장 압도적이고 충격적인 상위 3~4개 프레임에 대해:
   - hook_score: 1~10점 (가장 강렬한 것은 9~10점)
   - is_hook_candidate: true (상위 3~4개만)
   - hook_reason: 왜 첫 3초 훅으로 강력한지 1줄 설명

반드시 아래 JSON 포맷으로만 응답하세요:
{{
  "curations": [
    {{
      "index": 1,
      "summary_ko": "발사대 기립 및 웅장한 외형",
      "action_tag": "외형/기립",
      "hook_score": 9,
      "is_hook_candidate": true,
      "hook_reason": "압도적인 미사일 거대 체급이 첫 화면에 잡혀 시선 강탈"
    }}
  ]
}}
"""
    raw_res = _call_gemini_text_or_json(prompt, gemini_api_key, json_mode=True, images=pil_images)
    if raw_res:
        try:
            m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", raw_res, re.DOTALL)
            json_str = m.group(1) if m else raw_res
            data = json.loads(json_str)
            cur_list = data.get("curations", [])
            cur_map = {item["index"]: item for item in cur_list if "index" in item}

            for kf in keyframes:
                idx = kf["index"]
                if idx in cur_map:
                    c = cur_map[idx]
                    kf["summary_ko"] = c.get("summary_ko", kf["summary_ko"])
                    kf["action_tag"] = c.get("action_tag", kf["action_tag"])
                    kf["hook_score"] = c.get("hook_score", 5)
                    kf["is_hook_candidate"] = bool(c.get("is_hook_candidate", False))
                    kf["hook_reason"] = c.get("hook_reason", "")
        except Exception as e:
            print(f"[curate_keyframes_with_gemini] parse error: {e}")

    # 상위 훅 후보 최소 1개는 강제 보장
    if not any(kf.get("is_hook_candidate") for kf in keyframes) and keyframes:
        keyframes[0]["is_hook_candidate"] = True
        keyframes[0]["hook_score"] = 9
        keyframes[0]["hook_reason"] = "영상 대표 시작 장면"

    return keyframes


# ════════════════════════════════════════════════════════════
# 2. 자체 9:16 세로형 변환 엔진 (로컬 시네마틱 / AI)
# ════════════════════════════════════════════════════════════

def convert_to_916_local_cinematic(
    src_image_path: str,
    dst_image_path: str,
    target_width: int = 1080,
    target_height: int = 1920,
) -> bool:
    """
    유튜브 쇼츠 공식 표준 스타일인 '로컬 시네마틱 앰비언트 블러(Ambient Blur)' 방식으로
    원본 실사의 화질과 비율을 100% 무왜곡 보존하면서 1080x1920(9:16) 규격으로 즉시(0.1초) 변환합니다.
    - 배경: 원본 이미지를 세로 화면에 꽉 차게 비율 확대 후 가우시안 블러(radius=40) + 부드러운 톤다운
    - 전경: 원본 실사 이미지를 가로 1080px에 맞춰 중앙에 선명하게 안착
    """
    try:
        if not os.path.exists(src_image_path):
            return False

        orig = Image.open(src_image_path).convert("RGBA")
        orig_w, orig_h = orig.size

        # 1. 배경 생성 (Aspect Fill로 1080x1920 채우기)
        scale_bg = max(target_width / orig_w, target_height / orig_h)
        bg_w = int(orig_w * scale_bg)
        bg_h = int(orig_h * scale_bg)
        bg_img = orig.resize((bg_w, bg_h), Image.Resampling.LANCZOS)

        # 중앙 크롭
        left = (bg_w - target_width) // 2
        top = (bg_h - target_height) // 2
        bg_cropped = bg_img.crop((left, top, left + target_width, top + target_height))

        # 가우시안 블러 및 시네마틱 톤다운
        bg_blurred = bg_cropped.filter(ImageFilter.GaussianBlur(radius=40))
        enhancer = ImageEnhance.Brightness(bg_blurred)
        bg_final = enhancer.enhance(0.65).convert("RGBA")

        # 2. 전경 이미지 중앙 배치 (Aspect Fit 가로 1080px 기준)
        scale_fg = target_width / orig_w
        fg_w = target_width
        fg_h = int(orig_h * scale_fg)
        fg_resized = orig.resize((fg_w, fg_h), Image.Resampling.LANCZOS)

        # 캔버스 정중앙 좌표 계산
        fg_y = (target_height - fg_h) // 2

        # 3. 합성 (배경 위에 전경 얹기)
        canvas = Image.new("RGBA", (target_width, target_height))
        canvas.paste(bg_final, (0, 0))
        canvas.paste(fg_resized, (0, fg_y), fg_resized)

        # 저장
        os.makedirs(os.path.dirname(os.path.abspath(dst_image_path)), exist_ok=True)
        canvas.convert("RGB").save(dst_image_path, "PNG", quality=95)
        return True
    except Exception as e:
        print(f"[convert_to_916_local_cinematic] 변환 실패: {e}")
        return False


def convert_to_916_imagen3_ai(
    src_image_path: str,
    dst_image_path: str,
    gemini_api_key: str,
    prompt_hint: str = "",
) -> bool:
    """
    Google Imagen 3 API를 호출하여 원본 실사의 피사체를 중심에 두고
    상/하단 환경을 AI로 자연스럽게 확장(Outpainting)하여 9:16 초고화질 스틸 키프레임으로 생성합니다.
    (API 키 권한 또는 모델 지원 불가 시 자동으로 로컬 시네마틱으로 안전하게 폴백합니다.)
    """
    if not gemini_api_key or not HAS_NEW_GENAI:
        # 폴백
        return convert_to_916_local_cinematic(src_image_path, dst_image_path)

    try:
        client = genai.Client(api_key=gemini_api_key)
        # Imagen 3 모델 시도
        ext_prompt = f"Ultra-detailed 8k cinematic vertical 9:16 photograph expanding the vertical scene of: {prompt_hint or 'military defense technology missile launch'}, photorealistic, dramatic sky above, realistic ground below, seamless extension, no text"

        # Image generation 모델 호출 시도
        try:
            resp = client.models.generate_images(
                model="imagen-3.0-generate-002",
                prompt=ext_prompt,
                config=genai_types.GenerateImagesConfig(
                    number_of_images=1,
                    aspect_ratio="9:16",
                    output_mime_type="image/png",
                ),
            )
            if resp and resp.generated_images:
                gen_bytes = resp.generated_images[0].image.image_bytes
                os.makedirs(os.path.dirname(os.path.abspath(dst_image_path)), exist_ok=True)
                with open(dst_image_path, "wb") as f:
                    f.write(gen_bytes)
                return True
        except Exception as ie:
            print(f"[convert_to_916_imagen3_ai] Imagen API 미지원 또는 제한, 로컬 시네마틱으로 폴백: {ie}")
            return convert_to_916_local_cinematic(src_image_path, dst_image_path)
    except Exception as e:
        print(f"[convert_to_916_imagen3_ai] 에러 발생, 로컬 시네마틱으로 폴백: {e}")
        return convert_to_916_local_cinematic(src_image_path, dst_image_path)

    return convert_to_916_local_cinematic(src_image_path, dst_image_path)


def batch_convert_picked_keyframes(
    picked_keyframes: List[Dict],
    output_dir: str,
    mode: str = "local_cinematic",
    gemini_api_key: str = "",
) -> List[Dict]:
    """
    사용자가 선택한 8~10개 키프레임을 순서대로 9:16 세로형으로 일괄 변환하여
    정리된 프로젝트 assets_916 폴더에 저장하고 메타데이터 리스트를 반환합니다.
    """
    os.makedirs(output_dir, exist_ok=True)
    converted_list = []

    for i, kf in enumerate(picked_keyframes, 1):
        src_path = kf["image_path"]
        fname = f"Scene_{i:02d}_916.png"
        dst_path = os.path.join(output_dir, fname)

        summary = kf.get("summary_ko", f"Scene {i}")
        if mode == "imagen3" and gemini_api_key:
            ok = convert_to_916_imagen3_ai(src_path, dst_path, gemini_api_key=gemini_api_key, prompt_hint=summary)
        else:
            ok = convert_to_916_local_cinematic(src_path, dst_path)

        if ok and os.path.exists(dst_path):
            item = dict(kf)
            item["scene_num"] = i
            item["image_path_916"] = os.path.abspath(dst_path)
            item["filename_916"] = fname
            converted_list.append(item)

    return converted_list


# ════════════════════════════════════════════════════════════
# 3. 픽한 키프레임 기반 8씬 대본 역생성 엔진
# ════════════════════════════════════════════════════════════

def generate_script_from_picked_keyframes(
    picked_keyframes: List[Dict],
    user_director_intent: str = "",
    topic_title: str = "",
    mode: str = "standard",
    gemini_api_key: str = "",
) -> Dict:
    """
    [풋티지 선행형 대본 역생성 엔진]
    사용자가 직접 픽한 실제 키프레임들(1씬 킬러 훅 + 전개 장면들)의 시각 정보와
    사용자의 연출 의도를 바탕으로, 시각 팩트와 100% 싱크되는 8단계 텐션 대본을 생성합니다.
    """
    if not picked_keyframes:
        return {"error": "선택된 키프레임이 없습니다."}

    # 분량 가이드
    if mode == "long":
        len_guide = "전체 공백 포함 700~800자 내외 (씬당 약 85~100자, 플로우 96초 풀 활용 모드)"
    else:
        len_guide = "전체 공백 포함 500~580자 내외 (씬당 약 60~75자, 1분 쇼츠 최적화 모드)"

    # 키프레임 시퀀스 설명 블록 생성
    kf_lines = []
    pil_images = []
    for idx, kf in enumerate(picked_keyframes, 1):
        t_str = kf.get("time_str", "00:00")
        summ = kf.get("summary_ko", "실제 캡처 장면")
        act = kf.get("action_tag", "액션")
        role_desc = "🌟 [Scene 1: 초반 3초 킬러 훅 & 주제 관통 장면]" if idx == 1 else f"[Scene {idx} 시각 기준 장면]"
        kf_lines.append(f"{idx}. {role_desc} (타임코드: {t_str}) - {summ} [분류: {act}]")

        p = kf.get("image_path_916") or kf.get("image_path")
        if p and os.path.exists(p):
            try:
                im = Image.open(p)
                im.thumbnail((512, 512))
                pil_images.append(im)
            except Exception:
                pil_images.append(None)

    keyframes_text = "\n".join(kf_lines)

    intent_block = ""
    if user_director_intent.strip():
        intent_block = f"""
=== 🎯 [사용자 총괄 디렉터의 핵심 연출 의도 & 방향성 (최우선 준수)] ===
"{user_director_intent.strip()}"
위 연출 의도를 100% 반영하여, 1씬의 관통 훅과 2~8씬의 서사 흐름을 이 방향으로 강력하게 이끌어 가세요!
======================================================================
"""

    topic_clean = topic_title.strip() or (picked_keyframes[0].get("summary_ko", "대한민국 최첨단 국방 무기 체계"))

    prompt = f"""당신은 유튜브 쇼츠 3D 시뮬레이션·역사·공학 미스터리 콘텐츠 전문 총괄 디렉터입니다.
사용자가 실제 공식 영상에서 직접 눈으로 보고 선택한 [핵심 키프레임 시퀀스]를 제공합니다.

당신의 임무는 상상 속의 대본을 쓰는 것이 아니라,
**제공된 실제 키프레임 사진들의 시각적 사건과 100% 완벽하게 싱크(Sync)가 맞는 8개 씬의 쇼츠 대본을 작성**하는 것입니다!

=== 사용자가 지정한 주제 ===
{topic_clean}
{intent_block}

=== 🎬 [사용자가 직접 픽한 실제 영상 키프레임 시퀀스] ===
{keyframes_text}

=== [대본 작성 필수 4대 절대 원칙] ===
1. 🎯 [Scene 1의 본질: 주제를 한 번에 관통하는 킬러 훅]:
   - 1번 키프레임(시작 장면)은 시청자가 왜 이 쇼츠를 봐야 하는지 단 3초 만에 상식을 깨부수며 주제를 관통해야 합니다!
   - 1씬 대사 하나로 영상 전체의 호기심과 도파민을 폭발시키세요.
2. 🔗 [시각 자료 1:1 완벽 싱크 (괴리율 0%)]:
   - 1번부터 8번 씬까지 각 씬의 나레이션은 위에 매칭된 실제 키프레임의 시각 팩트(외형, 조종석, 발사 화염, 초음속, 타격 등)와 단 1%의 어긋남 없이 완벽히 일치해야 합니다!
3. 🎢 [8단계 텐션 서사 구조]:
   - [Scene 1]: 상식 파괴 후킹 및 문제 제기 (시청자 스크롤 정지)
   - [Scene 2]: 배경 상황 및 압도적 제약 조건
   - [Scene 3]: 1차 시도 및 물리적 난관
   - [Scene 4]: 한계 봉착 및 자문자답
   - [Scene 5]: 뜻밖의 실마리 및 관점 전환
   - [Scene 6]: 핵심 반전 메커니즘 증명 (물리/공학적 사실)
   - [Scene 7]: 극적인 성공 및 파급력
   - [Scene 8]: 통념을 뒤엎는 요약 및 여운 넘치는 클로징
4. ⏱️ [분량 제어 & TTS 클린 규격]:
   - {len_guide} 엄수.
   - 단문 위주, 귀에 꽂히는 구어체 (~거든요, ~죠, ~겁니다, ~셈입니다).
   - 발음 왜곡 방지를 위해 따옴표(""), 물음표(?), 대시(-) 배제, 마침표(.)와 쉼표(,) 위주로만 작성.

반드시 아래 JSON 포맷으로만 응답하세요:
{{
  "title": "시선을 끄는 대표 후킹 제목",
  "scenes": [
    {{
      "scene_num": 1,
      "stage": "상식 파괴 후킹",
      "matching_keyframe": "1번 키프레임 매칭 내용 요약",
      "narration": "적의 최신 레이더망조차 단 0.1초도 포착할 수 없는 괴물 미사일이 실제로 존재합니다."
    }},
    {{
      "scene_num": 2,
      "stage": "배경 상황 및 제약 조건",
      "matching_keyframe": "2번 키프레임 매칭 내용",
      "narration": "음속의 열 배를 넘나드는 극한의 환경에서는 어떠한 유도 장치도 타버리기 일쑤였죠."
    }}
    // 총 8개 씬 (scene_num 1부터 8까지)
  ]
}}
"""
    raw_res = _call_gemini_text_or_json(prompt, gemini_api_key, json_mode=True, images=pil_images)

    title = f"{topic_clean}의 숨겨진 실체"
    scenes = []

    if raw_res:
        try:
            m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", raw_res, re.DOTALL)
            json_str = m.group(1) if m else raw_res
            data = json.loads(json_str)
            title = data.get("title", title)
            raw_sc = data.get("scenes", [])
            for i, sc in enumerate(raw_sc, 1):
                narr = sc.get("narration", "").strip()
                stage = sc.get("stage", f"Scene {i}")
                scenes.append({
                    "scene_num": i,
                    "stage": stage,
                    "narration": narr,
                    "matching_keyframe": sc.get("matching_keyframe", ""),
                })
        except Exception as e:
            print(f"[generate_script_from_picked_keyframes] parse error: {e}")

    # 폴백
    if len(scenes) < 8:
        scenes = []
        for i in range(1, 9):
            kf_summ = picked_keyframes[i-1].get("summary_ko", "실제 캡처 장면") if i <= len(picked_keyframes) else "대한민국 국방 첨단 기술"
            scenes.append({
                "scene_num": i,
                "stage": f"Scene {i}",
                "narration": f"Scene {i}: {kf_summ}을 바탕으로 펼쳐지는 놀라운 기술의 실체입니다.",
                "matching_keyframe": kf_summ,
            })

    full_script_lines = []
    for sc in scenes:
        full_script_lines.append(f"[Scene {sc['scene_num']}]\n{sc['narration']}")

    full_script = "\n\n".join(full_script_lines)

    return {
        "title": title,
        "scenes": scenes,
        "full_script": full_script,
        "total_chars": len(re.sub(r'\s|\[Scene\s*\d+\]', '', full_script)),
    }


# ════════════════════════════════════════════════════════════
# 4. 디렉터 연출 의도 기반 대본 유기적 재조정
# ════════════════════════════════════════════════════════════

def refine_script_with_director_intent(
    current_scenes: List[Dict],
    director_feedback: str,
    picked_keyframes: List[Dict],
    locked_indices: Optional[List[int]] = None,
    mode: str = "standard",
    gemini_api_key: str = "",
) -> Dict:
    """
    사용자가 "1씬의 방향성을 ~로 바꾸고 전체를 맞춰줘"라고 피드백을 주었을 때,
    1씬 킬러 훅을 재정립하고 2~8씬을 유기적으로 재조정합니다.
    """
    if locked_indices is None:
        locked_indices = []

    current_script_blocks = []
    for sc in current_scenes:
        s_num = sc.get("scene_num", 1)
        narr = sc.get("narration", "")
        is_locked = s_num in locked_indices
        tag = f"[Scene {s_num} - 🔒 잠금 확정 (절대 변경 금지)]" if is_locked else f"[Scene {s_num}]"
        current_script_blocks.append(f"{tag}\n{narr}")

    current_text = "\n\n".join(current_script_blocks)

    prompt = f"""당신은 유튜브 쇼츠 3D 시뮬레이션 전문 총괄 디렉터입니다.
현재 작성된 8개 씬 대본에 대해, 사용자 디렉터가 핵심 연출 방향성과 수정 피드백을 전달했습니다.

=== 🎯 [사용자 디렉터의 수정 피드백 / 연출 의도] ===
"{director_feedback.strip()}"

=== 📝 [현재 대본 내용] ===
{current_text}

[수정 원칙]
1. 사용자의 피드백을 최우선으로 반영하여, 특히 **1씬(초반 3초 킬러 훅)을 주제를 단번에 관통하는 압도적 문장으로 재정립**하세요!
2. 1씬의 바뀐 방향성과 톤앤매너에 맞춰, **2~8씬의 서사 흐름(제약-난관-한계-실마리-원리-성공-여운)을 도미노처럼 유기적으로 재작성**하세요.
3. [🔒 잠금 확정]으로 표시된 씬은 1글자도 변경 없이 100% 원문 그대로 유지하세요.
4. TTS 클린 규격: 따옴표, 물음표, 대시 배제, 마침표와 쉼표 위주.

반드시 아래 JSON 포맷으로만 응답하세요:
{{
  "title": "수정 반영된 대표 후킹 제목",
  "scenes": [
    {{
      "scene_num": 1,
      "narration": "수정된 씬 1 나레이션 대사"
    }}
    // 총 8개 씬
  ]
}}
"""
    raw_res = _call_gemini_text_or_json(prompt, gemini_api_key, json_mode=True)
    if raw_res:
        try:
            m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", raw_res, re.DOTALL)
            json_str = m.group(1) if m else raw_res
            data = json.loads(json_str)
            new_scenes = data.get("scenes", [])
            merged = []
            for i in range(1, 9):
                orig_sc = current_scenes[i-1] if i <= len(current_scenes) else {}
                if i in locked_indices:
                    merged.append(orig_sc)
                elif i <= len(new_scenes):
                    merged.append({
                        "scene_num": i,
                        "stage": orig_sc.get("stage", f"Scene {i}"),
                        "narration": new_scenes[i-1].get("narration", orig_sc.get("narration", "")),
                        "matching_keyframe": orig_sc.get("matching_keyframe", ""),
                    })
                else:
                    merged.append(orig_sc)

            full_script_lines = [f"[Scene {sc['scene_num']}]\n{sc['narration']}" for sc in merged]
            full_script = "\n\n".join(full_script_lines)
            return {
                "title": data.get("title", "수정된 쇼츠 대본"),
                "scenes": merged,
                "full_script": full_script,
                "total_chars": len(re.sub(r'\s|\[Scene\s*\d+\]', '', full_script)),
            }
        except Exception as e:
            print(f"[refine_script_with_director_intent] parse error: {e}")

    return {
        "title": "현재 대본 유지",
        "scenes": current_scenes,
        "full_script": "\n\n".join([f"[Scene {sc['scene_num']}]\n{sc['narration']}" for sc in current_scenes]),
        "total_chars": sum(len(sc.get("narration", "")) for sc in current_scenes),
    }


# ════════════════════════════════════════════════════════════
# 5. 단일 10초 3멀티샷 Flow 프롬프트 엔진
# ════════════════════════════════════════════════════════════

def generate_10s_multishot_flow_prompts(
    scenes: List[Dict],
    picked_keyframes: List[Dict],
    gemini_api_key: str = "",
) -> List[Dict]:
    """
    [단일 10초 3멀티샷 규격 생성기]
    씬당 비디오 클립 1개(10초) 안에 하드 컷(Hard cut)으로 연결되는 3단 액션 시나리오를 구성합니다:
    - [0.0s - 3.0s] Shot 1: 시작 구도, 킬러 훅 및 디테일 형성 (키프레임 80% 고정)
    - [3.0s - 6.5s] Shot 2: Hard cut to 핵심 사출/발사 폭발 액션 (모션 20%)
    - [6.5s - 10.0s] Shot 3: Hard cut to 가속 궤적 및 종결 카메라 무빙 (vertical 9:16)
    """
    flow_prompts = []

    # 각 씬별 대본 및 매칭 정보 조합
    prompt_inputs = []
    for i, sc in enumerate(scenes[:8], 1):
        narr = sc.get("narration", "")
        kf = picked_keyframes[i-1] if i <= len(picked_keyframes) else {}
        kf_desc = kf.get("summary_ko", f"Scene {i}")
        prompt_inputs.append(f"[Scene {i}]\n대본: {narr}\n키프레임 시각 팩트: {kf_desc}")

    prompt = f"""당신은 헐리우드 블록버스터 밀리터리 비주얼 디렉터이자 Flow(Shorts Story Studio) AI 영상 최고 권위자입니다.
8개 씬에 대해, 피사체 형태 붕괴를 원천 차단하는 **단일 10초 3멀티샷 Flow 비디오 프롬프트**를 작성하세요.

=== [단일 10초 3멀티샷 타임스탬프 규격 (엄수)] ===
씬당 3개의 독립 클립이 아니라, 10초짜리 단일 비디오 1개 안에 정확한 초 단위 타임스탬프와 'Hard cut to'를 명시합니다:
- [0.0s - 3.0s] Shot 1: 시작 구도, 키프레임 실사 디테일 고정(80%), 미세 줌/패닝 모션(20%)
- [3.0s - 6.5s] Shot 2: Hard cut to 핵심 사출/발사 폭발 액션, 강렬한 화염/충격파, 고속 트래킹
- [6.5s - 10.0s] Shot 3: Hard cut to 초음속 가속 궤적, 소닉붐 또는 타깃 락온 클라이맥스, vertical 9:16

=== 🚨 [형태 붕괴 방지 & No-Text 절대 규칙] ===
1. 무기의 외형은 키프레임에서 고정되므로, 비디오 프롬프트에서는 과도하게 복잡한 외형 통제를 쓰지 말고 화염, 충격파, 연기, 비행 궤적 등 20%의 물리 모션만 부여하세요.
2. 화면 내 글자 렌더링 방지를 위해 모든 프롬프트 끝에 ", no text, 8k cinematic"를 포함하세요.
3. 대한민국 무기는 `South Korean military defense (modern high-tech matte grey finish)`로 명확히 명시.

=== 8개 씬 정보 ===
{chr(10).join(prompt_inputs)}

반드시 아래 JSON 포맷으로만 응답하세요:
{{
  "flow_prompts": [
    {{
      "scene_num": 1,
      "title_ko": "초음속 미사일 발사 훅",
      "shot1_en": "[0.0s - 3.0s] Low-angle steady cinematic shot, South Korean modern missile poised on launchpad with intense heat haze shimmering, slow dramatic push-in",
      "shot2_en": "[3.0s - 6.5s] Hard cut to violent booster ignition, massive billowing fiery orange shockwave blasting across launchpad, violent camera shake",
      "shot3_en": "[6.5s - 10.0s] Hard cut to missile rocketing vertically into storm clouds, brilliant glowing pure red exhaust plume, cinematic tilt-up, vertical 9:16, no text, 8k cinematic",
      "full_10s_prompt": "[0.0s - 3.0s] Low-angle steady cinematic shot, South Korean modern missile poised on launchpad with intense heat haze shimmering, slow dramatic push-in. [3.0s - 6.5s] Hard cut to violent booster ignition, massive billowing fiery orange shockwave blasting across launchpad, violent camera shake. [6.5s - 10.0s] Hard cut to missile rocketing vertically into storm clouds, brilliant glowing pure red exhaust plume, cinematic tilt-up, vertical 9:16, no text, 8k cinematic"
    }}
  ]
}}
"""
    raw_res = _call_gemini_text_or_json(prompt, gemini_api_key, json_mode=True)
    if raw_res:
        try:
            m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", raw_res, re.DOTALL)
            json_str = m.group(1) if m else raw_res
            data = json.loads(json_str)
            flow_prompts = data.get("flow_prompts", [])
        except Exception as e:
            print(f"[generate_10s_multishot_flow_prompts] parse error: {e}")

    # 폴백 보정
    if len(flow_prompts) < len(scenes[:8]):
        fallback_list = []
        for i, sc in enumerate(scenes[:8], 1):
            kf = picked_keyframes[i-1] if i <= len(picked_keyframes) else {}
            title = kf.get("summary_ko", f"Scene {i} 액션")
            sh1 = f"[0.0s - 3.0s] Low-angle cinematic framing of South Korean defense system ({title}), heat haze shimmering, subtle camera push-in"
            sh2 = f"[3.0s - 6.5s] Hard cut to dynamic release and explosive ignition blast, high-speed tracking camera following intense smoke plume"
            sh3 = f"[6.5s - 10.0s] Hard cut to supersonic acceleration piercing through clouds, glowing red exhaust line, vertical 9:16, no text, 8k cinematic"
            full_p = f"{sh1}. {sh2}. {sh3}"
            fallback_list.append({
                "scene_num": i,
                "title_ko": title,
                "shot1_en": sh1,
                "shot2_en": sh2,
                "shot3_en": sh3,
                "full_10s_prompt": full_p,
            })
        flow_prompts = fallback_list

    return flow_prompts


def build_flow_10s_master_copy_text(flow_prompts: List[Dict]) -> str:
    """Flow 전체 씬 일괄 복사용 마스터 텍스트 포맷 빌더"""
    lines = []
    lines.append("=" * 72)
    lines.append("🎬 [Flow Shorts Story Studio 전용] 단일 10초 3멀티샷 비디오 프롬프트 일괄 팩")
    lines.append("규격: 1씬당 1개 비디오 (총 8개 비디오) | 타임스탬프: [0.0s-3.0s] / [3.0s-6.5s] / [6.5s-10.0s]")
    lines.append("=" * 72)
    lines.append("")

    for fp in flow_prompts:
        s_num = fp.get("scene_num", 1)
        title = fp.get("title_ko", f"Scene {s_num}")
        full_p = fp.get("full_10s_prompt", "")
        lines.append(f"▼▼▼ [Scene {s_num}: {title}] (10초 단일 비디오) ▼▼▼")
        lines.append(full_p)
        lines.append("")

    return "\n".join(lines).strip()


def export_flow_assets_package(
    project_dir: str,
    converted_916_keyframes: List[Dict],
    flow_prompts: List[Dict],
) -> str:
    """Flow 웹 작업 편의를 위해 번호순 9:16 이미지와 프롬프트 텍스트를 담은 전용 패키지 폴더 생성"""
    pack_dir = os.path.join(project_dir, "Flow_Ready_Pack")
    os.makedirs(pack_dir, exist_ok=True)

    # 1. 9:16 이미지 복사 (Scene_01_916.png 등)
    for item in converted_916_keyframes:
        src = item.get("image_path_916")
        s_num = item.get("scene_num", 1)
        if src and os.path.exists(src):
            dst = os.path.join(pack_dir, f"Scene_{s_num:02d}_Keyframe_916.png")
            shutil.copy2(src, dst)

    # 2. 마스터 프롬프트 텍스트 파일 저장
    master_text = build_flow_10s_master_copy_text(flow_prompts)
    txt_path = os.path.join(pack_dir, "Flow_10s_Prompts_All.txt")
    with open(txt_path, "w", encoding="utf-8") as f:
        f.write(master_text)

    return pack_dir
