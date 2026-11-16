import os
import shutil
import subprocess

def get_ffmpeg_exe() -> str:
    """
    FFmpeg 실행 파일의 절대 경로를 안전하게 탐색하고 반환합니다.
    1. PATH 환경변수
    2. 프로젝트 루트 폴더 (d:\\쇼츠자동화\\ffmpeg.exe)
    3. D:\\ffmpeg\\ffmpeg.exe
    4. D:\\이전\\ffmpeg\\ffmpeg.exe
    5. CapCut 내장 ffmpeg.exe
    """
    which_ffmpeg = shutil.which("ffmpeg")
    if which_ffmpeg and os.path.exists(which_ffmpeg):
        return os.path.abspath(which_ffmpeg)

    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    candidates = [
        os.path.join(base_dir, "ffmpeg.exe"),
        r"d:\쇼츠자동화\ffmpeg.exe",
        r"D:\ffmpeg\ffmpeg.exe",
        r"D:\이전\ffmpeg\ffmpeg.exe",
    ]

    local_app_data = os.environ.get("LOCALAPPDATA", "")
    if local_app_data:
        capcut_dir = os.path.join(local_app_data, "CapCut", "Apps")
        if os.path.exists(capcut_dir):
            try:
                for sub in sorted(os.listdir(capcut_dir), reverse=True):
                    candidates.append(os.path.join(capcut_dir, sub, "ffmpeg.exe"))
            except Exception:
                pass

    for c in candidates:
        if os.path.exists(c):
            abs_c = os.path.abspath(c)
            # PATH에 추가하여 다른 라이브러리나 서브프로세스도 즉시 인식하도록 함
            c_dir = os.path.dirname(abs_c)
            current_path = os.environ.get("PATH", "")
            if c_dir.lower() not in current_path.lower():
                os.environ["PATH"] = f"{c_dir};{current_path}"
            return abs_c

    return "ffmpeg"


def ensure_ffmpeg() -> str:
    """앱 시작 시 ffmpeg 경로를 PATH에 등록하고 확인합니다."""
    exe = get_ffmpeg_exe()
    try:
        r = subprocess.run([exe, "-version"], capture_output=True, text=True, timeout=5)
        if r.returncode == 0:
            return exe
    except Exception as e:
        print(f"[ffmpeg_utils] ffmpeg 실행 실패: {e}")
    return exe
