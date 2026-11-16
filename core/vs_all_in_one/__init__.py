# -*- coding: utf-8 -*-
"""
core.vs_all_in_one
유튜브 쇼츠(9:16) 스펙 비교(VS) 올인원 제작 스튜디오 패키지
"""

import os
from pathlib import Path

# 패키지 및 저장소 기본 경로
PACKAGE_DIR = Path(__file__).resolve().parent
CORE_DIR = PACKAGE_DIR.parent
PROJECT_ROOT = CORE_DIR.parent

SOURCES_DIR = PROJECT_ROOT / "captures" / "vs_studio" / "sources"
EXPORTS_DIR = PROJECT_ROOT / "captures" / "vs_studio" / "exports"

SOURCES_DIR.mkdir(parents=True, exist_ok=True)
EXPORTS_DIR.mkdir(parents=True, exist_ok=True)


def load_env_api_key() -> str:
    """루트의 .env 또는 config.json 또는 환경 변수에서 GEMINI_API_KEY를 탐색하여 반환합니다."""
    # 1. os.environ 확인
    api_key = os.environ.get("GEMINI_API_KEY", "")
    if api_key:
        return api_key

    # 2. .env 파일 파싱
    env_path = PROJECT_ROOT / ".env"
    if env_path.exists():
        try:
            with open(env_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line.startswith("GEMINI_API_KEY="):
                        val = line.split("=", 1)[1].strip().strip('"').strip("'")
                        if val:
                            return val
        except Exception:
            pass

    # 3. config.json 확인
    cfg_path = PROJECT_ROOT / "config.json"
    if cfg_path.exists():
        try:
            import json
            with open(cfg_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                return data.get("gemini_api_key", "")
        except Exception:
            pass

    return ""
