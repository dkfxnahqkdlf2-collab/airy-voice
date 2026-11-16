"""
core/project_manager.py
유튜브 쇼츠 프로젝트 단위 독립 폴더 관리 엔진
- 기본 경로: D:\\쇼츠_프로젝트\\YYYYMMDD_주제명\\
- 폴더 내부 구조:
  ├── assets/          (Flow/Studio 에셋 등록용 핵심 실물 앵커 사진 1~3장)
  ├── videos/          (Shorts Story Studio에서 렌더링된 영상 클립 보관)
  ├── tts/             (씬별 개별 mp3 및 오디오 메타데이터)
  ├── narration.mp3    (통합 고음질 나레이션 오디오)
  ├── subtitles.srt    (캡컷 100% 호환 밀리초 1줄 싱크 자막)
  ├── script.txt       (완성 대본 및 프롬프트 텍스트)
  └── project_meta.json(프로젝트 상태 및 데이터 캐시)
"""

import datetime
import json
import os
import re
import subprocess
import sys

DEFAULT_PROJECTS_ROOT = r"D:\쇼츠_프로젝트"


def sanitize_filename(name: str) -> str:
    """폴더명이나 파일명에 사용할 수 없는 특수문자를 안전하게 제거합니다."""
    clean = re.sub(r'[\\/*?:"<>|]', "", name).strip()
    clean = re.sub(r"\s+", "_", clean)
    return clean[:40] if clean else "신규프로젝트"


def get_projects_root(custom_root: str = "") -> str:
    root = custom_root or DEFAULT_PROJECTS_ROOT
    os.makedirs(root, exist_ok=True)
    return root


def list_projects(custom_root: str = "") -> list:
    """기존 프로젝트 목록을 최신순으로 정렬하여 반환합니다."""
    root = get_projects_root(custom_root)
    if not os.path.exists(root):
        return []

    projects = []
    try:
        entries = os.listdir(root)
    except Exception:
        return []

    for name in entries:
        p_path = os.path.join(root, name)
        if not os.path.isdir(p_path):
            continue

        meta_path = os.path.join(p_path, "project_meta.json")
        meta = {}
        if os.path.exists(meta_path):
            try:
                with open(meta_path, "r", encoding="utf-8") as f:
                    meta = json.load(f)
            except Exception:
                pass

        # 파일 존재 여부 실시간 체크
        has_narration = os.path.exists(os.path.join(p_path, "narration.mp3"))
        has_subtitles = os.path.exists(os.path.join(p_path, "subtitles.srt"))
        
        assets_dir = os.path.join(p_path, "assets")
        asset_files = [f for f in os.listdir(assets_dir) if f.lower().endswith(('.png', '.jpg', '.jpeg', '.webp'))] if os.path.exists(assets_dir) else []
        
        videos_dir = os.path.join(p_path, "videos")
        video_files = [f for f in os.listdir(videos_dir) if f.lower().endswith(('.mp4', '.mov', '.webm'))] if os.path.exists(videos_dir) else []

        mtime = os.path.getmtime(p_path)

        projects.append({
            "name": name,
            "path": p_path,
            "title": meta.get("title", name),
            "created_at": meta.get("created_at", datetime.datetime.fromtimestamp(mtime).strftime("%Y-%m-%d %H:%M")),
            "mtime": mtime,
            "has_narration": has_narration,
            "has_subtitles": has_subtitles,
            "asset_count": len(asset_files),
            "video_count": len(video_files),
            "meta": meta,
        })

    projects.sort(key=lambda x: x["mtime"], reverse=True)
    return projects


def create_project(title: str, custom_root: str = "") -> dict:
    """새 프로젝트 폴더 및 하위 디렉토리를 생성하고 메타데이터를 초기화합니다."""
    root = get_projects_root(custom_root)
    now_str = datetime.datetime.now().strftime("%Y%m%d")
    clean_title = sanitize_filename(title)
    base_folder_name = f"{now_str}_{clean_title}"

    folder_name = base_folder_name
    p_path = os.path.join(root, folder_name)
    counter = 1
    while os.path.exists(p_path):
        counter += 1
        folder_name = f"{base_folder_name}_{counter}"
        p_path = os.path.join(root, folder_name)

    os.makedirs(p_path, exist_ok=True)
    os.makedirs(os.path.join(p_path, "assets"), exist_ok=True)
    os.makedirs(os.path.join(p_path, "videos"), exist_ok=True)
    os.makedirs(os.path.join(p_path, "tts"), exist_ok=True)

    created_at = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    meta = {
        "title": title,
        "folder_name": folder_name,
        "created_at": created_at,
        "script": "",
        "prompts": {},
        "core_assets": [],
        "chosen_assets": {},
    }

    meta_path = os.path.join(p_path, "project_meta.json")
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)

    return {
        "name": folder_name,
        "path": p_path,
        "title": title,
        "created_at": created_at,
        "meta": meta,
    }


def load_project_meta(project_path: str) -> dict:
    meta_path = os.path.join(project_path, "project_meta.json")
    if os.path.exists(meta_path):
        try:
            with open(meta_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def save_project_meta(project_path: str, data: dict):
    os.makedirs(project_path, exist_ok=True)
    meta_path = os.path.join(project_path, "project_meta.json")
    existing = load_project_meta(project_path)
    existing.update(data)
    try:
        with open(meta_path, "w", encoding="utf-8") as f:
            json.dump(existing, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"[project_manager] save error: {e}")


def open_folder_in_explorer(folder_path: str) -> bool:
    """Windows 파일 탐색기에서 해당 폴더를 사용자의 실제 활성 데스크톱(WinSta0\\Default)에 즉시 팝업합니다."""
    norm_path = os.path.normpath(os.path.abspath(folder_path))
    if not os.path.exists(norm_path):
        os.makedirs(norm_path, exist_ok=True)

    if sys.platform == "win32":
        # 1순위: CreateProcessW로 사용자의 대화형 화면(WinSta0\Default)에 직접 explorer.exe 실행
        try:
            import ctypes
            from ctypes import wintypes

            class STARTUPINFO(ctypes.Structure):
                _fields_ = [
                    ('cb', wintypes.DWORD),
                    ('lpReserved', wintypes.LPWSTR),
                    ('lpDesktop', wintypes.LPWSTR),
                    ('lpTitle', wintypes.LPWSTR),
                    ('dwX', wintypes.DWORD),
                    ('dwY', wintypes.DWORD),
                    ('dwXSize', wintypes.DWORD),
                    ('dwYSize', wintypes.DWORD),
                    ('dwXCountChars', wintypes.DWORD),
                    ('dwYCountChars', wintypes.DWORD),
                    ('dwFillAttribute', wintypes.DWORD),
                    ('dwFlags', wintypes.DWORD),
                    ('wShowWindow', wintypes.WORD),
                    ('cbReserved2', wintypes.WORD),
                    ('lpReserved2', ctypes.c_char_p),
                    ('hStdInput', wintypes.HANDLE),
                    ('hStdOutput', wintypes.HANDLE),
                    ('hStdError', wintypes.HANDLE),
                ]

            class PROCESS_INFORMATION(ctypes.Structure):
                _fields_ = [
                    ('hProcess', wintypes.HANDLE),
                    ('hThread', wintypes.HANDLE),
                    ('dwProcessId', wintypes.DWORD),
                    ('dwThreadId', wintypes.DWORD),
                ]

            si = STARTUPINFO()
            si.cb = ctypes.sizeof(STARTUPINFO)
            si.lpDesktop = 'WinSta0\\Default'
            si.dwFlags = 1  # STARTF_USESHOWWINDOW
            si.wShowWindow = 1  # SW_SHOWNORMAL

            pi = PROCESS_INFORMATION()
            cmd = f'explorer.exe "{norm_path}"'
            success = ctypes.windll.kernel32.CreateProcessW(
                None, cmd, None, None, False, 0, None, None,
                ctypes.byref(si), ctypes.byref(pi)
            )
            if success:
                if pi.hProcess:
                    ctypes.windll.kernel32.CloseHandle(pi.hProcess)
                if pi.hThread:
                    ctypes.windll.kernel32.CloseHandle(pi.hThread)
                return True
        except Exception as e:
            print(f"[project_manager] CreateProcess explorer error: {e}")

        # 2순위: os.startfile (일반 데스크톱 환경)
        try:
            os.startfile(norm_path)
            return True
        except Exception as e:
            print(f"[project_manager] startfile error: {e}")

        # 3순위: subprocess
        try:
            subprocess.Popen(f'explorer.exe "{norm_path}"')
            return True
        except Exception:
            return False
    else:
        try:
            subprocess.Popen(["xdg-open", norm_path])
            return True
        except Exception as e:
            print(f"[project_manager] xdg-open error: {e}")
            return False
