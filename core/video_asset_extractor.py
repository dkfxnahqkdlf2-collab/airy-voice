"""
core/video_asset_extractor.py
- 원본 영상(유튜브 링크 또는 로컬 MP4/MOV 파일)에서 대본/에셋 맞춤형 장면을 자동 분석 및 정밀 캡처하는 모듈
- 1) YouTube URL 고화질 다운로드 (yt-dlp)
- 2) OpenCV / FFmpeg 기반 타임스탬프 고화질 1프레임 정밀 추출
- 3) 영상 전체 균등/스마트 키프레임 샘플링 갤러리 생성
- 4) Gemini 비전 멀티모달을 활용한 대본 & 핵심 에셋 최적 장면 자동 매칭 추천
"""

import json
import os
import re
import shutil
import subprocess
import time
from typing import Dict, List, Optional, Tuple
from PIL import Image

# 코어 FFmpeg 경로 확보
from core.ffmpeg_utils import get_ffmpeg_exe

# Gemini API 지원
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


def format_time_str(seconds: float) -> str:
    """초 단위를 MM:SS 또는 HH:MM:SS 형식의 문자열로 변환"""
    sec = max(0.0, float(seconds))
    m, s = divmod(int(sec), 60)
    h, m = divmod(m, 60)
    if h > 0:
        return f"{h:02d}:{m:02d}:{s:02d}"
    return f"{m:02d}:{s:02d}"


def parse_time_str_to_seconds(time_str: str) -> float:
    """MM:SS, HH:MM:SS 또는 초 단위 문자열을 float 초로 변환"""
    if not time_str:
        return 0.0
    time_str = str(time_str).strip()
    try:
        if ":" in time_str:
            parts = [float(p) for p in time_str.split(":")]
            if len(parts) == 3:
                return parts[0] * 3600 + parts[1] * 60 + parts[2]
            elif len(parts) == 2:
                return parts[0] * 60 + parts[1]
        return float(time_str)
    except Exception:
        return 0.0


def download_youtube_video(url: str, output_dir: str) -> Tuple[bool, str]:
    """
    yt-dlp를 사용하여 유튜브 영상을 로컬 MP4 파일로 다운로드합니다.
    (에셋 캡처에 최적인 1080p 이하 MP4로 다운로드)
    반환: (성공여부, 비디오파일경로 또는 에러메시지)
    """
    try:
        import yt_dlp
    except ImportError:
        return False, "yt-dlp 모듈이 설치되어 있지 않습니다."

    os.makedirs(output_dir, exist_ok=True)
    out_template = os.path.join(output_dir, "%(title).50s [%(id)s].%(ext)s")

    ydl_opts = {
        # 1080p 이하 최고화질 mp4 결합 다운로드 (너무 큰 4K는 지연 유발 방지)
        "format": "bestvideo[height<=1080][ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best",
        "outtmpl": out_template,
        "merge_output_format": "mp4",
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            if not info:
                return False, "영상 정보를 가져올 수 없습니다."
            downloaded_file = ydl.prepare_filename(info)
            # 확장자가 mkv 등으로 결합되었을 경우 mp4 파일명 확인
            base, _ = os.path.splitext(downloaded_file)
            mp4_file = f"{base}.mp4"
            if os.path.exists(mp4_file):
                return True, os.path.abspath(mp4_file)
            if os.path.exists(downloaded_file):
                return True, os.path.abspath(downloaded_file)
            return False, "다운로드된 파일을 찾을 수 없습니다."
    except Exception as e:
        return False, f"YouTube 다운로드 실패: {e}"


def get_video_info(video_path: str) -> Dict:
    """비디오의 총 길이(초), 가로/세로 해상도, fps, 총 프레임 수를 반환"""
    default_info = {
        "duration": 0.0,
        "width": 1920,
        "height": 1080,
        "fps": 30.0,
        "total_frames": 0,
        "duration_str": "00:00",
        "valid": False,
    }
    if not video_path or not os.path.exists(video_path):
        return default_info

    try:
        import cv2
        cap = cv2.VideoCapture(video_path)
        if not cap.isOpened():
            return default_info

        fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 1920)
        height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 1080)
        duration = total_frames / fps if fps > 0 else 0.0
        cap.release()

        default_info.update({
            "duration": round(duration, 2),
            "width": width,
            "height": height,
            "fps": round(fps, 2),
            "total_frames": total_frames,
            "duration_str": format_time_str(duration),
            "valid": duration > 0,
        })
        return default_info
    except Exception as e:
        print(f"[get_video_info] OpenCV 분석 오류: {e}")
        return default_info


def extract_frame_at_time(video_path: str, time_sec: float, output_path: Optional[str] = None) -> Optional[Image.Image]:
    """
    지정한 시간(초)의 프레임을 고화질로 캡처합니다.
    output_path가 제공되면 파일로 저장하고, PIL Image 객체를 반환합니다.
    OpenCV 시도 후 실패 시 FFmpeg 서브프로세스로 안전하게 캡처합니다.
    """
    if not video_path or not os.path.exists(video_path):
        return None

    time_sec = max(0.0, float(time_sec))
    pil_img = None

    # 1. OpenCV 시도
    try:
        import cv2
        cap = cv2.VideoCapture(video_path)
        if cap.isOpened():
            # 밀리초 단위로 정확히 이동
            cap.set(cv2.CAP_PROP_POS_MSEC, time_sec * 1000.0)
            ret, frame = cap.read()
            cap.release()
            if ret and frame is not None and frame.size > 0:
                frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                pil_img = Image.fromarray(frame_rgb)
    except Exception as e:
        print(f"[extract_frame_at_time] OpenCV 캡처 실패, FFmpeg로 전환: {e}")

    # 2. FFmpeg 폴백 (OpenCV 실패 시 또는 키프레임 오차 보정)
    if pil_img is None and output_path:
        ffmpeg_exe = get_ffmpeg_exe()
        try:
            os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
            cmd = [
                ffmpeg_exe,
                "-y",
                "-ss", str(time_sec),
                "-i", video_path,
                "-vframes", "1",
                "-q:v", "2",
                output_path,
            ]
            r = subprocess.run(cmd, capture_output=True, timeout=10)
            if r.returncode == 0 and os.path.exists(output_path):
                pil_img = Image.open(output_path)
        except Exception as fe:
            print(f"[extract_frame_at_time] FFmpeg 캡처 실패: {fe}")

    # output_path 저장 처리
    if pil_img is not None and output_path:
        try:
            os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
            pil_img.save(output_path)
        except Exception as se:
            print(f"[extract_frame_at_time] 이미지 저장 실패: {se}")

    return pil_img


def extract_keyframe_samples(video_path: str, num_samples: int = 16, output_dir: Optional[str] = None) -> List[Dict]:
    """
    영상 전체 구간에서 균등하게 num_samples개의 키프레임을 추출하여
    타임코드 및 이미지 파일 경로 목록을 반환합니다.
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
    # 시작과 끝 여백 1초씩 두기
    start_t = min(1.0, duration * 0.05)
    end_t = max(start_t, duration * 0.95)
    step = (end_t - start_t) / max(1, (num_samples - 1))

    for i in range(num_samples):
        t = start_t + i * step
        if t > duration:
            t = duration
        t_str = format_time_str(t)
        safe_fname = f"keyframe_{i+1:02d}_{int(t)}s.jpg"
        save_path = os.path.join(output_dir, safe_fname)

        # 이미 추출된 프레임이 있으면 재활용 (초고속 캐싱)
        if not os.path.exists(save_path):
            img = extract_frame_at_time(video_path, t, output_path=save_path)
            if img is None:
                continue

        samples.append({
            "index": i + 1,
            "time_sec": round(t, 2),
            "time_str": t_str,
            "image_path": os.path.abspath(save_path),
        })

    return samples


def match_assets_with_gemini(
    keyframes: List[Dict],
    core_assets: List[Dict],
    script_text: str,
    gemini_api_key: str,
) -> Dict:
    """
    추출된 키프레임 목록과 대본의 핵심 에셋 정보를 Gemini 멀티모달에게 전달하여,
    각 에셋에 가장 잘 부합하는 최적의 키프레임 인덱스(1위, 2위)를 추천받습니다.
    """
    if not gemini_api_key or not keyframes or not core_assets:
        return {}

    candidate_models = [
        "gemini-3.5-flash",
        "gemini-3.5-flash-lite",
        "gemini-3.1-flash-lite",
        "gemini-flash-latest",
        "gemini-3.8-flash",
    ]

    # 키프레임 안내 목록 생성
    kf_meta_lines = []
    pil_images = []
    for kf in keyframes:
        idx = kf["index"]
        t_str = kf["time_str"]
        p = kf["image_path"]
        kf_meta_lines.append(f"- [키프레임 #{idx}] 타임스탬프: {t_str}")
        try:
            if os.path.exists(p):
                im = Image.open(p)
                im.thumbnail((512, 512))  # 토큰 절약 및 초고속 전송
                pil_images.append(im)
            else:
                pil_images.append(None)
        except Exception:
            pil_images.append(None)

    assets_desc = []
    for a_i, ast in enumerate(core_assets, 1):
        name = ast.get("name", f"에셋 {a_i}")
        atype = ast.get("type", "핵심 대상")
        desc = ast.get("search_keyword", name)
        assets_desc.append(f"{a_i}. [에셋 #{a_i}] 이름: {name} | 분류: {atype} | 핵심설명: {desc}")

    prompt_text = f"""당신은 쇼츠 영상 제작 전문 영상 편집 디렉터입니다.
현재 제작 중인 영상의 대본과 우리가 찾아야 할 [핵심 에셋 실물 목록]은 다음과 같습니다.

[대본 요약]
{script_text[:1000]}

[추출해야 할 핵심 에셋 목록]
{chr(10).join(assets_desc)}

[영상에서 추출한 키프레임 목록 ({len(keyframes)}장 순서대로 제공)]
{chr(10).join(kf_meta_lines)}

[미션]
제공된 키프레임 사진들을 분석하여, 위의 각 [에셋]에 가장 잘 어울리고 피사체가 선명하게 포착된 최적의 키프레임 번호(1~{len(keyframes)})를 1순위와 2순위로 추천하고, 그 이유를 1줄로 설명하세요.

반드시 오직 아래 JSON 형식으로만 응답하세요:
{{
  "recommendations": [
    {{
      "asset_idx": 1,
      "asset_name": "에셋 명칭",
      "best_keyframe_indices": [추천키프레임번호1, 추천키프레임번호2],
      "reason": "사유 (예: 미사일 발사관을 견착하고 조준하는 클로즈업 장면)"
    }}
  ]
}}
"""

    contents = []
    for im in pil_images:
        if im is not None:
            contents.append(im)
    contents.append(prompt_text)

    # 1. 최신 google.genai 시도
    if HAS_NEW_GENAI:
        try:
            client = genai.Client(api_key=gemini_api_key)
            for m_name in candidate_models:
                try:
                    resp = client.models.generate_content(
                        model=m_name,
                        contents=contents,
                        config={"response_mime_type": "application/json"},
                    )
                    if resp and resp.text:
                        raw = resp.text.strip()
                        raw = re.sub(r"^```json\s*", "", raw)
                        raw = re.sub(r"\s*```$", "", raw)
                        return json.loads(raw)
                except Exception as me:
                    print(f"[match_assets_with_gemini] genai {m_name} fail: {me}")
                    continue
        except Exception as ce:
            print(f"[match_assets_with_gemini] genai client err: {ce}")

    # 2. 레거시 google.generativeai 폴백
    if HAS_LEGACY_GENAI:
        try:
            legacy_genai.configure(api_key=gemini_api_key)
            for m_name in candidate_models:
                try:
                    model = legacy_genai.GenerativeModel(
                        m_name,
                        generation_config={"response_mime_type": "application/json"},
                    )
                    resp = model.generate_content(contents)
                    if resp and resp.text:
                        raw = resp.text.strip()
                        raw = re.sub(r"^```json\s*", "", raw)
                        raw = re.sub(r"\s*```$", "", raw)
                        return json.loads(raw)
                except Exception as le:
                    print(f"[match_assets_with_gemini] legacy {m_name} fail: {le}")
                    continue
        except Exception as oe:
            print(f"[match_assets_with_gemini] legacy err: {oe}")

    return {}
