# -*- coding: utf-8 -*-
"""
core.vs_all_in_one.source_extractor
유튜브 영상 다운로드 및 OpenCV 기반 고화질 프레임 캡처 엔진
"""

import os
import re
import hashlib
import base64
import cv2
from pathlib import Path
from PIL import Image
from typing import Optional, Tuple, Dict, Any
import yt_dlp

from core.vs_all_in_one import SOURCES_DIR, PROJECT_ROOT

CACHE_DIR = PROJECT_ROOT / "captures" / "vs_studio" / "video_cache"
CACHE_DIR.mkdir(parents=True, exist_ok=True)


def image_to_base64(file_path: str) -> str:
    """로컬 이미지 파일을 웹 캔버스 주입용 Base64 Data URL 문자열로 변환합니다."""
    if not file_path or not os.path.exists(file_path):
        return ""
    try:
        ext = Path(file_path).suffix.lower().replace(".", "")
        if ext == "jpg":
            ext = "jpeg"
        with open(file_path, "rb") as f:
            encoded = base64.b64encode(f.read()).decode("utf-8")
            return f"data:image/{ext};base64,{encoded}"
    except Exception as e:
        print(f"[image_to_base64] Error: {e}")
        return ""


def get_video_id_from_url(url: str) -> str:
    """유튜브 URL에서 11자리 비디오 ID 또는 고유 해시 추출"""
    patterns = [
        r'(?:v=|\/)([0-9A-Za-z_-]{11}).*',
        r'(?:youtu\.be\/)([0-9A-Za-z_-]{11})',
        r'(?:shorts\/)([0-9A-Za-z_-]{11})',
    ]
    for p in patterns:
        m = re.search(p, url)
        if m:
            return m.group(1)
    # 일반 URL인 경우 해시값 반환
    return hashlib.md5(url.encode("utf-8")).hexdigest()[:12]


def download_youtube_video(url: str, max_height: int = 1080, progress_hook=None) -> Dict[str, Any]:
    """yt-dlp를 사용하여 유튜브 영상을 캐시 디렉터리에 다운로드하고 메타데이터와 파일 경로를 반환합니다."""
    url = url.strip()
    if not url:
        return {"success": False, "error": "URL이 비어 있습니다."}

    vid_id = get_video_id_from_url(url)
    expected_path = CACHE_DIR / f"{vid_id}.mp4"

    # 이미 다운로드된 캐시가 있으면 재사용
    if expected_path.exists() and expected_path.stat().st_size > 10000:
        info = get_video_metadata(str(expected_path))
        info["cached"] = True
        info["file_path"] = str(expected_path)
        info["video_id"] = vid_id
        return {"success": True, **info}

    ydl_opts = {
        "outtmpl": str(CACHE_DIR / f"{vid_id}.%(ext)s"),
        "format": f"bestvideo[ext=mp4][height<={max_height}]+bestaudio[ext=m4a]/best[ext=mp4][height<={max_height}]/best[height<={max_height}]",
        "merge_output_format": "mp4",
        "quiet": True,
        "no_warnings": True,
        "ignoreerrors": False,
        "socket_timeout": 30,
    }
    if progress_hook:
        ydl_opts["progress_hooks"] = [progress_hook]

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            meta = ydl.extract_info(url, download=True)
            title = meta.get("title", f"Video_{vid_id}")
            actual_file = str(expected_path)
            # 만약 다른 확장자로 저장되었을 경우 확인
            if not os.path.exists(actual_file):
                for f in CACHE_DIR.glob(f"{vid_id}.*"):
                    actual_file = str(f)
                    break

            info = get_video_metadata(actual_file)
            info["title"] = title
            info["video_id"] = vid_id
            info["file_path"] = actual_file
            info["cached"] = False
            return {"success": True, **info}
    except Exception as e:
        return {"success": False, "error": f"유튜브 다운로드 실패: {str(e)}"}


def get_video_metadata(file_path: str) -> Dict[str, Any]:
    """OpenCV로 비디오의 해상도, 총 프레임 수, FPS, 재생 시간(초)을 측정합니다."""
    if not os.path.exists(file_path):
        return {"duration": 0, "fps": 30.0, "width": 1920, "height": 1080, "total_frames": 0}

    cap = cv2.VideoCapture(file_path)
    if not cap.isOpened():
        return {"duration": 0, "fps": 30.0, "width": 1920, "height": 1080, "total_frames": 0}

    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    duration = total_frames / fps if fps > 0 else 0.0
    cap.release()

    return {
        "duration": round(duration, 2),
        "fps": round(fps, 2),
        "width": width,
        "height": height,
        "total_frames": total_frames,
    }


def extract_frame_at_timestamp(
    video_path: str,
    timestamp_sec: float,
    output_filename: Optional[str] = None,
    save_to_sources: bool = True,
    dest_dir: Optional[str] = None,
) -> Tuple[bool, Optional[Image.Image], Optional[str]]:
    """지정한 초(timestamp_sec) 지점의 고화질 프레임을 추출하여 PIL Image 및 파일 경로를 반환합니다."""
    if not os.path.exists(video_path):
        return False, None, None

    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        return False, None, None

    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    target_frame = int(timestamp_sec * fps)
    cap.set(cv2.CAP_PROP_POS_FRAMES, target_frame)

    ret, frame = cap.read()
    cap.release()

    if not ret or frame is None:
        return False, None, None

    # BGR -> RGB 변환
    rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
    pil_img = Image.fromarray(rgb_frame)

    saved_path = None
    if save_to_sources:
        target_dir = Path(dest_dir) if dest_dir else SOURCES_DIR
        target_dir.mkdir(parents=True, exist_ok=True)

        if not output_filename:
            safe_ts = f"{timestamp_sec:.2f}".replace(".", "_")
            output_filename = f"frame_{safe_ts}.png"
        if not output_filename.lower().endswith(".png"):
            output_filename += ".png"

        save_full_path = target_dir / output_filename
        pil_img.save(str(save_full_path), format="PNG", quality=95)
        saved_path = str(save_full_path)

    return True, pil_img, saved_path


def save_uploaded_source_image(uploaded_file, target_name: str, dest_dir: Optional[str] = None) -> str:
    """사용자가 직접 업로드한 이미지 파일을 소스 보관함에 저장합니다."""
    target_dir = Path(dest_dir) if dest_dir else SOURCES_DIR
    target_dir.mkdir(parents=True, exist_ok=True)

    clean_name = re.sub(r'[^가-힣a-zA-Z0-9_\-\.]', '_', target_name)
    if not clean_name.lower().endswith(('.png', '.jpg', '.jpeg', '.webp')):
        clean_name += ".png"

    dest_path = target_dir / clean_name
    with open(dest_path, "wb") as f:
        f.write(uploaded_file.getbuffer())
    return str(dest_path)


def list_source_box_images(dest_dir: Optional[str] = None) -> list:
    """지정된 소스 보관함 디렉터리에 저장된 모든 이미지 파일 목록 반환"""
    target_dir = Path(dest_dir) if dest_dir else SOURCES_DIR
    exts = {".png", ".jpg", ".jpeg", ".webp"}
    images = []
    if target_dir.exists():
        for f in sorted(target_dir.iterdir(), key=lambda x: x.stat().st_mtime, reverse=True):
            if f.suffix.lower() in exts:
                images.append({
                    "name": f.name,
                    "path": str(f),
                    "size_kb": round(f.stat().st_size / 1024, 1),
                    "mtime": f.stat().st_mtime,
                })
    return images


def search_and_save_vs_images(
    target_name: str,
    max_count: int = 5,
    tag: str = "A",
    dest_dir: Optional[str] = None,
) -> list:
    """
    [핵심 신규 기능] 대상 명칭(예: KF-21, F-16)을 입력받아 네이버/Bing/위키미디어에서
    고화질 대표 실사 사진을 자동으로 검색하고 소스 보관함에 다운로드합니다.
    다운로드된 로컬 파일 경로 리스트를 반환합니다.
    """
    from core.searcher import search_keyword_images, download_image_from_url
    import time

    target_dir = Path(dest_dir) if dest_dir else SOURCES_DIR
    target_dir.mkdir(parents=True, exist_ok=True)

    clean_name = re.sub(r'[^가-힣a-zA-Z0-9]', '_', target_name).strip('_') or f"Target_{tag}"
    search_query = re.sub(r'[_]', ' ', clean_name).strip()

    # 고화질 이미지 검색 쿼리 구성 (외형, 전경 위주)
    items = search_keyword_images(search_query, max_results=max_count * 3, shot_num=1)
    saved_paths = []

    for idx, it in enumerate(items):
        img_url = it.get("image") or it.get("thumbnail")
        if not img_url:
            continue

        ts = int(time.time() * 1000) % 1000000
        filename = f"{clean_name}_{tag}_{idx+1}_{ts}.png"
        save_dest = target_dir / filename

        try:
            ok = download_image_from_url(img_url, str(save_dest), timeout=10)
            if ok and save_dest.exists() and save_dest.stat().st_size > 8000:
                saved_paths.append(str(save_dest))
                if len(saved_paths) >= max_count:
                    break
        except Exception as e:
            print(f"[search_and_save_vs_images] Download error: {e}")
            continue

    # 만약 웹 크롤링이 네트워크 문제로 하나도 안 받아졌을 때 플레이스홀더 비상 생성
    if not saved_paths:
        from core.searcher import create_placeholder_candidate
        fallback_file = str(target_dir / f"{clean_name}_{tag}_fallback.png")
        create_placeholder_candidate(target_name, fallback_file, idx=1)
        if os.path.exists(fallback_file):
            saved_paths.append(fallback_file)

    return saved_paths

