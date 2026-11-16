"""
core/cutter.py
- 전체 후보 프레임 풀(Pool) 일괄 캡처 및 로드
- 유연한 번호 유지 저장 규칙 (1-1, 1-3 유지, 건너뛴 슬롯 생략)
- Flow 업로드용 1080x1920 (9:16) 세로 캔버스 자동 변환 (중앙 원본 + 상하 가우시안 블러)
"""
import glob
import json
import os
import re
import shutil
import subprocess
import tempfile

from PIL import Image, ImageEnhance, ImageFilter
import yt_dlp
from core.ffmpeg_utils import get_ffmpeg_exe


def _extract_video_id(url: str) -> str:
    for pattern in [r"(?:v=|youtu\.be/|shorts/)([A-Za-z0-9_-]{11})"]:
        match = re.search(pattern, url)
        if match:
            return match.group(1)
    raise ValueError(f"유튜브 URL에서 video ID를 추출할 수 없습니다: {url}")


def get_video_duration(video_path: str) -> float:
    try:
        r = subprocess.run(
            [get_ffmpeg_exe(), "-i", video_path],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        m = re.search(r"Duration:\s*(\d+):(\d+):([\d.]+)", r.stderr)
        if m:
            return (
                int(m.group(1)) * 3600
                + int(m.group(2)) * 60
                + float(m.group(3))
            )
    except Exception:
        pass
    return 600.0


def extract_candidate_frames_pool(
    youtube_url: str,
    candidates_dir: str = "captures/candidates",
    interval: float = 4.5,
    min_start: float = 10.0,
    max_frames: int = 60,
    progress_callback = None,
) -> list:
    """
    영상에서 4~5초 간격으로 고화질 16:9 무손실 원본 후보 프레임들을 단일 풀(Pool)로 캡처하여 저장합니다.
    """
    os.makedirs(candidates_dir, exist_ok=True)

    # 기존 후보 파일 및 썸네일 정리
    for f in os.listdir(candidates_dir):
        fp = os.path.join(candidates_dir, f)
        if os.path.isfile(fp) and f.endswith((".png", ".jpg")):
            try:
                os.remove(fp)
            except Exception:
                pass
    thumb_dir = os.path.join(candidates_dir, ".thumbs")
    if os.path.exists(thumb_dir):
        try:
            shutil.rmtree(thumb_dir, ignore_errors=True)
        except Exception:
            pass

    tmp_dir = tempfile.mkdtemp()
    tmp_video = os.path.join(tmp_dir, "video.%(ext)s")

    ydl_opts = {
        "format": "bestvideo[height<=1080][ext=mp4]/bestvideo[height<=720][ext=mp4]/bestvideo/best",
        "outtmpl": tmp_video,
        "quiet": True,
        "no_warnings": True,
    }

    if progress_callback:
        progress_callback("📥 영상 다운로드 중...")

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(youtube_url, download=True)
        ext = info.get("ext", "mp4")

    downloaded = os.path.join(tmp_dir, f"video.{ext}")
    if not os.path.exists(downloaded):
        files = [f for f in os.listdir(tmp_dir) if f.startswith("video.")]
        if files:
            downloaded = os.path.join(tmp_dir, files[0])
        else:
            raise FileNotFoundError("다운로드된 영상 파일을 찾을 수 없습니다.")

    duration = get_video_duration(downloaded)

    start_ts = min(min_start, max(3.0, duration * 0.03))
    end_ts = max(start_ts + interval, duration - 3.0)

    timestamps = []
    curr = start_ts
    while curr <= end_ts and len(timestamps) < max_frames:
        timestamps.append(curr)
        curr += interval

    frames = []
    total_ts = len(timestamps)
    for idx, ts in enumerate(timestamps, start=1):
        if progress_callback:
            progress_callback(f"🎞️ 후보 프레임 캡처 중... ({idx}/{total_ts})")

        m = int(ts // 60)
        s = int(ts % 60)
        time_str = f"{m:02d}:{s:02d}"
        fname = f"{idx:04d}_{m:02d}m{s:02d}s.png"
        out_path = os.path.join(candidates_dir, fname)

        cmd = [
            get_ffmpeg_exe(),
            "-y",
            "-ss",
            f"{ts:.2f}",
            "-i",
            downloaded,
            "-vframes",
            "1",
            "-q:v",
            "2",
            out_path,
        ]
        r = subprocess.run(cmd, capture_output=True, text=True)
        if r.returncode == 0 and os.path.exists(out_path):
            frames.append(
                {
                    "id": idx,
                    "path": out_path,
                    "timestamp": ts,
                    "time_str": time_str,
                }
            )

    try:
        shutil.rmtree(tmp_dir, ignore_errors=True)
    except Exception:
        pass

    return frames


def extract_shot_segmented_candidate_pool(
    youtube_url: str,
    candidates_dir: str = "captures/candidates",
    target_scene: int = 1,
    frames_per_shot: int = 10,
    interval_sec: float = 4.5,
    progress_callback = None,
) -> list:
    """
    [요구사항 1.3: 샷 단위 세분화 후보 캡처 - 씬당 총 30장 풀]
    - 씬 통째 캡처 대신, 샷별 시각 키워드에 맞춰 4~5초 간격으로 10장씩 후보를 추출합니다.
      * Shot X-1 후보 10장, Shot X-2 후보 10장, Shot X-3 후보 10장 (총 30장 16:9 무손실 원본 캡처)
    """
    os.makedirs(candidates_dir, exist_ok=True)

    # 기존 후보 파일 및 썸네일 정리
    for f in os.listdir(candidates_dir):
        fp = os.path.join(candidates_dir, f)
        if os.path.isfile(fp) and f.endswith((".png", ".jpg")):
            try:
                os.remove(fp)
            except Exception:
                pass
    thumb_dir = os.path.join(candidates_dir, ".thumbs")
    if os.path.exists(thumb_dir):
        try:
            shutil.rmtree(thumb_dir, ignore_errors=True)
        except Exception:
            pass

    tmp_dir = tempfile.mkdtemp()
    tmp_video = os.path.join(tmp_dir, "video.%(ext)s")

    ydl_opts = {
        "format": "bestvideo[height<=1080][ext=mp4]/bestvideo[height<=720][ext=mp4]/bestvideo/best",
        "outtmpl": tmp_video,
        "quiet": True,
        "no_warnings": True,
    }

    if progress_callback:
        progress_callback("📥 영상 다운로드 중...")

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(youtube_url, download=True)
        ext = info.get("ext", "mp4")

    downloaded = os.path.join(tmp_dir, f"video.{ext}")
    if not os.path.exists(downloaded):
        files = [f for f in os.listdir(tmp_dir) if f.startswith("video.")]
        if files:
            downloaded = os.path.join(tmp_dir, files[0])
        else:
            raise FileNotFoundError("다운로드된 영상 파일을 찾을 수 없습니다.")

    duration = get_video_duration(downloaded)

    # 씬당 30장 (Shot 1: 10장, Shot 2: 10장, Shot 3: 10장)
    # 8개 씬 중 target_scene 위치에 해당하는 구간 산출 (또는 전체 영상에서 균등 분배)
    scene_duration = duration / 8.0
    scene_start = (target_scene - 1) * scene_duration
    shot_duration = scene_duration / 3.0

    frames = []
    global_idx = 1
    total_shots = [1, 2, 3]
    total_count = len(total_shots) * frames_per_shot

    for shot_idx in total_shots:
        shot_start = scene_start + (shot_idx - 1) * shot_duration
        # 4~5초 간격으로 10장 샘플링
        for f_i in range(frames_per_shot):
            ts = shot_start + (f_i * interval_sec)
            if ts >= duration - 2.0:
                ts = max(1.0, duration - 3.0 - (frames_per_shot - f_i) * 1.5)

            if progress_callback:
                progress_callback(
                    f"🎞️ Scene {target_scene} - Shot {target_scene}-{shot_idx} 후보 캡처 중... "
                    f"({global_idx}/{total_count}) [{ts:.1f}s]"
                )

            m = int(ts // 60)
            s = int(ts % 60)
            time_str = f"{m:02d}:{s:02d}"
            fname = f"sc{target_scene}_sh{shot_idx}_{f_i+1:02d}_{m:02d}m{s:02d}s.png"
            out_path = os.path.join(candidates_dir, fname)

            cmd = [
                get_ffmpeg_exe(),
                "-y",
                "-ss",
                f"{ts:.2f}",
                "-i",
                downloaded,
                "-vframes",
                "1",
                "-q:v",
                "2",
                out_path,
            ]
            r = subprocess.run(cmd, capture_output=True, text=True)
            if r.returncode == 0 and os.path.exists(out_path):
                frames.append({
                    "id": global_idx,
                    "path": out_path,
                    "timestamp": ts,
                    "time_str": time_str,
                    "shot_label": f"Shot {target_scene}-{shot_idx}",
                })
            global_idx += 1

    try:
        shutil.rmtree(tmp_dir, ignore_errors=True)
    except Exception:
        pass

    return frames


def load_existing_candidate_pool(candidates_dir: str = "captures/candidates") -> list:
    """
    기존에 캡처된 후보 이미지 파일들을 검색하여 단일 풀(Pool) 리스트로 복원합니다.
    (직하위 파일 및 scene_X/shot_Y 하위 파일 모두 지원)
    """
    files = sorted(glob.glob(os.path.join(candidates_dir, "*.png")))
    if not files:
        files = sorted(glob.glob(os.path.join(candidates_dir, "**/*.png"), recursive=True))

    pool = []
    for idx, fp in enumerate(files, start=1):
        fname = os.path.basename(fp)
        tm = re.search(r"(\d+)m(\d+)s", fname)
        t_str = f"{int(tm.group(1)):02d}:{int(tm.group(2)):02d}" if tm else f"#{idx:02d}"
        pool.append({
            "id": idx,
            "path": fp,
            "time_str": t_str,
        })
    return pool


def convert_to_vertical_9_16(
    src_path: str,
    dst_path: str,
    target_size: tuple = (1080, 1920),
    mode: str = "crop",  # "crop" (Center Crop Fill), "pad_black", "pad_white", "blur"
    pad_color: tuple = (0, 0, 0),
    blur_radius: int = 30,
    dim_factor: float = 0.8,
) -> str:
    """
    Flow 영상 AI 업로드용 9:16 (1080x1920) 세로 규격 변환.
    - mode="crop" (기본 추천): Center Crop (Fill).
      여백을 만들지 않고 원본 비율을 유지하며 1080x1920 세로 프레임에 꽉 차도록 확대한 뒤 중앙을 크롭.
      (블러 영역을 구름/연기/노이즈로 오인하여 피사체 형태를 왜곡하는 Flow AI 문제 원천 방지)
    - mode="pad" / "pad_black" / "pad_white": Fit + 단색 패딩 (여백 유지 옵션).
      크롭 없이 원본 전체를 보여주며, 가우시안 블러 대신 순수 블랙(#000000) 또는 순수 화이트(#FFFFFF) 단색 여백 채움.
    - mode="blur": 레거시 가우시안 블러 배경 (비추천).
    """
    with Image.open(src_path) as orig:
        orig = orig.convert("RGB")
        tw, th = target_size
        ow, oh = orig.size

        # 이미 정확히 9:16 비율이거나 오차가 극히 미세한 경우
        if abs((ow / oh) - (tw / th)) < 0.005:
            res = orig.resize(target_size, Image.Resampling.LANCZOS)
            dst_dir = os.path.dirname(dst_path)
            if dst_dir:
                os.makedirs(dst_dir, exist_ok=True)
            res.save(dst_path, format="PNG")
            return dst_path

        if mode == "crop":
            # 1. Center Crop (Fill) - 기본 추천 (여백 없이 1080x1920 꽉 채움)
            scale = max(tw / ow, th / oh)
            nw = int(round(ow * scale))
            nh = int(round(oh * scale))
            resized = orig.resize((nw, nh), Image.Resampling.LANCZOS)

            crop_x = max(0, (nw - tw) // 2)
            crop_y = max(0, (nh - th) // 2)
            final_img = resized.crop((crop_x, crop_y, crop_x + tw, crop_y + th))

            if final_img.size != target_size:
                final_img = final_img.resize(target_size, Image.Resampling.LANCZOS)

        elif mode in ("pad", "pad_black", "pad_white", "pad_transparent"):
            # 2. 패딩 (Fit) - 여백 유지 옵션 (블러 노이즈 왜곡 차단, Flow AI 최적 규격)
            scale = min(tw / ow, th / oh)
            fw = int(round(ow * scale))
            fh = int(round(oh * scale))
            paste_x = (tw - fw) // 2
            paste_y = (th - fh) // 2

            if mode == "pad_transparent":
                final_img = Image.new("RGBA", target_size, (255, 255, 255, 0))
                fg = orig.convert("RGBA").resize((fw, fh), Image.Resampling.LANCZOS)
                final_img.paste(fg, (paste_x, paste_y), fg)
            else:
                bg_color = (255, 255, 255) if (mode == "pad_white" or pad_color == (255, 255, 255)) else (0, 0, 0)
                final_img = Image.new("RGB", target_size, bg_color)
                fg = orig.convert("RGB").resize((fw, fh), Image.Resampling.LANCZOS)
                final_img.paste(fg, (paste_x, paste_y))

        elif mode == "blur":
            # 3. 레거시 가우시안 블러 배경
            scale_bg = max(tw / ow, th / oh)
            bw = int(round(ow * scale_bg))
            bh = int(round(oh * scale_bg))
            bg = orig.resize((bw, bh), Image.Resampling.BILINEAR)

            crop_x = (bw - tw) // 2
            crop_y = (bh - th) // 2
            bg = bg.crop((crop_x, crop_y, crop_x + tw, crop_y + th))

            if blur_radius > 0:
                bg = bg.filter(ImageFilter.GaussianBlur(radius=blur_radius))

            if dim_factor < 1.0:
                enhancer = ImageEnhance.Brightness(bg)
                bg = enhancer.enhance(dim_factor)

            scale_fg = min(tw / ow, th / oh)
            fw = int(round(ow * scale_fg))
            fh = int(round(oh * scale_fg))
            fg = orig.resize((fw, fh), Image.Resampling.LANCZOS)

            paste_x = (tw - fw) // 2
            paste_y = (th - fh) // 2
            bg.paste(fg, (paste_x, paste_y))
            final_img = bg
        else:
            # 폴백: Center Crop
            scale = max(tw / ow, th / oh)
            nw = int(round(ow * scale))
            nh = int(round(oh * scale))
            resized = orig.resize((nw, nh), Image.Resampling.LANCZOS)
            crop_x = max(0, (nw - tw) // 2)
            crop_y = max(0, (nh - th) // 2)
            final_img = resized.crop((crop_x, crop_y, crop_x + tw, crop_y + th))

        dst_dir = os.path.dirname(dst_path)
        if dst_dir:
            os.makedirs(dst_dir, exist_ok=True)
        final_img.save(dst_path, format="PNG")

    # 결과 파일 전수 검증: 반드시 (1080, 1920)이어야 함
    try:
        with Image.open(dst_path) as verify_img:
            if verify_img.size != target_size:
                corrected = verify_img.resize(target_size, Image.Resampling.LANCZOS)
                corrected.save(dst_path, format="PNG")
    except Exception:
        pass

    return dst_path


def ensure_all_vertical(output_dir: str = "captures", mode: str = "crop") -> list:
    """
    output_dir 내의 모든 'X-Y.png' 파일들을 전수 조사하여,
    1080x1920 세로형 규격이 아닌 파일들을 모두 1080x1920 (9:16)으로 강제 변환합니다.
    """
    fixed = []
    pattern = os.path.join(output_dir, "*-*.png")
    for fp in sorted(glob.glob(pattern)):
        try:
            with Image.open(fp) as im:
                if im.size != (1080, 1920):
                    convert_to_vertical_9_16(fp, fp, mode=mode)
                    fixed.append(fp)
        except Exception:
            pass
    return fixed


def save_slot_matched_shots(
    slot_assignments: dict,
    output_dir: str = "captures",
    raw_dir: str = "captures/raw",
    mode: str = "crop",
) -> dict:
    """
    [유연한 번호 유지 저장 규칙]
    - 특정 샷(예: Shot 1-2)에서 '없음'으로 건너뛰고 다음 샷(Shot 1-3)을 선택하면:
      다음 선택된 이미지는 앞 번호로 당겨지지 않고 본래 슬롯인 'captures/1-3.png'로 정확히 매칭되어 저장됩니다.
    - 건너뛴 슬롯(1-2)은 파일 저장을 생략하며, 기존에 남아있던 과거 잔여 파일도 깔끔히 제거하여 슬롯을 비워둡니다.
    - 저장되는 이미지는 누락 없이 100% 1080x1920 (9:16) 세로 캔버스(Center Crop Fill 또는 단색 패딩)로 변환 전수 보장됩니다.

    slot_assignments: {(scene_num, shot_num): "path_to_image" or None}
    mode: "crop" (기본/추천 - Center Crop Fill) | "pad_black" | "pad_white" | "blur"
    Returns:
        {
            "saved": [{"scene": 1, "shot": 1, "path": "captures/1-1.png"}, ...],
            "skipped": [{"scene": 1, "shot": 2}, ...]
        }
    """
    os.makedirs(output_dir, exist_ok=True)
    os.makedirs(raw_dir, exist_ok=True)
    thumb_dir = os.path.join(output_dir, ".thumbs")
    os.makedirs(thumb_dir, exist_ok=True)

    saved = []
    skipped = []

    for key, img_path in sorted(
        slot_assignments.items(),
        key=lambda item: item[0] if isinstance(item[0], int) else (item[0][0] - 1) * 3 + item[0][1],
    ):
        if isinstance(key, int):
            slot_num = key
            sc_num = ((slot_num - 1) // 3) + 1
            shot_num = ((slot_num - 1) % 3) + 1
        else:
            sc_num, shot_num = key
            slot_num = (sc_num - 1) * 3 + shot_num

        fname = f"{sc_num}-{shot_num}.png"
        final_dst = os.path.join(output_dir, fname)
        raw_dst = os.path.join(raw_dir, fname)
        thumb_dst = os.path.join(thumb_dir, f"{sc_num}-{shot_num}_thumb.jpg")

        if img_path and os.path.exists(img_path):
            # 재변환 시 원본 raw_dst가 존재하면 uncropped 원본을 사용하여 화질 저하 및 이중 크롭 방지
            source_img = raw_dst if (img_path == final_dst and os.path.exists(raw_dst)) else img_path

            # 원본 백업
            if source_img != raw_dst and os.path.exists(source_img):
                shutil.copy2(source_img, raw_dst)

            # Flow 9:16 (1080x1920) 규격 변환 최종 저장 (지정된 mode 적용)
            convert_to_vertical_9_16(source_img, final_dst, mode=mode)

            # 전수 보장 확인
            with Image.open(final_dst) as chk:
                if chk.size != (1080, 1920):
                    convert_to_vertical_9_16(final_dst, final_dst, mode=mode)

            # 기존 구버전 썸네일 파일 제거 (새 썸네일로 즉시 재생성 보장)
            if os.path.exists(thumb_dst):
                try:
                    os.remove(thumb_dst)
                except Exception:
                    pass

            saved.append({
                "scene": sc_num,
                "shot": shot_num,
                "slot_num": slot_num,
                "path": final_dst,
                "slot": f"{sc_num}-{shot_num}",
            })
        else:
            # [핵심 버그 픽스]: 건너뛴 슬롯에 과거 잔여 가로 16:9 파일 및 썸네일이 남아있지 않도록 제거
            if os.path.exists(final_dst):
                try:
                    os.remove(final_dst)
                except Exception:
                    pass
            if os.path.exists(thumb_dst):
                try:
                    os.remove(thumb_dst)
                except Exception:
                    pass
            if os.path.exists(raw_dst):
                try:
                    os.remove(raw_dst)
                except Exception:
                    pass

            skipped.append({
                "scene": sc_num,
                "shot": shot_num,
                "slot_num": slot_num,
                "slot": f"{sc_num}-{shot_num}",
            })

    # 전체 폴더 9:16 규격 최종 전수 보정
    ensure_all_vertical(output_dir, mode=mode)

    return {
        "saved": saved,
        "skipped": skipped,
    }

