"""
core/tts_engine.py
쇼츠 전용 초고음질 TTS 음성 생성 및 자막 동기화 엔진
- Edge-TTS를 활용하여 한국어 쇼츠 특화 보이스(인준/선희/현수) 1.2배속 음성 초고속 합성
- 씬별(Scene 1~8) 실제 음성 재생 시간(초) 정밀 측정
- 유튜브 쇼츠(1080x1920) 전용 1줄 8~15자 어절 분할 및 자막-음성 0.1초 싱크 매칭
- 볼드 화이트 + 5px 블랙 외곽선 ASS 자막 파일(.ass) 자동 생성
"""

import asyncio
import json
import math
import os
import re
import subprocess
import sys
from pathlib import Path
from core.ffmpeg_utils import get_ffmpeg_exe

# Windows 콘솔 인코딩(CP949) 충돌 방지: 입출력을 UTF-8로 강제 재구성
if sys.platform == "win32":
    try:
        if sys.stdout and hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        if sys.stderr and hasattr(sys.stderr, "reconfigure"):
            sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

try:
    import edge_tts
    HAS_EDGE_TTS = True
except ImportError:
    HAS_EDGE_TTS = False

VOICE_CHOICES_KO = {
    "ko-KR-InJoonNeural": "🔥 인준 (박진감 쇼츠 남성 - 한국어 추천)",
    "ko-KR-SunHiNeural": "✨ 선희 (몰입감 쇼츠 여성)",
    "ko-KR-HyunsuNeural": "🎙️ 현수 (차분한 다큐 남성)",
}

VOICE_CHOICES_EN = {
    "en-US-ChristopherNeural": "🇺🇸 Christopher (묵직하고 웅장한 해외 밀리터리 쇼츠 1위 남성 성우 / 강력 추천)",
    "en-US-GuyNeural": "🇺🇸 Guy (빠르고 박진감 넘치는 액션·다큐 남성 성우)",
    "en-US-JennyNeural": "🇺🇸 Jenny (또렷하고 신뢰감 넘치는 미국 여성 성우)",
    "en-US-EricNeural": "🇺🇸 Eric (차분하고 정밀한 밀리터리 해설 남성 성우)",
}

VOICE_CHOICES = {**VOICE_CHOICES_KO, **VOICE_CHOICES_EN}


def detect_script_language(text: str) -> str:
    """대본의 주 언어가 한국어인지 영어인지 자동 판별합니다."""
    if not text:
        return "Korean"
    hangul_count = len(re.findall(r'[\uac00-\ud7a3]', text))
    english_count = len(re.findall(r'[a-zA-Z]', text))
    if english_count > 15 and english_count > hangul_count * 1.5:
        return "English"
    return "Korean"

QWEN_SPEAKERS = {
    "Sohee": "🇰🇷 소희 (한국어 여성 - 자연스럽고 또렷한 전달력)",
    "Aiden": "🎙️ 에이든 (중저음 남성 - 신뢰감 있는 나레이션)",
    "Dylan": "🔥 딜런 (차분하고 묵직한 다큐 남성)",
    "Uncle_Fu": "🧙 푸 아저씨 (깊이 있는 중후한 원숙미)",
    "Vivian": "✨ 비비안 (밝고 지적인 여성)",
    "Serena": "💫 세레나 (차분하고 감성적인 여성)",
}

QWEN_MODELS = {
    "0.6B": "⚡ Qwen3-TTS 0.6B (초고속 / VRAM 1.2GB - 권장)",
    "1.7B": "🔥 Qwen3-TTS 1.7B (최고음질 / 정밀 표현)",
}


def get_qwen_python_path() -> str:
    """Qwen 전용 가상환경(.venv_qwen)의 Python 실행 파일 경로를 반환합니다."""
    candidates = [
        os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".venv_qwen", "Scripts", "python.exe")),
        os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".venv_qwen", "bin", "python")),
    ]
    for c in candidates:
        if os.path.exists(c):
            return c
    return sys.executable


def is_qwen_available() -> bool:
    """Qwen3-TTS 가상환경이 설치되어 사용할 수 있는지 확인합니다."""
    py_path = get_qwen_python_path()
    if not os.path.exists(py_path):
        return False
    worker_path = os.path.join(os.path.dirname(__file__), "qwen_tts_worker.py")
    return os.path.exists(worker_path)


VOICE_PROFILES_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "voice_profiles"))


def get_pinned_voice() -> dict:
    """영구 고정된 대표 복제 음성 프로필 정보를 반환합니다."""
    os.makedirs(VOICE_PROFILES_DIR, exist_ok=True)
    meta_p = os.path.join(VOICE_PROFILES_DIR, "pinned_voice_meta.json")
    if os.path.exists(meta_p):
        try:
            with open(meta_p, "r", encoding="utf-8") as f:
                meta = json.load(f)
            audio_p = meta.get("audio_path", "")
            if audio_p and os.path.exists(audio_p):
                return meta
        except Exception:
            pass

    # 폴백: pinned_voice.wav 또는 .mp3 탐색
    for ext in [".wav", ".mp3", ".m4a"]:
        default_file = os.path.join(VOICE_PROFILES_DIR, f"pinned_voice{ext}")
        if os.path.exists(default_file):
            return {
                "name": "내 대표 메인 보이스",
                "audio_path": default_file,
                "ref_text": "",
            }
    return {}


def has_cached_voice_dna() -> bool:
    """고정된 대표 보이스의 목소리 DNA 텐서(.prompt.pt)가 캐싱되어 있는지 확인합니다."""
    if not os.path.exists(VOICE_PROFILES_DIR):
        return False
    return any(f.endswith(".prompt.pt") for f in os.listdir(VOICE_PROFILES_DIR))


def save_pinned_voice(audio_bytes: bytes, filename: str, voice_name: str = "내 대표 메인 보이스", ref_text: str = "") -> dict:
    """사용자가 업로드하거나 유튜브에서 추출한 참조 음성을 voice_profiles에 대표 메인 보이스로 영구 고정 저장합니다."""
    os.makedirs(VOICE_PROFILES_DIR, exist_ok=True)

    # 이전 캐시 파일(.prompt.pt) 정리 (새 음성이 들어왔으므로 깨끗이 갱신)
    try:
        for f in os.listdir(VOICE_PROFILES_DIR):
            if f.endswith(".prompt.pt"):
                os.remove(os.path.join(VOICE_PROFILES_DIR, f))
    except Exception:
        pass

    ext = os.path.splitext(filename)[1].lower() or ".wav"
    save_path = os.path.join(VOICE_PROFILES_DIR, f"pinned_voice{ext}")
    with open(save_path, "wb") as f:
        f.write(audio_bytes)

    meta = {
        "name": voice_name.strip() or "내 대표 메인 보이스",
        "audio_path": save_path,
        "filename": filename,
        "ref_text": ref_text.strip(),
        "pinned": True,
    }
    meta_p = os.path.join(VOICE_PROFILES_DIR, "pinned_voice_meta.json")
    with open(meta_p, "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)
    return meta


def save_pinned_voice_from_file(source_file_path: str, voice_name: str = "내 대표 메인 보이스", ref_text: str = "") -> dict:
    """로컬 파일 경로로부터 대표 메인 보이스를 영구 고정 저장합니다."""
    if not os.path.exists(source_file_path):
        raise FileNotFoundError(f"원본 음성 파일을 찾을 수 없습니다: {source_file_path}")
    with open(source_file_path, "rb") as f:
        b = f.read()
    return save_pinned_voice(b, os.path.basename(source_file_path), voice_name=voice_name, ref_text=ref_text)



def get_audio_duration(file_path: str) -> float:
    """ffmpeg를 사용하여 오디오 파일의 실제 재생 시간(초)을 정밀 측정합니다."""
    if not os.path.exists(file_path):
        return 0.0
    try:
        ffmpeg_bin = get_ffmpeg_exe()
        cmd = [ffmpeg_bin, "-i", file_path]
        res = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
        m = re.search(r"Duration:\s*(\d+):(\d+):(\d+\.\d+)", res.stderr)
        if m:
            h, mn, s = float(m.group(1)), float(m.group(2)), float(m.group(3))
            return round(h * 3600 + mn * 60 + s, 3)
    except Exception as e:
        print(f"[tts_engine] get_audio_duration failed: {e}")
    return 6.0


def split_subtitles_for_shorts(
    raw_items: list[dict],
    max_one_line: int = 16,
    target_chunk_max: int = 15,
) -> list[dict]:
    """
    유튜브 쇼츠(1080x1920)에 최적화된 1줄 자막 분할 알고리즘.
    - 16자 이하의 짧은 문장은 그대로 1줄 단일 팝업 유지.
    - 17자 이상의 긴 문장은 한국어 의미 단위(어절)로 8~15자 내외의 1줄 청크로 균형 분할.
    - 글자(음절) 수에 비례하여 start~end 시간을 정밀 배분.
    """
    result: list[dict] = []

    def _split_single_text(text: str) -> list[str]:
        cleaned = text.strip()
        if not cleaned:
            return []

        # 영문 여부 자동 감지: 알파벳이 한글보다 많을 경우 영문 기준 길이 적용
        en_c = len(re.findall(r'[a-zA-Z]', cleaned))
        ko_c = len(re.findall(r'[\uac00-\ud7a3]', cleaned))
        is_en = (en_c > ko_c * 1.5) and (en_c >= 10)

        cur_max_line = 38 if is_en else max_one_line
        cur_target_chunk = 30 if is_en else target_chunk_max
        min_curr_len = 12 if is_en else 8

        if len(cleaned) <= cur_max_line:
            return [cleaned]

        words = cleaned.split()
        total_len = len(cleaned)
        k = max(2, math.ceil(total_len / cur_target_chunk))
        ideal_len = total_len / k

        chunks: list[str] = []
        curr_words: list[str] = []
        curr_len = 0

        for i, w in enumerate(words):
            remaining_words = len(words) - i
            remaining_slots = k - len(chunks)
            cand_len = len(w) if not curr_words else curr_len + 1 + len(w)

            # 남은 단어 수와 슬롯 수가 같으면 강제 분할
            if remaining_slots > 1 and remaining_words <= remaining_slots - 1:
                if curr_words:
                    chunks.append(" ".join(curr_words))
                    curr_words = []
                    curr_len = 0
                    cand_len = len(w)

            # 균형 분할 판단
            if curr_words and remaining_slots > 1:
                diff_current = abs(curr_len - ideal_len)
                diff_next = abs(cand_len - ideal_len)
                if cand_len > cur_target_chunk or (diff_current <= diff_next and curr_len >= min_curr_len):
                    chunks.append(" ".join(curr_words))
                    curr_words = [w]
                    curr_len = len(w)
                    continue

            curr_words.append(w)
            curr_len = cand_len

        if curr_words:
            tail_limit = 42 if is_en else 18
            tail_word_limit = 8 if is_en else 4
            if chunks and len(" ".join(curr_words)) <= tail_word_limit and (len(chunks[-1]) + 1 + len(" ".join(curr_words))) <= tail_limit:
                chunks[-1] = chunks[-1] + " " + " ".join(curr_words)
            else:
                chunks.append(" ".join(curr_words))

        return chunks

    for item in raw_items:
        txt = str(item.get("text", "")).strip()
        start = float(item.get("start", 0.0))
        end = float(item.get("end", 0.0))
        dur = max(0.1, end - start)

        chunks = _split_single_text(txt)
        if not chunks:
            continue

        if len(chunks) == 1:
            result.append({"text": chunks[0], "start": round(start, 3), "end": round(end, 3)})
            continue

        # 글자 수(공백 제외) 비례 시간 배분
        total_chars = sum(max(1, len(re.sub(r"\s+", "", c))) for c in chunks)
        curr_t = start
        for c in chunks:
            c_chars = max(1, len(re.sub(r"\s+", "", c)))
            c_dur = dur * (c_chars / total_chars)
            c_end = curr_t + c_dur
            result.append({"text": c, "start": round(curr_t, 3), "end": round(c_end, 3)})
            curr_t = c_end

    return result


def _format_ass_time(seconds: float) -> str:
    """초 단위를 ASS 자막 시간 포맷 (H:MM:SS.cs)으로 변환"""
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    centis = int(round((seconds - int(seconds)) * 100))
    if centis >= 100:
        centis = 99
    return f"{hours}:{minutes:02d}:{secs:02d}.{centis:02d}"


def generate_ass_subtitles(
    subtitles: list[dict],
    output_path: str,
    title: str = "",
) -> str:
    """
    쇼츠 모바일 화면(1080x1920)에 최적화된 ASS 자막 파일을 생성합니다.
    - 하단 마진 260px (유튜브 쇼츠 UI 겹침 방지)
    - 58pt 볼드 화이트 + 5px 순수 블랙 외곽선
    - 0~2초 오프닝 타이틀 스타일 지원
    """
    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)

    ass_content = [
        "[Script Info]",
        "ScriptType: v4.00+",
        "PlayResX: 1080",
        "PlayResY: 1920",
        "ScaledBorderAndShadow: yes",
        "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding",
        "Style: ShortsSubtitle,Malgun Gothic,58,&H00FFFFFF,&H000000FF,&H00000000,&H80000000,-1,0,0,0,100,100,0,0,1,5,2,2,60,60,260,1",
        "Style: ShortsTitle,Malgun Gothic,72,&H0000FFFF,&H000000FF,&H00000000,&HA0000000,-1,0,0,0,100,100,0,0,1,6,3,8,80,80,320,1",
        "",
        "[Events]",
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
    ]

    # 0~2초 오프닝 타이틀 팝업
    if title and title.strip():
        t_clean = title.strip().replace("\n", "\\N")
        ass_content.append(f"Dialogue: 1,0:00:00.00,0:00:02.20,ShortsTitle,,0,0,0,,{t_clean}")

    for sub in subtitles:
        st = _format_ass_time(sub["start"])
        et = _format_ass_time(sub["end"])
        text = sub["text"].replace("\n", "\\N")
        ass_content.append(f"Dialogue: 0,{st},{et},ShortsSubtitle,,0,0,0,,{text}")

    with open(output_path, "w", encoding="utf-8") as f:
        f.write("\n".join(ass_content))

    return output_path


def _format_srt_time(seconds: float) -> str:
    """초 단위를 SRT 표준 자막 시간 포맷 (HH:MM:SS,mmm)으로 변환"""
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    millis = int(round((seconds - int(seconds)) * 1000))
    if millis >= 1000:
        millis = 999
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"


def generate_srt_subtitles(
    subtitles: list[dict],
    output_path: str,
) -> str:
    """
    캡컷(CapCut) 및 프리미어 프로 100% 호환 표준 SRT 자막 파일을 생성합니다.
    - UTF-8 인코딩 (한글 깨짐 방지)
    - 00:00:00,000 포맷
    """
    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
    srt_blocks = []
    for idx, sub in enumerate(subtitles, start=1):
        st = _format_srt_time(sub["start"])
        et = _format_srt_time(sub["end"])
        text = sub["text"].strip().replace("\n", " ")
        srt_blocks.append(f"{idx}\n{st} --> {et}\n{text}\n")

    with open(output_path, "w", encoding="utf-8") as f:
        f.write("\n".join(srt_blocks))

    return output_path



async def _synthesize_edge_tts_async(text: str, output_file: str, voice: str, rate: str):
    """비동기 edge-tts 호출"""
    comm = edge_tts.Communicate(text, voice, rate=rate)
    await comm.save(output_file)


def synthesize_scene_audio(text: str, output_file: str, voice: str = "ko-KR-InJoonNeural", rate: str = "+20%") -> float:
    """단일 씬 나레이션 음성을 생성하고 실제 재생 시간(초)을 반환합니다."""
    os.makedirs(os.path.dirname(os.path.abspath(output_file)), exist_ok=True)
    clean_text = re.sub(r'\[Scene\s*\d+\]', '', text).strip()
    if not clean_text:
        clean_text = "이 장면의 내용을 확인하세요."

    # Edge-TTS 호출
    try:
        asyncio.run(_synthesize_edge_tts_async(clean_text, output_file, voice, rate))
    except Exception as e:
        print(f"[tts_engine] Edge-TTS error ({output_file}): {e}")
        # 오류 시 ffmpeg 무음 파일 생성 폴백
        ffmpeg_bin = get_ffmpeg_exe()
        subprocess.run(
            [ffmpeg_bin, "-y", "-f", "lavfi", "-i", "anullsrc=r=44100:cl=mono", "-t", "5.0", "-q:a", "9", "-acodec", "libmp3lame", output_file],
            capture_output=True,
        )

    return get_audio_duration(output_file)


def synthesize_qwen_tts_batch(
    scenes: list[str],
    output_dir: str,
    mode: str = "custom_voice",
    model_size: str = "0.6B",
    speaker: str = "Sohee",
    instruct: str = "",
    ref_audio_path: str = "",
    ref_text: str = "",
    language: str = "Korean",
    progress_callback = None,
) -> list[dict]:
    """
    Qwen3-TTS 전용 가상환경(.venv_qwen)의 worker 스크립트를 호출하여
    씬별 고품질 AI 음성 합성을 수행하고 메타데이터를 반환합니다.
    """
    os.makedirs(output_dir, exist_ok=True)
    tts_dir = os.path.join(output_dir, "tts")
    os.makedirs(tts_dir, exist_ok=True)

    scenes_json_path = os.path.join(tts_dir, "scenes_input.json")
    with open(scenes_json_path, "w", encoding="utf-8") as f:
        json.dump(scenes, f, ensure_ascii=False, indent=2)

    venv_py = get_qwen_python_path()
    worker_script = os.path.abspath(os.path.join(os.path.dirname(__file__), "qwen_tts_worker.py"))

    model_id = f"Qwen/Qwen3-TTS-12Hz-{model_size}-Base" if mode == "voice_clone" else f"Qwen/Qwen3-TTS-12Hz-{model_size}-CustomVoice"

    cmd = [
        venv_py,
        worker_script,
        "--scenes_json", scenes_json_path,
        "--output_dir", tts_dir,
        "--mode", mode,
        "--model_id", model_id,
        "--speaker", speaker,
        "--instruct", instruct or "",
        "--ref_audio", ref_audio_path or "",
        "--ref_text", ref_text or "",
        "--language", language or "Korean",
        "--device", "auto",
    ]

    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"
    env["HF_HUB_DISABLE_SYMLINKS"] = "1"
    env["HF_HUB_DISABLE_SYMLINKS_WARNING"] = "1"

    total_scenes = len(scenes)
    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        bufsize=1,
        env=env,
    )

    for line in iter(proc.stdout.readline, ""):
        line_s = line.strip()
        if not line_s:
            continue
        try:
            print(f"[qwen_tts_engine] {line_s}")
        except Exception:
            pass

        if progress_callback:
            if "[MODEL] Loading weights" in line_s:
                progress_callback(0, total_scenes, f"Qwen3-TTS ({model_size}) AI 모델 가중치 로드 중...")
            elif "[CLONE_CACHE] ⚡" in line_s or "복제 연산 0초 생략" in line_s:
                progress_callback(0, total_scenes, "⚡ 저장된 목소리 DNA 텐서(.pt) 즉시 로드 (복제 연산 0초 생략)...")
            elif "[CLONE] Creating voice clone prompt" in line_s:
                progress_callback(0, total_scenes, "참조 오디오에서 목소리 음색(Voiceprint) 분석 및 복제 중...")
            elif "[PROGRESS] Scene" in line_s:
                m = re.search(r"Scene\s*(\d+)/(\d+)\s*completed\s*in\s*[\d\.]+s\s*\(duration:\s*([\d\.]+)s\)", line_s)
                if m:
                    cur_sc, tot_sc, dur_sc = int(m.group(1)), int(m.group(2)), float(m.group(3))
                    progress_callback(cur_sc, tot_sc, f"Qwen3-TTS: Scene {cur_sc}/{tot_sc} 생성 완료 ({dur_sc:.1f}초)")
            elif "[SCENE" in line_s:
                m_sc = re.search(r"\[SCENE\s*(\d+)/(\d+)\]", line_s)
                if m_sc:
                    cur_sc, tot_sc = int(m_sc.group(1)), int(m_sc.group(2))
                    progress_callback(cur_sc - 1, tot_sc, f"Qwen3-TTS: Scene {cur_sc}/{tot_sc} AI 음성 합성 중...")

    ret_code = proc.wait()
    if ret_code != 0:
        raise RuntimeError(f"Qwen3-TTS 워커 프로세스가 비정상 종료되었습니다 (Exit Code: {ret_code})")

    meta_path = os.path.join(tts_dir, "meta.json")
    if not os.path.exists(meta_path):
        raise FileNotFoundError(f"Qwen3-TTS 출력 메타 파일이 생성되지 않았습니다: {meta_path}")

    with open(meta_path, "r", encoding="utf-8") as f:
        meta = json.load(f)

    return meta.get("scenes", [])


def analyze_audio_silence_boundaries(audio_path: str, ffmpeg_bin: str = "") -> dict:
    """
    FFmpeg silencedetect 필터를 사용하여 오디오의 선행 무음(leading)과 후행 무음(trailing)을 밀리초 단위로 측정.
    (nam-ai-trend/17_long_auto의 audio-analysis.ts 원리 적용)
    """
    if not ffmpeg_bin:
        ffmpeg_bin = get_ffmpeg_exe()

    total_dur = get_audio_duration(audio_path)
    if total_dur <= 0.1:
        return {"duration": 0.0, "leading": 0.0, "trailing": 0.0}

    cmd = [
        ffmpeg_bin, "-hide_banner", "-i", audio_path,
        "-af", "silencedetect=noise=-32dB:d=0.08",
        "-f", "null", "-"
    ]
    res = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    stderr = res.stderr or ""

    starts = [float(m.group(1)) for m in re.finditer(r"silence_start:\s*([0-9.]+)", stderr)]
    ends = [float(m.group(1)) for m in re.finditer(r"silence_end:\s*([0-9.]+)", stderr)]

    leading = 0.0
    trailing = 0.0

    if starts and starts[0] <= 0.03 and ends:
        leading = ends[0]

    for s, e in zip(starts, ends):
        if abs(e - total_dur) <= 0.08:
            trailing = max(0.0, total_dur - s)
            break
    if starts and not ends:
        trailing = max(0.0, total_dur - starts[-1])

    return {
        "duration": round(total_dur, 3),
        "leading": round(leading, 3),
        "trailing": round(trailing, 3),
    }


def apply_shorts_voice_mastering(
    input_path: str,
    output_path: str,
    silence_compress: bool = True,
    target_tempo: float = 1.15,
    pitch_semitones: float = -0.9,
    compressor_gain_db: float = 3.5,
    target_lufs: float = -14.0,
    ffmpeg_bin: str = "",
) -> str:
    """
    유튜브 쇼츠 전용 오디오 마스터링 후처리:
    1. 무음 구간 자동 압축 (0.3초 이상 공백을 0.12초 이내로 트리밍)
    2. 재생 속도 1.15배속 (음높이 왜곡 없이 템포 업)
    3. 피치 -0.8 ~ -1.0 반음 하향 조정 (묵직한 중저음 보정)
    4. 다이나믹 컴프레서 및 -14 LUFS 노멀라이즈 (+3.5dB 게인으로 펀치감 20% 보강)
    """
    if not ffmpeg_bin:
        ffmpeg_bin = get_ffmpeg_exe()

    if not os.path.exists(input_path):
        return input_path

    # 입력 오디오 샘플레이트 감지
    sr = 44100
    try:
        probe_cmd = [ffmpeg_bin, "-i", input_path]
        res = subprocess.run(probe_cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
        m = re.search(r"(\d{4,5})\s*Hz", res.stderr)
        if m:
            sr = int(m.group(1))
    except Exception:
        pass

    filters = []

    # 1. 무음 구간 압축
    if silence_compress:
        filters.append("silenceremove=start_periods=1:start_duration=0.08:start_threshold=-40dB:start_silence=0.04:detection=peak")
        filters.append("silenceremove=stop_periods=-1:stop_duration=0.28:stop_threshold=-40dB:stop_silence=0.12:detection=peak")

    # 2 & 3. 피치 하향 + 템포 업
    # 피치 factor: 2 ** (pitch_semitones / 12.0)
    pitch_factor = 2.0 ** (pitch_semitones / 12.0)
    # 최종 target_tempo 유지를 위한 atempo: target_tempo / pitch_factor
    adj_tempo = target_tempo / pitch_factor

    filters.append(f"asetrate={int(sr * pitch_factor)},aresample={sr}")
    filters.append(f"atempo={adj_tempo:.4f}")

    # 4. 컴프레서 및 노멀라이즈
    filters.append(f"acompressor=threshold=-18dB:ratio=3.5:attack=15:release=120:makeup={compressor_gain_db:.1f}dB")
    filters.append(f"loudnorm=I={target_lufs}:LRA=7:TP=-1.5")

    cmd = [
        ffmpeg_bin, "-y", "-hide_banner",
        "-i", input_path,
        "-af", ",".join(filters),
        "-c:a", "libmp3lame", "-b:a", "192k",
        output_path
    ]
    res = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if res.returncode == 0 and os.path.exists(output_path):
        return output_path
    return input_path


def apply_natural_breath_gaps(
    scene_audio_files: list[str],
    output_dir: str,
    target_gap: float = 0.35,
    ffmpeg_bin: str = ""
) -> list[dict]:
    """
    각 씬 오디오의 후행 무음을 감지하여, 과도한 침묵은 깔끔하게 다듬고 부족한 호흡은
    자연스러운 인간 성우 호흡(기본 0.35초)으로 정밀 스내핑(Gap 보정)한 오디오 세트를 생성합니다.
    """
    if not ffmpeg_bin:
        ffmpeg_bin = get_ffmpeg_exe()

    gap_dir = os.path.join(output_dir, "breath_adjusted")
    os.makedirs(gap_dir, exist_ok=True)

    results = []
    for idx, fpath in enumerate(scene_audio_files):
        analysis = analyze_audio_silence_boundaries(fpath, ffmpeg_bin)
        tot_dur = analysis["duration"]
        trailing = analysis["trailing"]

        out_fname = f"adj_{idx+1:02d}_{os.path.basename(fpath)}"
        out_path = os.path.join(gap_dir, out_fname)

        is_last = (idx == len(scene_audio_files) - 1)
        cur_target_gap = 0.15 if is_last else target_gap

        if trailing > 0.4:
            trim_dur = max(0.1, tot_dur - trailing + 0.05)
            pad_needed = round(max(0.0, cur_target_gap - 0.05), 3)
            filter_str = f"atrim=0:{trim_dur},asetpts=PTS-STARTPTS,apad=pad_dur={pad_needed}"
        else:
            pad_needed = round(max(0.0, cur_target_gap - trailing), 3)
            filter_str = f"apad=pad_dur={pad_needed}" if pad_needed > 0.02 else "anull"

        cmd = [
            ffmpeg_bin, "-y", "-hide_banner", "-i", fpath,
            "-af", filter_str,
            "-c:a", "libmp3lame", "-b:a", "192k",
            out_path
        ]
        res = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
        if res.returncode == 0 and os.path.exists(out_path):
            new_dur = get_audio_duration(out_path)
            results.append({
                "adjusted_path": out_path,
                "duration": new_dur if new_dur > 0.1 else tot_dur,
                "added_gap": pad_needed,
            })
        else:
            results.append({
                "adjusted_path": fpath,
                "duration": tot_dur,
                "added_gap": 0.0,
            })

    return results


def generate_full_narration_and_subtitles(
    scenes: list[str],
    output_dir: str,
    voice: str = "ko-KR-InJoonNeural",
    rate: str = "+20%",
    title: str = "",
    progress_callback = None,
    engine: str = "edge-tts",
    qwen_mode: str = "custom_voice",
    qwen_speaker: str = "Sohee",
    qwen_instruct: str = "",
    qwen_model_size: str = "0.6B",
    qwen_ref_audio: str = "",
    qwen_ref_text: str = "",
    language: str = "auto",
    mastering_preset: bool = False,
) -> dict:
    """
    8개 씬 전체에 대한 고품질 TTS 음성을 생성하고,
    오디오 결합(narration.mp3), 1줄 쇼츠 자막(subtitles.ass), 씬별 재생 시간을 산출합니다.
    - engine="edge-tts": Edge-TTS를 사용한 1.2배속 초고속 합성
    - engine="qwen-tts": Qwen3-TTS (RTX 3060 가속) CustomVoice 또는 Voice Clone 합성
    """
    os.makedirs(output_dir, exist_ok=True)
    tts_dir = os.path.join(output_dir, "tts")
    os.makedirs(tts_dir, exist_ok=True)

    scene_audio_files = []
    scene_durations = []
    raw_subtitles = []

    target_scenes = [s.strip() for s in scenes if s and s.strip()]
    if not target_scenes:
        raise ValueError("합성할 씬 대본이 없습니다. [1. 각본] 단계에서 대본을 먼저 입력해 주세요.")
    total_scenes = len(target_scenes)

    # 언어 자동 감지
    full_sample = " ".join(target_scenes)
    detected_lang = detect_script_language(full_sample) if language == "auto" else language
    target_lang = "English" if str(detected_lang).lower().startswith("en") else "Korean"

    # Edge-TTS 성우가 언어와 맞지 않을 경우 자동 폴백 보정
    if engine == "edge-tts":
        if target_lang == "English" and voice.startswith("ko-KR"):
            voice = "en-US-ChristopherNeural"
        elif target_lang == "Korean" and voice.startswith("en-US"):
            voice = "ko-KR-InJoonNeural"

    if engine == "qwen-tts":
        # ── Qwen3-TTS 엔진 파이프라인 ──
        if progress_callback:
            progress_callback(0, total_scenes, f"Qwen3-TTS 전용 엔진 가동 및 씬별 음성 합성 준비 중... (언어: {target_lang})")

        qwen_scenes = synthesize_qwen_tts_batch(
            scenes=target_scenes,
            output_dir=output_dir,
            mode=qwen_mode,
            model_size=qwen_model_size,
            speaker=qwen_speaker,
            instruct=qwen_instruct,
            ref_audio_path=qwen_ref_audio,
            ref_text=qwen_ref_text,
            language=target_lang,
            progress_callback=progress_callback,
        )

        current_timeline = 0.0
        for item in qwen_scenes:
            a_path = item["audio_path"]
            dur = float(item.get("duration", 0.0))
            if dur <= 0.1:
                dur = get_audio_duration(a_path)
            if dur <= 0.1:
                dur = 5.0

            scene_audio_files.append(a_path)
            scene_durations.append(dur)

            c_text = item.get("text", "")
            raw_subtitles.append({
                "text": c_text,
                "start": round(current_timeline, 3),
                "end": round(current_timeline + dur, 3),
            })
            current_timeline += dur

    else:
        # ── 기본 Edge-TTS 엔진 파이프라인 ──
        current_timeline = 0.0
        for i in range(1, total_scenes + 1):
            sc_text = target_scenes[i - 1]
            sc_audio_path = os.path.join(tts_dir, f"scene_{i:02d}.mp3")

            if progress_callback:
                progress_callback(i - 1, total_scenes, f"Scene {i} 나레이션 음성 생성 중...")

            dur = synthesize_scene_audio(sc_text, sc_audio_path, voice=voice, rate=rate)
            if dur <= 0.1:
                dur = 5.0

            scene_audio_files.append(sc_audio_path)
            scene_durations.append(dur)

            # 자막용 세그먼트 생성
            clean_sc_text = re.sub(r'\[Scene\s*\d+\]', '', sc_text).strip()
            raw_subtitles.append({
                "text": clean_sc_text,
                "start": round(current_timeline, 3),
                "end": round(current_timeline + dur, 3),
            })

            current_timeline += dur

    ffmpeg_bin = get_ffmpeg_exe()

    # ── FFprobe 기반 성우 호흡(0.35s Gap) 자동 보정 적용 (17_long_auto 알고리즘) ──
    if progress_callback:
        progress_callback(total_scenes, total_scenes, "FFprobe 성우 호흡(0.35s Gap) 정밀 스내핑 및 무음 보정 중...")

    cur_target_gap = 0.12 if mastering_preset else 0.35
    adjusted_items = apply_natural_breath_gaps(
        scene_audio_files=scene_audio_files,
        output_dir=tts_dir,
        target_gap=cur_target_gap,
        ffmpeg_bin=ffmpeg_bin,
    )

    if mastering_preset:
        if progress_callback:
            progress_callback(total_scenes, total_scenes, "🔥 [쇼츠 성우 톤 프리셋] 속도 1.15x / 중저음 피치(-0.9st) / 펀치감(+3.5dB) 마스터링 중...")
        mastered_items = []
        for idx, item in enumerate(adjusted_items):
            in_p = item["adjusted_path"]
            m_fname = f"mst_{idx+1:02d}_{os.path.basename(in_p)}"
            m_out = os.path.join(tts_dir, m_fname)
            m_res = apply_shorts_voice_mastering(
                input_path=in_p,
                output_path=m_out,
                silence_compress=True,
                target_tempo=1.15,
                pitch_semitones=-0.9,
                compressor_gain_db=3.5,
                target_lufs=-14.0,
                ffmpeg_bin=ffmpeg_bin
            )
            m_dur = get_audio_duration(m_res)
            mastered_items.append({
                "adjusted_path": m_res,
                "duration": m_dur,
                "added_gap": 0.05
            })
        adjusted_items = mastered_items

    final_scene_audio_files = [item["adjusted_path"] for item in adjusted_items]
    scene_durations = [item["duration"] for item in adjusted_items]

    # 자막 정밀 재계산 (실제 발화 구간 + 자연스러운 호흡 갭 반영)
    current_timeline = 0.0
    raw_subtitles = []
    for idx, item in enumerate(adjusted_items):
        dur = item["duration"]
        added_gap = item.get("added_gap", 0.0)
        sc_text = target_scenes[idx] if idx < len(target_scenes) else ""
        clean_sc_text = re.sub(r'\[Scene\s*\d+\]', '', sc_text).strip()
        speech_end = max(round(current_timeline + 0.3, 3), round(current_timeline + dur - added_gap, 3))
        raw_subtitles.append({
            "text": clean_sc_text,
            "start": round(current_timeline, 3),
            "end": speech_end,
        })
        current_timeline += dur

    # 1. 씬 오디오 전체 concat
    concat_list_path = os.path.join(tts_dir, "audio_concat.txt")
    with open(concat_list_path, "w", encoding="utf-8") as f:
        for fpath in final_scene_audio_files:
            abs_p = Path(fpath).resolve().as_posix()
            f.write(f"file '{abs_p}'\n")

    final_narration_path = os.path.join(output_dir, "narration.mp3")
    cmd = [
        ffmpeg_bin, "-y", "-f", "concat", "-safe", "0",
        "-i", concat_list_path,
        "-c:a", "libmp3lame", "-b:a", "192k",
        final_narration_path,
    ]
    res = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if res.returncode != 0:
        raise RuntimeError(f"FFmpeg 전체 나레이션 결합 실패: {res.stderr}")

    # 2. 쇼츠 1줄 8~15자 어절 분할
    optimized_subtitles = split_subtitles_for_shorts(raw_subtitles, max_one_line=16, target_chunk_max=15)

    # 3. ASS 고화질 자막 및 캡컷(CapCut)/프리미어 표준 SRT 자막 생성
    ass_path = os.path.join(output_dir, "subtitles.ass")
    generate_ass_subtitles(optimized_subtitles, ass_path, title=title)

    srt_path = os.path.join(output_dir, "subtitles.srt")
    generate_srt_subtitles(optimized_subtitles, srt_path)

    total_duration = get_audio_duration(final_narration_path)
    if total_duration <= 0.1:
        total_duration = current_timeline

    return {
        "narration_path": final_narration_path,
        "scene_durations": scene_durations,
        "total_duration": total_duration,
        "subtitles_ass_path": ass_path,
        "subtitles_srt_path": srt_path,
        "subtitle_items": optimized_subtitles,
        "scene_audio_files": final_scene_audio_files,
    }


def resync_subtitles_from_script(project_dir: str, script_text: str) -> bool:
    """
    기존에 생성된 오디오(narration.mp3 또는 tts/ 씬별 음성)의 타임라인을 유지하면서,
    현재 대본 텍스트를 기준으로 subtitles.srt 및 subtitles.ass를 100% 재동기화하여 복원합니다.
    (음성 재합성 없이 0.1초 만에 자막 텍스트 싱크 복구)
    """
    if not os.path.exists(project_dir) or not script_text.strip():
        return False

    from core.generator import split_script_into_scenes
    scenes = split_script_into_scenes(script_text)
    if not scenes:
        return False

    tts_dir = os.path.join(project_dir, "tts")
    meta_json_path = os.path.join(tts_dir, "meta.json")

    scene_durations = []
    if os.path.exists(meta_json_path):
        try:
            with open(meta_json_path, "r", encoding="utf-8") as f:
                m = json.load(f)
            for sc in m.get("scenes", []):
                dur = float(sc.get("duration", 0.0))
                if dur > 0:
                    scene_durations.append(dur)
        except Exception:
            pass

    if len(scene_durations) < len(scenes) and os.path.exists(tts_dir):
        scene_files = sorted([
            os.path.join(tts_dir, f) for f in os.listdir(tts_dir)
            if f.lower().startswith("scene_") and f.lower().endswith((".wav", ".mp3"))
            and not f.endswith("_adjusted.wav")
        ])
        if scene_files:
            scene_durations = [get_audio_duration(fp) for fp in scene_files]

    final_audio = os.path.join(project_dir, "narration.mp3")
    total_dur = get_audio_duration(final_audio) if os.path.exists(final_audio) else 0.0
    if total_dur <= 0.1:
        total_dur = len(scenes) * 6.0

    if len(scene_durations) < len(scenes):
        total_chars = sum(len(s.strip()) for s in scenes) or 1
        scene_durations = [(len(s.strip()) / total_chars) * total_dur for s in scenes]

    current_timeline = 0.0
    raw_subtitles = []
    for idx, sc_text in enumerate(scenes):
        dur = scene_durations[idx] if idx < len(scene_durations) else (total_dur / len(scenes))
        clean_sc_text = re.sub(r'\[Scene\s*\d+\]', '', sc_text).strip()
        speech_end = max(round(current_timeline + 0.3, 3), round(current_timeline + dur - 0.2, 3))
        raw_subtitles.append({
            "text": clean_sc_text,
            "start": round(current_timeline, 3),
            "end": speech_end,
        })
        current_timeline += dur

    optimized = split_subtitles_for_shorts(raw_subtitles, max_one_line=16, target_chunk_max=15)

    ass_path = os.path.join(project_dir, "subtitles.ass")
    generate_ass_subtitles(optimized, ass_path, title="쇼츠 비디오")

    srt_path = os.path.join(project_dir, "subtitles.srt")
    generate_srt_subtitles(optimized, srt_path)

    return True


def clean_script_for_tts(script_text: str) -> str:
    """
    대본에서 제목, 인트로, 타임코드, 화면 연출 지시문, 나레이션/대본 라벨,
    그리고 [REC], [GEN], [Scene] 태그를 100% 완벽하게 제거하여
    오직 성우가 읽어야 할 '순수 발화 텍스트'만 반환합니다.
    """
    lines = script_text.splitlines()
    cleaned_lines = []

    meta_line_pattern = re.compile(
        r'^\s*(?:'
        r'\[?(?:제목|타이틀|주제|title)\s*[:：\]].*|'
        r'\[?(?:시간|소요\s*시간|예상\s*시간|재생\s*시간|타임코드|러닝타임|time)\s*[:：\]].*|'
        r'\[?(?:화면|비주얼|영상|화면\s*설명|연출\s*가이드|visual|screen)\s*[:：\]].*|'
        r'\[?(?:인트로|아웃트로|오프닝|엔딩|본론|본문|결론|intro|outro|hook|body)\s*[:：\-].*|'
        r'\[(?:인트로|아웃트로|오프닝|엔딩|본론|본문|결론|intro|outro|hook|body)[^\]]*\]|'
        r'\[\s*\d{1,2}:\d{2}\s*(?:~|-)?\s*\d{0,2}:?\d{0,2}\s*\]|'
        r'\(\s*\d{1,2}:\d{2}\s*(?:~|-)?\s*\d{0,2}:?\d{0,2}\s*\)|'
        r'\[(?:REC|GEN|Scene)[^\]]*\]|'
        r'\((?:REC|GEN|Scene)[^\)]*\)'
        r')\s*$',
        re.IGNORECASE
    )

    for line in lines:
        line_s = line.strip()
        if not line_s or meta_line_pattern.match(line_s):
            continue

        l = re.sub(r'[\(\[](?:화면|영상|비주얼|화면\s*설명|visual|screen)\s*[:：][^\)\]]*[\)\]]', '', line_s, flags=re.IGNORECASE)
        l = re.sub(r'[\(\[]\s*\d{1,2}:\d{2}\s*(?:~|-)?\s*\d{0,2}:?\d{0,2}\s*[\)\]]', '', l)
        l = re.sub(r'\[(?:REC|GEN|Scene)[^\]]*\]|\((?:REC|GEN|Scene)[^\)]*\)', '', l, flags=re.IGNORECASE)
        l = re.sub(r'^\s*#\s*\d{1,2}(?:\s*[\(\[]?[^:：\]\)]*[\)\]]?)?\s*[:：\-]?\s*', '', l)
        l = re.sub(r'^\s*\[(?:씬|Scene|#)?\s*\d{1,2}[^\]]*\]\s*[:：\-]?\s*', '', l, flags=re.IGNORECASE)
        l = re.sub(r'\[(?:인트로|아웃트로|오프닝|엔딩|본론|본문|결론|intro|outro|hook|body)[^\]]*\]', '', l, flags=re.IGNORECASE)
        l = re.sub(r'^\s*(?:나레이션|대본|멘트|성우|해설|자막|narration|script|voice)\s*[:：\-]\s*', '', l, flags=re.IGNORECASE)
        l = re.sub(r'\[(?:제목|시간|소요\s*시간|타임코드)[^\]]*\]', '', l, flags=re.IGNORECASE)

        l = l.strip()
        if l:
            cleaned_lines.append(l)

    return "\n".join(cleaned_lines)


def generate_narration_from_full_script(
    script_text: str,
    output_dir: str,
    voice: str = "ko-KR-InJoonNeural",
    rate: str = "+20%",
    title: str = "",
    progress_callback = None,
    engine: str = "edge-tts",
    qwen_mode: str = "custom_voice",
    qwen_speaker: str = "Sohee",
    qwen_instruct: str = "",
    qwen_model_size: str = "0.6B",
    qwen_ref_audio: str = "",
    qwen_ref_text: str = "",
    language: str = "auto",
    mastering_preset: bool = False,
) -> dict:
    """
    씬(Scene) 분할 없이 전체 대본을 그대로 입력받아,
    제목/시간/화면설명/태그를 완전히 제거한 순수 대본으로
    자연스러운 문장 호흡 단위 음성과 캡컷 1줄 싱크 자막(subtitles.srt)을 생성합니다.
    """
    clean_text = clean_script_for_tts(script_text).strip()
    if not clean_text:
        raise ValueError("합성할 대본 내용이 없습니다. 대본을 먼저 입력해 주세요.")

    os.makedirs(output_dir, exist_ok=True)
    try:
        with open(os.path.join(output_dir, "script.txt"), "w", encoding="utf-8") as f:
            f.write(clean_text)
    except Exception:
        pass

    # 문장 및 호흡 단위 분할 (온점, 느낌표, 물음표, 줄바꿈)
    raw_lines = [l.strip() for l in clean_text.splitlines() if l.strip()]
    sentence_units = []
    for line in raw_lines:
        parts = re.split(r'(?<=[.!?])\s+', line)
        for p in parts:
            p = p.strip()
            if not p:
                continue
            if len(p) > 55:
                sub_parts = re.split(r'(?<=[,])\s+', p)
                for sp in sub_parts:
                    sp = sp.strip()
                    if sp:
                        sentence_units.append(sp)
            else:
                sentence_units.append(p)

    if not sentence_units:
        sentence_units = [clean_text]

    def _adapted_progress(current, total, msg):
        if progress_callback:
            clean_msg = re.sub(r'Scene\s*(\d+)/?(\d*)', r'문장 \1/\2', msg)
            clean_msg = clean_msg.replace("Scene ", "문장 ")
            progress_callback(current, total, clean_msg)

    res = generate_full_narration_and_subtitles(
        scenes=sentence_units,
        output_dir=output_dir,
        voice=voice,
        rate=rate,
        title=title,
        progress_callback=_adapted_progress if progress_callback else None,
        engine=engine,
        qwen_mode=qwen_mode,
        qwen_speaker=qwen_speaker,
        qwen_instruct=qwen_instruct,
        qwen_model_size=qwen_model_size,
        qwen_ref_audio=qwen_ref_audio,
        qwen_ref_text=qwen_ref_text,
        language=language,
        mastering_preset=mastering_preset,
    )
    res["sentence_count"] = len(sentence_units)
    res["clean_script"] = clean_text
    return res

