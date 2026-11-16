"""
core/voice_extractor.py
유튜브 채널 또는 영상 주소로부터 깨끗한 나레이터 음성을 초고속(수 초 이내) 추출하고,
Qwen3-TTS 보이스 클로닝용 참조 오디오(WAV)로 변환하는 유틸리티
"""

import json
import os
import re
import subprocess
import tempfile
from pathlib import Path
import yt_dlp
from yt_dlp.utils import download_range_func

from core.ffmpeg_utils import get_ffmpeg_exe


def normalize_youtube_url(url: str) -> str:
    """사용자가 입력한 URL의 프로토콜 누락(www.) 및 채널 URL을 올바른 형식으로 정규화합니다."""
    u = url.strip()
    if not u:
        raise ValueError("유튜브 URL이 입력되지 않았습니다.")

    # http/https 누락 시 추가
    if not u.startswith("http://") and not u.startswith("https://"):
        u = "https://" + u

    # 채널 URL(@ 또는 /channel/)인 경우 영상 목록(/videos)으로 연결하여 최신 영상 자동 탐색 보장
    if "/@" in u or "/channel/" in u or "/c/" in u:
        clean_u = re.sub(r'/(featured|streams|shorts|playlists)?/?$', '', u)
        if not clean_u.endswith("/videos"):
            u = clean_u + "/videos"

    return u


def resolve_youtube_video_info(url_or_channel: str) -> dict:
    """
    유튜브 채널 URL(@채널명) 또는 영상 URL을 분석하여 대상 영상 정보(ID, 제목, URL, 총 길이)를 반환합니다.
    """
    url = normalize_youtube_url(url_or_channel)

    ydl_opts = {
        "quiet": True,
        "no_warnings": True,
        "extract_flat": True,
        "playlist_items": "1",
    }

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=False)

    if not info:
        raise ValueError("유튜브 정보를 불러올 수 없습니다. URL을 확인해 주세요.")

    # 채널/플레이리스트인 경우 첫 번째 영상 선택
    entries = list(info.get("entries", [])) if "entries" in info else []
    if entries and entries[0]:
        first_entry = entries[0]
        vid = first_entry.get("id", "")
        title = first_entry.get("title", "유튜브 영상")
        target_url = f"https://www.youtube.com/watch?v={vid}"
        duration = float(first_entry.get("duration") or 0.0)
    else:
        vid = info.get("id", "")
        title = info.get("title", "유튜브 영상")
        target_url = f"https://www.youtube.com/watch?v={vid}" if vid else url
        duration = float(info.get("duration") or 0.0)

    if not vid:
        # 혹시 vid를 못 구했을 경우 URL에서 11자리 ID 정규식 추출
        m = re.search(r"(?:v=|youtu\.be/|shorts/)([A-Za-z0-9_-]{11})", url)
        if m:
            vid = m.group(1)
            target_url = f"https://www.youtube.com/watch?v={vid}"

    return {
        "video_id": vid,
        "title": title,
        "video_url": target_url,
        "duration": duration,
    }


def extract_voice_clip_from_youtube(
    video_url: str,
    start_sec: float = 15.0,
    duration_sec: float = 8.0,
    output_path: str = None,
    progress_callback = None,
) -> dict:
    """
    유튜브 영상 전체를 받지 않고, 타겟 구간(start_sec ~ start_sec+duration_sec)의
    오디오만 부분 다운로드(download_ranges)하여 2~3초 만에 24kHz 모노 WAV로 초고속 추출합니다.
    """
    if progress_callback:
        progress_callback("🔍 유튜브 영상 정보 및 최신 영상 탐색 중...")

    info_dict = resolve_youtube_video_info(video_url)
    target_url = info_dict["video_url"]
    total_dur = info_dict.get("duration", 0.0)

    # 시작 시간 보정
    if total_dur > 0 and start_sec >= total_dur:
        start_sec = max(5.0, total_dur * 0.1)

    tmp_dir = tempfile.mkdtemp(prefix="yt_voice_")
    raw_audio_tmpl = os.path.join(tmp_dir, "range_audio.%(ext)s")

    ffmpeg_bin = get_ffmpeg_exe()

    # 타겟 구간 앞뒤 3초 버퍼를 두어 부분만 초고속 스트리밍 다운로드
    r_start = max(0.0, start_sec - 3.0)
    r_end = start_sec + duration_sec + 3.0

    ydl_opts = {
        "format": "bestaudio/best",
        "outtmpl": raw_audio_tmpl,
        "download_ranges": download_range_func(None, [(r_start, r_end)]),
        "force_keyframes_at_cuts": False,
        "quiet": True,
        "no_warnings": True,
        "ffmpeg_location": os.path.dirname(ffmpeg_bin) if ffmpeg_bin != "ffmpeg" else None,
    }

    if progress_callback:
        progress_callback(f"📥 {start_sec:.1f}초 지점 음성 스트림 초고속 다운로드 중 (수 초 소요)...")

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        ydl.download([target_url])

    # 다운로드된 파일 탐색
    dl_files = [os.path.join(tmp_dir, f) for f in os.listdir(tmp_dir) if f.startswith("range_audio.")]
    if not dl_files:
        raise FileNotFoundError("오디오 구간 스트림 다운로드에 실패했습니다.")

    downloaded_clip = dl_files[0]

    if progress_callback:
        progress_callback(f"✂️ {duration_sec:.1f}초 분량의 클린 보이스(24kHz 모노 WAV) 정밀 가공 중...")

    if not output_path:
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        clips_dir = os.path.join(base_dir, "voice_profiles", "extracted_clips")
        os.makedirs(clips_dir, exist_ok=True)
        safe_title = re.sub(r'[^\w\-_\.]', '_', info_dict.get("title", "clip"))[:25]
        output_path = os.path.join(clips_dir, f"yt_{safe_title}_{int(start_sec)}s.wav")

    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)

    # 24000Hz 1채널 16-bit PCM 정규화
    # 부분 다운로드된 파일 내에서 실제 start_sec 오프셋 계산
    offset_in_clip = start_sec - r_start
    cmd = [
        ffmpeg_bin, "-y",
        "-ss", f"{offset_in_clip:.2f}",
        "-t", f"{duration_sec:.2f}",
        "-i", downloaded_clip,
        "-ar", "24000",
        "-ac", "1",
        "-c:a", "pcm_s16le",
        output_path,
    ]
    subprocess.run(cmd, capture_output=True, check=True)

    # 추천 대사(자막) 조회 시도 (타임아웃 3초)
    suggested_text = ""
    try:
        sub_opts = {
            "skip_download": True,
            "writeautomaticsub": True,
            "subtitleslangs": ["ko"],
            "quiet": True,
            "no_warnings": True,
        }
        with yt_dlp.YoutubeDL(sub_opts) as sub_ydl:
            sub_info = sub_ydl.extract_info(target_url, download=False)
            captions = sub_info.get("automatic_captions", {}).get("ko", [])
            if captions:
                json3_url = next((c.get("url") for c in captions if c.get("ext") == "json3"), None)
                if json3_url:
                    import urllib.request
                    req = urllib.request.Request(json3_url, headers={"User-Agent": "Mozilla/5.0"})
                    with urllib.request.urlopen(req, timeout=3) as resp:
                        sub_data = json.loads(resp.read().decode("utf-8"))
                        events = sub_data.get("events", [])
                        text_parts = []
                        end_sec = start_sec + duration_sec
                        for ev in events:
                            t_start = ev.get("tStartMs", 0) / 1000.0
                            if start_sec - 1.0 <= t_start <= end_sec + 1.0:
                                segs = ev.get("segs", [])
                                line = "".join([s.get("utf8", "") for s in segs]).strip()
                                if line and line != "\n":
                                    text_parts.append(line)
                        suggested_text = " ".join(text_parts).strip()
    except Exception:
        pass

    return {
        "audio_path": output_path,
        "title": info_dict["title"],
        "video_url": target_url,
        "start_sec": start_sec,
        "duration_sec": duration_sec,
        "suggested_text": suggested_text,
    }
