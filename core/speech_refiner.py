"""
core/speech_refiner.py
녹화 영상 또는 오디오 파일에서 음성을 초고속 추출하고,
Gemini AI를 통해 더듬거리거나 끊긴 발화를 100% 깔끔한 프로 쇼츠 대본으로 자동 정제하는 엔진
"""

import json
import os
import re
import subprocess
import sys
import tempfile
import warnings
from pathlib import Path
from typing import Dict, Optional, Callable

from core.ffmpeg_utils import get_ffmpeg_exe

try:
    from google import genai
    from google.genai import types as genai_types
    HAS_NEW_GENAI = True
except ImportError:
    HAS_NEW_GENAI = False

# 레거시 SDK 경고 억제
with warnings.catch_warnings():
    warnings.simplefilter("ignore")
    try:
        import google.generativeai as legacy_genai
        HAS_LEGACY_GENAI = True
    except ImportError:
        HAS_LEGACY_GENAI = False


def extract_audio_from_media(media_path: str, output_audio_path: Optional[str] = None) -> str:
    """
    영상 파일(.mp4, .mov, .mkv, .avi, .webm 등) 또는 기존 오디오 파일에서
    FFmpeg를 이용하여 24kHz 모노 MP3로 초고속(수 초 이내) 추출/변환합니다.
    """
    if not os.path.exists(media_path):
        raise FileNotFoundError(f"미디어 파일을 찾을 수 없습니다: {media_path}")

    ext = os.path.splitext(media_path)[1].lower()
    
    # 이미 mp3이면서 output_audio_path가 지정되지 않은 경우 원본 그대로 반환
    if ext == ".mp3" and not output_audio_path:
        return os.path.abspath(media_path)

    if not output_audio_path:
        stem = Path(media_path).stem
        parent_dir = os.path.dirname(os.path.abspath(media_path))
        output_audio_path = os.path.join(parent_dir, f"{stem}_extracted_audio.mp3")

    ffmpeg_exe = get_ffmpeg_exe()
    cmd = [
        ffmpeg_exe,
        "-y",
        "-i", media_path,
        "-vn",                   # 비디오 스트림 제외
        "-acodec", "libmp3lame", # MP3 인코딩
        "-ar", "24000",          # 24kHz 샘플레이트 (음성 인식 및 TTS 최적)
        "-ac", "1",              # 모노 채널로 용량 최적화
        "-b:a", "96k",           # 96kbps (가볍고 고품질)
        output_audio_path
    ]

    try:
        res = subprocess.run(cmd, capture_output=True, text=True, check=True)
    except subprocess.CalledProcessError as e:
        raise RuntimeError(f"FFmpeg 오디오 추출 실패: {e.stderr or e.stdout}")

    if not os.path.exists(output_audio_path) or os.path.getsize(output_audio_path) == 0:
        raise RuntimeError("오디오 파일이 생성되지 않았거나 크기가 0바이트입니다.")

    return os.path.abspath(output_audio_path)


def refine_speech_to_shorts_script(
    audio_path: str,
    gemini_api_key: str,
    progress_callback: Optional[Callable[[str], None]] = None,
    mode: str = "preserve_all",
    **kwargs,
) -> Dict:
    """
    Gemini 멀티모달 오디오 AI를 호출하여:
    1) 사용자가 말한 원본 발화를 충실하게 전사(Raw Transcript)
    2) 말 더듬기, '어/음' 군더더기, 끊김, 중복만 말끔히 제거
    3) 사용자가 말한 핵심 내용, 구체적 수치(%, 시간 등), 실험 과정, 결론을 100% 그대로 보존
    4) [REC](화면 시연)와 [GEN](AI 영상)으로 자동 분리된 흡입력 있는 쇼츠 대본으로 완성
    """
    if not gemini_api_key:
        raise ValueError("Gemini API 키가 설정되지 않았습니다.")
    if not os.path.exists(audio_path):
        raise FileNotFoundError(f"오디오 파일을 찾을 수 없습니다: {audio_path}")

    if progress_callback:
        progress_callback("🎧 오디오 파일 분석 준비 중...")

    # 후보 모델 목록 (안정성 최우선 순위)
    candidate_models = [
        "gemini-3.5-flash",
        "gemini-3.5-flash-lite",
        "gemini-3.1-flash-lite",
        "gemini-flash-latest",
        "gemini-3.8-flash",
    ]

    mode_instruction = ""
    if mode == "concise_hook":
        mode_instruction = """
[정제 스타일: 핵심 요약형]
- 시청자가 즉각 반응할 수 있도록 템포감 있게 압축 정리하되, 사용자가 말한 '구체적인 수치(%, 시간, 분)'와 '실제 테스트 팩트'는 절대 생략하지 말고 반드시 살리세요.
- 절대로 사용자가 말하지 않은 허구의 원인이나 가짜 결과를 지어내지 마세요.
"""
    else:
        mode_instruction = """
[정제 스타일: 원문 내용 & 수치 100% 보존형 (최우선 기본값)]
- 사용자가 말한 모든 경험담, 테스트 절차, 의문점, 실제 결론, 생각의 흐름을 절대로 날리거나 과도하게 압축하지 마세요.
- 원본 발화의 '정보량(Information Content)'과 '디테일'을 100% 온전히 유지해야 합니다.
- 문장의 어순과 어미만 듣기 좋은 자연스러운 구어체 대본으로 매끄럽게 연결하세요.
"""

    refine_prompt = f"""
당신은 사용자의 즉흥적인 녹음 발화를 방송용 전문 구어체 대본으로 매끄럽게 교정하는 최고 수준의 AI 전문 방송 작가 겸 오디오 에디터입니다.
사용자가 마이크를 켜고 실제 화면을 보며 녹음한 오디오를 직접 듣고 있습니다.

{mode_instruction}

[절대 불변의 4대 원칙 (위반 시 엄격히 실패로 간주)]
1. 🚫 【허구 날조 및 내용 왜곡 절대 금지 (NO Hallucination)】:
   - 사용자가 직접 말하지 않은 이론, 원인, 배경지식, 조언, 결과를 단 한 단어도 임의로 지어내거나 멋대로 추측하여 결론짓지 마세요!
   - (예: 사용자가 "원인을 아직 모르겠다, 다음번에 반대로 해보겠다"고 했는데, "알고리즘이 이탈률을 감지했기 때문이다"라고 원인을 단정하거나 "조회수가 터지는 것을 확인했다"고 허위 성공 결론을 짓는 것은 절대 금지입니다.)
   - 사용자가 실제로 겪은 관찰, 의문, 고민, 결론을 100% 진솔하게 유지하세요.

2. 🔢 【모든 수치, 숫자, 데이터 100% 완전 보존 (NO Omission)】:
   - 사용자가 발언한 모든 구체적인 숫자, 비율, 퍼센트(%), 시간(초, 분, 시간), 기기명(PC, 모바일 앱 등), 메뉴명, 고유명사는 단 하나도 생략하거나 뭉뚱그리지 말고 100% 정확하게 대본에 포함해야 합니다.
   - (예: "97.6%", "20분", "PC/컴퓨터", "핸드폰" 등이 언급되었다면 대본에 반드시 그대로 생생하게 포함되어야 합니다.)

3. 📝 【사용자의 발언 내용 및 스토리텔링 전량 보존 (Full Storyline)】:
   - 사용자가 겪은 상황, 직접 시도해 본 실험 과정(A방식 vs B방식), 중간에 느낀 의문점, 앞으로 해볼 계획("다음엔 반대로 해보겠다") 등 이야기의 흐름 전체를 멋대로 잘라내거나 몇 줄로 앙상하게 날려버리지 마세요.
   - 녹음된 이야기의 모든 맥락이 살아있어야 합니다.

4. ✂️ 【오직 제거 및 정돈해야 하는 대상】:
   - ① 음성적 말더듬 및 어절 중복 제거: (예: "피.. 피드 노출" -> "피드 노출", "원단 이번" -> "이번", "바로 안 올리고 바로 안 올리고" -> "바로 올리지 않고")
   - ② 무의미한 추임새 및 말버릇 제거: "어...", "음...", "그니까", "막", "아", "이제", "약간" 등
   - ③ 불필요한 끊김이나 헛기침, 말실수, 꼬인 문장을 문법적으로 자연스럽고 귀에 착 감기는 한국어 방송 구어체 문장으로 정돈.

[구조화 태그: [REC]와 [GEN] 태그 자동 부착]
- [REC]: 사용자가 실제 화면이나 프로그램을 보여주며 시연/설명/수치 확인하는 구간
- [GEN]: AI 비주얼 영상, 상황 연출, 시청자에게 질문을 던지거나 배경 설명/다음 계획을 밝히는 구간
- 억지로 대본을 줄이지 말고, 사용자의 전체 발언 분량에 맞추어 문맥이 자연스럽게 전환되는 지점마다 [REC]와 [GEN]을 번갈아 교차 배치하세요. (구간마다 1~3문장씩 자연스럽게 분할)

[구조 형식 안내]
[REC]
(오디오에서 사용자가 말한 실제 화면/수치 관련 대사...)

[GEN]
(오디오에서 사용자가 말한 실제 상황/설명/결론 대사...)

반드시 아래 JSON 형식으로만 응답하세요:
{{
  "raw_transcript": "사용자가 말한 말더듬과 군더더기가 포함된 원문 전사 텍스트 전체",
  "polished_script": "수치와 원본 내용이 100% 보존되고 말더듬/군더더기만 정돈된 [REC]/[GEN] 쇼츠 대본",
  "fixes_summary": "수치/원문 내용 100% 보존, 말더듬 및 군더더기 제거 요약 (1~2줄)"
}}
"""

    if progress_callback:
        progress_callback("🤖 Gemini AI에 오디오 업로드 및 청취 분석 중...")

    last_error = None

    if HAS_NEW_GENAI:
        try:
            client = genai.Client(api_key=gemini_api_key)
            uploaded_file = client.files.upload(file=audio_path)

            for model_name in candidate_models:
                try:
                    if progress_callback:
                        progress_callback(f"✨ AI가 더듬는 말을 제거하고 쇼츠 대본으로 다듬는 중... ({model_name})")

                    resp = client.models.generate_content(
                        model=model_name,
                        contents=[uploaded_file, refine_prompt],
                        config={"response_mime_type": "application/json"}
                    )
                    txt = resp.text.strip()
                    parsed = _parse_json_response(txt)
                    if parsed and parsed.get("polished_script"):
                        return parsed
                except Exception as ex:
                    last_error = ex
                    continue
        except Exception as e:
            last_error = e

    # 레거시 SDK 폴백
    if HAS_LEGACY_GENAI:
        try:
            legacy_genai.configure(api_key=gemini_api_key)
            uploaded = legacy_genai.upload_file(path=audio_path)
            for model_name in ["gemini-1.5-flash", "gemini-1.5-pro"]:
                try:
                    model = legacy_genai.GenerativeModel(model_name)
                    resp = model.generate_content([uploaded, refine_prompt])
                    txt = resp.text.strip()
                    parsed = _parse_json_response(txt)
                    if parsed and parsed.get("polished_script"):
                        return parsed
                except Exception as ex:
                    last_error = ex
                    continue
        except Exception as e:
            last_error = e

    raise RuntimeError(f"오디오 음성 정제 실패: {last_error}")


def _parse_json_response(raw_text: str) -> Dict:
    """JSON 마크다운 펜스 제거 및 딕셔너리 안전 파싱"""
    t = raw_text.strip()
    if t.startswith("```"):
        t = re.sub(r"^```(?:json)?\s*", "", t)
        t = re.sub(r"\s*```$", "", t)
        t = t.strip()

    try:
        return json.loads(t)
    except json.JSONDecodeError:
        # 혹시 JSON이 깨졌을 경우 정규식으로 필드 추출
        raw_m = re.search(r'"raw_transcript"\s*:\s*"(.*?)"(?=,\s*"polished_script")', t, re.DOTALL)
        pol_m = re.search(r'"polished_script"\s*:\s*"(.*?)"(?=,\s*"fixes_summary")', t, re.DOTALL)
        sum_m = re.search(r'"fixes_summary"\s*:\s*"(.*?)"\s*\}', t, re.DOTALL)

        return {
            "raw_transcript": raw_m.group(1).encode().decode('unicode-escape') if raw_m else "",
            "polished_script": pol_m.group(1).encode().decode('unicode-escape') if pol_m else t,
            "fixes_summary": sum_m.group(1).encode().decode('unicode-escape') if sum_m else "대본 정제 완료"
        }
