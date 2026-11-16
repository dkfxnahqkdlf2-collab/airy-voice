"""
core/video_renderer.py
초경량 순수 Python + FFmpeg 기반 쇼츠 원클릭 렌더링 스튜디오
- 생성된 9:16 비디오 클립(.mp4) 다중 파일 순차 결합(Concatenate)
- Edge-TTS 나레이션 음성 + BGM 배경음악 오토 더킹(Ducking, 볼륨 0.15 자동 믹싱)
- 쇼츠 최적화 1줄 볼드 자막(subtitles.ass) 하드섭 번인
- 최종 완성본 final_shorts.mp4 초고속 렌더링
"""

import json
import os
import re
import shutil
import subprocess
from pathlib import Path
from core.ffmpeg_utils import get_ffmpeg_exe


def get_media_duration(file_path: str) -> float:
    """ffmpeg를 사용하여 오디오 또는 비디오 미디어 파일의 실제 재생 시간(초)을 정밀 측정합니다."""
    if not file_path or not os.path.exists(file_path):
        return 0.0
    try:
        ffmpeg_bin = get_ffmpeg_exe()
        cmd = [ffmpeg_bin, "-i", file_path]
        res = subprocess.run(cmd, capture_output=True, encoding="utf-8", errors="replace")
        m = re.search(r"Duration:\s*(\d+):(\d+):(\d+\.\d+)", res.stderr)
        if m:
            h, mn, s = float(m.group(1)), float(m.group(2)), float(m.group(3))
            return round(h * 3600 + mn * 60 + s, 3)
    except Exception as e:
        print(f"[video_renderer] get_media_duration failed for {file_path}: {e}")
    return 0.0


def render_video_clips_with_audio_and_subs(
    output_dir: str,
    video_clip_paths: list[str],
    narration_path: str,
    subtitles_ass_path: str,
    bgm_path: str = None,
    bgm_volume: float = 0.15,
    output_filename: str = "final_shorts.mp4",
    progress_callback = None,
) -> str:
    """
    드래그 앤 드롭으로 업로드된 N개의 비디오 클립(.mp4)들을 순서대로 결합(Concatenate)하고,
    Edge-TTS 나레이션 음성 및 1줄 볼드 자막(ASS), BGM을 얹어 1080x1920 세로 쇼츠 완제품을 렌더링합니다.
    """
    os.makedirs(output_dir, exist_ok=True)
    tmp_dir = os.path.join(output_dir, "_render_clips_tmp")
    os.makedirs(tmp_dir, exist_ok=True)
    final_video_path = os.path.join(output_dir, output_filename)

    valid_clips = [p for p in video_clip_paths if os.path.exists(p) and os.path.getsize(p) > 1000]
    if not valid_clips:
        raise ValueError("유효한 비디오 클립 파일이 업로드되지 않았습니다.")

    if progress_callback:
        progress_callback(10, 100, f"비디오 클립 {len(valid_clips)}개 길이 및 오디오 싱크 분석 중...")

    # 총 오디오 길이 및 총 비디오 길이 측정
    total_audio_dur = get_media_duration(narration_path)
    if total_audio_dur <= 0.1:
        total_audio_dur = 10.0

    total_video_dur = sum(get_media_duration(c) for c in valid_clips)

    # 비디오가 나레이션보다 짧은 경우: 마지막 프레임을 복제 유지(tpad)하여 음성 짤림 방지
    extra_pad_duration = 0.0
    if total_video_dur < total_audio_dur:
        extra_pad_duration = round(total_audio_dur - total_video_dur + 0.3, 2)

    if progress_callback:
        progress_callback(25, 100, f"클립 1080x1920 정규화 및 순차 결합 준비 중... (합산: {total_video_dur:.1f}초)")

    # 1. FFmpeg 인자 구성 (각 클립 1080x1920 30fps 정규화)
    inputs = []
    filter_parts = []
    for i, c_path in enumerate(valid_clips):
        inputs.extend(["-i", c_path])
        filter_parts.append(
            f"[{i}:v]scale=1080:1920:force_original_aspect_ratio=decrease,pad=1080:1920:(ow-iw)/2:(oh-ih)/2,setsar=1,fps=30[v{i}];"
        )

    concat_inputs = "".join(f"[v{i}]" for i in range(len(valid_clips)))
    v_concat_tag = "vconcat"

    # 만약 영상이 오디오보다 짧으면 tpad로 마지막 프레임 홀드
    if extra_pad_duration > 0.05:
        concat_filter = f"{concat_inputs}concat=n={len(valid_clips)}:v=1:a=0[vraw];[vraw]tpad=stop_mode=clone:stop_duration={extra_pad_duration:.2f}[{v_concat_tag}];"
    else:
        concat_filter = f"{concat_inputs}concat=n={len(valid_clips)}:v=1:a=0[{v_concat_tag}];"

    # 2. ASS 자막 번인 필터
    has_subtitles = subtitles_ass_path and os.path.exists(subtitles_ass_path)
    if has_subtitles:
        ass_filter_path = Path(subtitles_ass_path).resolve().as_posix().replace(":", r"\:")
        subtitle_filter = f"[{v_concat_tag}]ass='{ass_filter_path}'[vout]"
    else:
        subtitle_filter = f"[{v_concat_tag}]copy[vout]"

    # 3. BGM 및 나레이션 오디오 믹싱
    has_bgm = bgm_path and os.path.exists(bgm_path) and os.path.getsize(bgm_path) > 1000
    audio_input_idx = len(valid_clips)

    full_filter_complex = "".join(filter_parts) + concat_filter + subtitle_filter

    cmd = [get_ffmpeg_exe(), "-y", *inputs, "-i", narration_path]

    if has_bgm:
        bgm_input_idx = audio_input_idx + 1
        cmd.extend(["-i", bgm_path])
        audio_filter = (
            f";[{audio_input_idx}:a]volume=1.0[voice];"
            f"[{bgm_input_idx}:a]volume={bgm_volume:.2f},aloop=loop=-1:size=2e+09[bgm];"
            f"[voice][bgm]amix=inputs=2:duration=first:dropout_transition=2[aout]"
        )
        full_filter_complex += audio_filter
        cmd.extend([
            "-filter_complex", full_filter_complex,
            "-map", "[vout]",
            "-map", "[aout]",
        ])
    else:
        cmd.extend([
            "-filter_complex", full_filter_complex,
            "-map", "[vout]",
            "-map", f"{audio_input_idx}:a",
        ])

    target_duration = max(total_audio_dur, total_video_dur)
    cmd.extend([
        "-c:v", "libx264",
        "-preset", "veryfast",
        "-pix_fmt", "yuv420p",
        "-c:a", "aac",
        "-b:a", "192k",
        "-t", f"{target_duration:.2f}",
        final_video_path,
    ])

    if progress_callback:
        progress_callback(50, 100, f"FFmpeg 1080x1920 쇼츠 영상 렌더링 중 (목표 길이: {target_duration:.1f}초)...")

    try:
        subprocess.run(cmd, capture_output=True, encoding="utf-8", errors="replace", check=True)
    except subprocess.CalledProcessError as e:
        err_msg = e.stderr[-400:] if e.stderr else str(e)
        raise RuntimeError(f"FFmpeg 비디오 결합 렌더링 실패: {err_msg}") from e

    if progress_callback:
        progress_callback(100, 100, "최종 완성본 final_shorts.mp4 렌더링 완료!")

    shutil.rmtree(tmp_dir, ignore_errors=True)
    return final_video_path


def render_final_shorts_video(
    output_dir: str,
    matched_slot_paths: dict,
    scene_durations: list[float],
    narration_path: str,
    subtitles_ass_path: str,
    bgm_path: str = None,
    bgm_volume: float = 0.15,
    output_filename: str = "final_shorts.mp4",
    progress_callback = None,
) -> str:
    """
    [레거시 이미지 슬라이드쇼 폴백]
    24개 슬롯 이미지 + TTS 나레이션 + BGM(더킹) + ASS 자막을 합성하여 final_shorts.mp4를 렌더링합니다.
    """
    os.makedirs(output_dir, exist_ok=True)
    tmp_render_dir = os.path.join(output_dir, "_render_tmp")
    os.makedirs(tmp_render_dir, exist_ok=True)

    final_video_path = os.path.join(output_dir, output_filename)

    if progress_callback:
        progress_callback(10, 100, "씬별 나레이션 시간에 맞춘 슬롯별 노출 시간 동기화 중...")

    # 1. 24개 슬롯별 지속 시간 계산 및 이미지 경로 수집
    concat_lines = []
    total_expected_duration = 0.0

    for sc_idx in range(1, 9):
        sc_dur = scene_durations[sc_idx - 1] if sc_idx - 1 < len(scene_durations) else 6.0
        shot_dur = round(sc_dur / 3.0, 3)

        for sh_idx in [1, 2, 3]:
            slot_num = (sc_idx - 1) * 3 + sh_idx
            img_path = matched_slot_paths.get(slot_num) or matched_slot_paths.get(str(slot_num))

            if not img_path or not os.path.exists(img_path):
                cand = os.path.join(output_dir, f"{sc_idx}-{sh_idx}.png")
                if os.path.exists(cand):
                    img_path = cand

            if not img_path or not os.path.exists(img_path):
                fallback_cand = os.path.join("captures", "search_cache", f"slot_{slot_num:02d}", "cand_1.png")
                if os.path.exists(fallback_cand):
                    img_path = fallback_cand

            if not img_path or not os.path.exists(img_path):
                from PIL import Image
                dummy_path = os.path.join(tmp_render_dir, f"dummy_{slot_num}.png")
                im = Image.new("RGB", (1080, 1920), color=(20, 30, 45))
                im.save(dummy_path)
                img_path = dummy_path

            abs_img = Path(img_path).resolve().as_posix()
            concat_lines.append(f"file '{abs_img}'")
            concat_lines.append(f"duration {shot_dur}")
            total_expected_duration += shot_dur

    if concat_lines:
        concat_lines.append(concat_lines[-2])

    concat_file_path = os.path.join(tmp_render_dir, "concat_shots.txt")
    with open(concat_file_path, "w", encoding="utf-8") as f:
        f.write("\n".join(concat_lines) + "\n")

    if progress_callback:
        progress_callback(40, 100, "오디오 믹싱 및 ASS 볼드 자막 번인 준비 중...")

    ass_filter_path = Path(subtitles_ass_path).resolve().as_posix().replace(":", r"\:")

    cmd = [
        get_ffmpeg_exe(), "-y",
        "-f", "concat", "-safe", "0", "-i", concat_file_path,
        "-i", narration_path,
    ]

    has_bgm = bgm_path and os.path.exists(bgm_path) and os.path.getsize(bgm_path) > 1000

    if has_bgm:
        cmd.extend(["-i", bgm_path])
        filter_complex = (
            f"[0:v]ass='{ass_filter_path}'[vout];"
            f"[1:a]volume=1.0[voice];"
            f"[2:a]volume={bgm_volume:.2f},aloop=loop=-1:size=2e+09[bgm];"
            f"[voice][bgm]amix=inputs=2:duration=first:dropout_transition=2[aout]"
        )
        cmd.extend([
            "-filter_complex", filter_complex,
            "-map", "[vout]",
            "-map", "[aout]",
        ])
    else:
        cmd.extend([
            "-vf", f"ass='{ass_filter_path}'",
            "-map", "0:v",
            "-map", "1:a",
        ])

    cmd.extend([
        "-fps_mode", "vfr",
        "-c:v", "libx264",
        "-preset", "veryfast",
        "-pix_fmt", "yuv420p",
        "-c:a", "aac",
        "-b:a", "192k",
        "-t", f"{total_expected_duration:.2f}",
        final_video_path,
    ])

    if progress_callback:
        progress_callback(60, 100, "FFmpeg 1080x1920 (9:16) 고화질 쇼츠 영상 렌더링 중...")

    try:
        subprocess.run(cmd, capture_output=True, encoding="utf-8", errors="replace", check=True)
    except subprocess.CalledProcessError as e:
        err_msg = e.stderr[-300:] if e.stderr else str(e)
        raise RuntimeError(f"FFmpeg 쇼츠 렌더링 실패: {err_msg}") from e

    if progress_callback:
        progress_callback(100, 100, "최종 완성본 final_shorts.mp4 렌더링 완료!")

    shutil.rmtree(tmp_render_dir, ignore_errors=True)
    return final_video_path
