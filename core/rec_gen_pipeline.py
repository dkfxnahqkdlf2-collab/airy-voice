"""
core/rec_gen_pipeline.py
REC(화면 녹화) & GEN(AI 생성) 교차 파이프라인 엔진
- 대본 전체를 분석하여 [REC](화면 녹화)와 [GEN](AI 비디오 생성)으로 자동 분리
- 태그([REC], [GEN])가 이미 있는 경우 파싱, 없는 경우 Gemini LLM이 문맥을 분석하여 자동 이원화
- TTS 음성 합성은 [REC]/[GEN] 태그를 제거한 순수 텍스트로 한 번에 생성
- 출력물:
  1) Flow_스토리보드_일괄스크립트.txt (Flow 스토리보드 원클릭 붙여넣기용)
  2) 화면_녹화_체크리스트.txt (녹화 대상, 마우스 액션, 연출 팁)
  3) AI_영상_프롬프트_목록.txt (영문 비디오 프롬프트, 카메라 워크)
  4) 캡컷_타임라인_배치표.txt (시간대별 REC/GEN 교차 배치 타임코드 표)
"""

import json
import math
import os
import re
from typing import Dict, List, Tuple

from core.generator import _call_gemini_api
from core.tts_engine import (
    generate_narration_from_full_script,
    get_audio_duration,
)


def format_seconds_to_timecode(seconds: float) -> str:
    """초를 MM:SS 형식으로 변환"""
    m = int(seconds // 60)
    s = int(seconds % 60)
    return f"{m:02d}:{s:02d}"


def strip_pipeline_tags(script_text: str) -> str:
    """
    대본에서 제목, 인트로, 타임코드, 화면 연출 지시문, 나레이션/대본 라벨,
    그리고 [REC], [GEN], [Scene] 태그를 100% 완벽하게 제거하여
    오직 성우가 읽어야 할 '순수 발화 텍스트'만 반환합니다.
    """
    lines = script_text.splitlines()
    cleaned_lines = []

    # 전체 줄이 메타데이터/헤더/시간 표시인 경우 줄 통째로 스킵하는 정규식
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
        if not line_s:
            continue

        # 1. 메타데이터 한 줄 전체 스킵
        if meta_line_pattern.match(line_s):
            continue

        # 2. 문장 내부/앞머리 인라인 메타데이터 제거
        # (화면: ...), [화면: ...], (영상: ...) 제거
        l = re.sub(r'[\(\[](?:화면|영상|비주얼|화면\s*설명|visual|screen)\s*[:：][^\)\]]*[\)\]]', '', line_s, flags=re.IGNORECASE)
        # 타임스탬프 (00:00~00:15), [00:00~00:15], [00:00] 제거
        l = re.sub(r'[\(\[]\s*\d{1,2}:\d{2}\s*(?:~|-)?\s*\d{0,2}:?\d{0,2}\s*[\)\]]', '', l)
        # [REC-01], [GEN-01], [Scene 1] 태그 제거
        l = re.sub(r'\[(?:REC|GEN|Scene)[^\]]*\]|\((?:REC|GEN|Scene)[^\)]*\)', '', l, flags=re.IGNORECASE)
        # [인트로], [아웃트로], [본문 1] 등 인라인 괄호 태그 제거
        l = re.sub(r'\[(?:인트로|아웃트로|오프닝|엔딩|본론|본문|결론|intro|outro|hook|body)[^\]]*\]', '', l, flags=re.IGNORECASE)
        # 앞머리 "나레이션:", "대본:", "멘트:", "성우:", "해설:" 접두사 제거
        l = re.sub(r'^\s*(?:나레이션|대본|멘트|성우|해설|자막|narration|script|voice)\s*[:：\-]\s*', '', l, flags=re.IGNORECASE)
        # 인라인 앞머리 [소요시간: 00:00~00:45] 등 혹시 남은 대괄호 메타데이터 제거
        l = re.sub(r'\[(?:제목|시간|소요\s*시간|타임코드)[^\]]*\]', '', l, flags=re.IGNORECASE)

        l = l.strip()
        if l:
            cleaned_lines.append(l)

    return "\n".join(cleaned_lines)



def parse_script_rec_gen(script_text: str, gemini_api_key: str = "") -> List[Dict]:
    """
    대본을 분석하여 [REC]와 [GEN] 구간으로 분리합니다.
    1. 대본 내 [REC], [GEN] 태그가 존재하면 정규식으로 직접 파싱
    2. 태그가 없는 순수 텍스트인 경우 Gemini API를 호출하여 문맥 기반 자동 이원화 분리
    """
    script_text = script_text.strip()
    if not script_text:
        return []

    has_rec = bool(re.search(r'\[REC[^\]]*\]', script_text, re.IGNORECASE))
    has_gen = bool(re.search(r'\[GEN[^\]]*\]', script_text, re.IGNORECASE))

    # ── 1. 명시적 태그가 있는 경우 정규식 파싱 ──
    if has_rec or has_gen:
        segments = []
        pattern = re.compile(r'(\[(?:REC|GEN)[^\]]*\])', re.IGNORECASE)
        tokens = pattern.split(script_text)

        current_type = "REC"
        rec_count = 0
        gen_count = 0

        for token in tokens:
            token = token.strip()
            if not token:
                continue

            tag_m = re.match(r'\[(REC|GEN)[^\]]*\]', token, re.IGNORECASE)
            if tag_m:
                current_type = tag_m.group(1).upper()
            else:
                if current_type == "REC":
                    rec_count += 1
                    seg_id = f"REC-{rec_count:02d}"
                else:
                    gen_count += 1
                    seg_id = f"GEN-{gen_count:02d}"

                segments.append({
                    "id": seg_id,
                    "type": current_type,
                    "text": token,
                    "summary_ko": token[:20],
                    "guide": "",
                    "prompt_en": "",
                    "camera_en": "",
                })

        if segments:
            return segments

    # ── 2. 태그가 없는 경우 Gemini LLM 문맥 기반 자동 분류 ──
    if gemini_api_key:
        prompt = f"""당신은 유튜브 쇼츠 전문 비디오 프로듀서입니다.
아래 대본을 읽고, 영상 제작 시 '직접 컴퓨터/스마트폰 화면을 녹화(REC)'해야 하는 문장과 'AI 비디오로 생성(GEN)'해야 하는 문장으로 이원화 분리하세요.

[분리 기준]
1. REC (화면 녹화):
   - 실제 웹사이트, 프로그램(캡컷, 유튜브 스튜디오, 브라우저, 엑셀, 툴 등) 조작 화면
   - 데이터 지표, 통계 그래프, 설정 버튼 클릭, 기능 시연, 증거 화면
   - 실질적인 튜토리얼/하우투(How-to) 액션

2. GEN (AI 비디오 생성):
   - 비유적/추상적 표현, 상상 속 개념, 인공지능 로봇, 우주/미래 시각화
   - 감정적 후킹, 강렬한 오프닝 비주얼, 시네마틱 드라마틱 장면
   - 화면 녹화로 보여주기 힘든 개념적 시각 묘사

[대본]
{script_text}

반드시 아래 JSON 포맷으로만 응답하세요:
{{
  "segments": [
    {{
      "type": "REC",
      "text": "해당 문장 대본",
      "summary_ko": "화면 요약 1줄 (예: 유튜브 스튜디오 분석 탭)",
      "guide": "화면 녹화 대상 및 연출 가이드 (예: 마우스로 특정 그래프 줌인)"
    }},
    {{
      "type": "GEN",
      "text": "해당 문장 대본",
      "summary_ko": "AI 시각화 요약 1줄 (예: AI 알고리즘 데이터 신경망)",
      "guide": "시각 기획 의도"
    }}
  ]
}}
"""
        resp_json = _call_gemini_api(prompt, gemini_api_key, json_mode=True)
        if resp_json:
            try:
                data = json.loads(resp_json)
                raw_segs = data.get("segments", [])
                segments = []
                rec_idx = 1
                gen_idx = 1
                for s in raw_segs:
                    s_type = "GEN" if s.get("type", "").upper() == "GEN" else "REC"
                    if s_type == "REC":
                        seg_id = f"REC-{rec_idx:02d}"
                        rec_idx += 1
                    else:
                        seg_id = f"GEN-{gen_idx:02d}"
                        gen_idx += 1

                    segments.append({
                        "id": seg_id,
                        "type": s_type,
                        "text": s.get("text", "").strip(),
                        "summary_ko": s.get("summary_ko", "").strip() or s.get("text", "")[:18],
                        "guide": s.get("guide", "").strip(),
                        "prompt_en": "",
                        "camera_en": "",
                    })
                if segments:
                    return segments
            except Exception as e:
                print(f"[rec_gen_pipeline] LLM parse error: {e}")

    # ── 3. 폴백: 온점/줄바꿈 기준 홀수 REC / 짝수 GEN 교차 할당 ──
    lines = [l.strip() for l in script_text.splitlines() if l.strip()]
    if len(lines) <= 1:
        lines = [s.strip() for s in re.split(r'(?<=[.!?])\s+', script_text) if s.strip()]

    fallback_segs = []
    rec_idx = 1
    gen_idx = 1
    for i, line in enumerate(lines):
        s_type = "REC" if i % 2 == 0 else "GEN"
        if s_type == "REC":
            seg_id = f"REC-{rec_idx:02d}"
            rec_idx += 1
        else:
            seg_id = f"GEN-{gen_idx:02d}"
            gen_idx += 1

        fallback_segs.append({
            "id": seg_id,
            "type": s_type,
            "text": line,
            "summary_ko": line[:18],
            "guide": "",
            "prompt_en": "",
            "camera_en": "",
        })

    return fallback_segs


def _ensure_segment_3shots(s: Dict) -> Dict:
    """
    GEN 세그먼트에 1씬 3컷(이미지 3장 / 3개 비디오 프롬프트)이 무조건 완벽하게 존재하도록 보장합니다.
    Flow의 [스토리보드 각본]과 [전체 프롬프트 일괄 분배] 규격에 1:1 매칭됩니다.
    """
    shots = s.get("shots")
    if shots and len(shots) >= 3 and all(sh.get("video_prompt") for sh in shots):
        # 이미 3컷이 완비되어 있으면 distribution prompt만 재확인
        if not s.get("flow_distribution_prompt"):
            dist_lines = []
            for sh in shots:
                dist_lines.append(f"[Shot {sh.get('shot_num', 1)}]\n{sh.get('video_prompt', '').strip()}")
            s["flow_distribution_prompt"] = "\n\n".join(dist_lines)
        return s

    text = s.get("text", "").strip()
    summary = s.get("summary_ko", "").strip() or text[:15]
    clean_korean = re.sub(r'[\r\n]+', ' ', text).strip()

    # 3단계 시네마틱 샷 (1컷: 오프닝/환경 훅, 2컷: 매크로/핵심 피사체 전개, 3컷: 클라이맥스/텐션 박동)
    built_shots = [
        {
            "shot_num": 1,
            "title": f"01 Establishing Hook ({summary[:8]})",
            "korean_desc": f"{summary} - 배경 환경과 정적인 긴장감",
            "video_prompt": (
                f"In the vast atmospheric cinematic setting of '{summary}', "
                f"capturing the mood of '{clean_korean[:32]}'. "
                f"Wide establishing composition, deep volumetric shadows, dramatic crimson and neon ambient lighting, "
                f"slow creeping push-in camera movement, 8k cinematic, photorealistic, vertical 9:16, no text"
            ),
            "camera_motion": "Slow creeping push-in",
        },
        {
            "shot_num": 2,
            "title": f"02 Macro Subject Focus ({summary[:8]})",
            "korean_desc": f"{summary} - 핵심 피사체 클로즈업 및 전개",
            "video_prompt": (
                f"A tighter macro perspective focusing directly on the core frozen elements of '{summary}'. "
                f"Subtle digital particles and light reflections highlighting the tension of '{clean_korean[:32]}'. "
                f"Tightly tracking macro pan with delicate depth of field, moody rim lighting, "
                f"8k resolution, photorealistic, vertical 9:16, no text"
            ),
            "camera_motion": "Tightly tracking macro pan",
        },
        {
            "shot_num": 3,
            "title": f"03 Climax Tension & Pulse ({summary[:8]})",
            "korean_desc": f"{summary} - 클라이맥스 디테일과 극적 에너지",
            "video_prompt": (
                f"An extreme cinematic macro close-up representing the awakening climax of '{summary}'. "
                f"Dynamic energy shift, dramatic anamorphic horizontal lens flare, high contrast futuristic lighting, "
                f"impending motion shift, deep emotional tension, 8k cinematic masterpiece, vertical 9:16, no text"
            ),
            "camera_motion": "Dynamic subtle crash zoom with anamorphic flare",
        },
    ]

    s["shots"] = built_shots
    if not s.get("summary_ko"):
        s["summary_ko"] = summary
    if not s.get("prompt_en"):
        s["prompt_en"] = built_shots[0]["video_prompt"]
    if not s.get("camera_en"):
        s["camera_en"] = built_shots[0]["camera_motion"]

    dist_lines = []
    for sh in built_shots:
        dist_lines.append(f"[Shot {sh['shot_num']}]\n{sh['video_prompt']}")
    s["flow_distribution_prompt"] = "\n\n".join(dist_lines)

    return s


def enrich_segments_with_prompts_and_guides(
    segments: List[Dict],
    gemini_api_key: str = "",
) -> List[Dict]:
    """
    [REC] 세그먼트에는 구체적인 화면 녹화 가이드(OBS/창 대상)를 채우고,
    [GEN] 세그먼트에는 Flow 1씬 3컷(이미지 3장 / 비디오 프롬프트 3개) 및 [전체 프롬프트 일괄 분배]용 프롬프트를 생성합니다.
    """
    if not segments:
        return segments

    gen_items = [s for s in segments if s["type"] == "GEN"]
    rec_items = [s for s in segments if s["type"] == "REC"]

    if gemini_api_key:
        prompt = f"""당신은 헐리우드 최고 수준의 쇼츠 비주얼 디렉터이자 Flow(Shorts Story Studio) AI 영상 프롬프트 최고 권위자입니다.
아래 제공된 [REC: 화면 녹화] 구간들과 [GEN: AI 영상 생성] 구간들에 대해 각각 프로페셔널한 가이드를 작성해 주세요.

1. REC 구간 요구사항:
   - summary_ko: 10자 이내의 명료한 한글 대상 명칭 (예: '유튜브 스튜디오 분석 탭', '캡컷 PC 설정창')
   - target: 실제 녹화할 프로그램 또는 웹페이지 (예: 'Chrome - 유튜브 스튜디오 대시보드')
   - action: 마우스 조작 및 녹화 연출 (예: '시청 지속 시간 그래프로 마우스 이동 후 1.5배 줌인')
   - checklist: 녹화 전 확인해야 할 핵심 사항

2. GEN 구간 요구사항 (매우 중요: 1씬당 3개 컷!):
   - 각 GEN 구간(대본 1문장)은 Flow의 [하나의 씬(Scene)]에 해당합니다.
   - 각 씬마다 [3개의 컷(이미지 3장: Shot 1, Shot 2, Shot 3)]이 생성되므로, Flow의 [전체 프롬프트 일괄 분배]에 그대로 붙여넣을 수 있는 3개의 연속된 비디오 프롬프트(video_prompt)를 작성해야 합니다:
     * Shot 1 (0~4초 훅/환경): 씬의 배경과 환경을 드러내는 시선 강탈 와이드/설정 샷
     * Shot 2 (4~8초 전개/피사체): 핵심 피사체에 집중하는 타이트한 매크로/클로즈업 샷
     * Shot 3 (8~12초 클라이맥스): 극적인 에너지 변화나 디테일이 돋보이는 클라이맥스 다이내믹 샷
   - 각 샷의 video_prompt 규격:
     대본의 핵심 한글 키워드와 영문 시네마틱 묘사(카메라 구도, 조명, 분위기)를 자연스럽게 결합하여 20~35단어 내외로 작성.
     (규격: 8k cinematic, photorealistic, vertical 9:16, no text 포함)

=== REC 구간 대본 목록 ===
{json.dumps([{"id": s["id"], "text": s["text"]} for s in rec_items], ensure_ascii=False, indent=2)}

=== GEN 구간 대본 목록 ===
{json.dumps([{"id": s["id"], "text": s["text"]} for s in gen_items], ensure_ascii=False, indent=2)}

반드시 아래 JSON 포맷으로만 응답하세요:
{{
  "rec_guides": [
    {{
      "id": "REC-01",
      "summary_ko": "유튜브 스튜디오 분석",
      "target": "Chrome - 유튜브 스튜디오 대시보드",
      "action": "시청 지속 시간 그래프 마우스 가리키며 줌인",
      "checklist": "개인정보 마스킹 및 OBS 세로 모드 확인"
    }}
  ],
  "gen_prompts": [
    {{
      "id": "GEN-01",
      "summary_ko": "정체된 사이버스페이스",
      "shots": [
        {{
          "shot_num": 1,
          "title": "Frozen Red Stream",
          "korean_desc": "정체된 붉은빛 데이터 스트림과 고요한 침묵",
          "video_prompt": "In the vast depths of 붉은빛의 정체된 사이버스페이스, an oppressive silence hangs in the air. A prominent 일직선으로 굳어 있는 붉은빛 데이터 스트림 spans the entire frame, completely static and flat like a flatlined electrocardiogram. Microscopic digital dust floats frozen in air, moody crimson neon lighting, slow creeping push-in, 8k cinematic, photorealistic, vertical 9:16, no text",
          "camera_motion": "Slow creeping push-in"
        }},
        {{
          "shot_num": 2,
          "title": "Digital Dust Suspended",
          "korean_desc": "정지된 데이터 입자와 긴장감 넘치는 매크로 시선",
          "video_prompt": "A tighter macro perspective within 붉은빛의 정체된 사이버스페이스 centers on the frozen edge of the 일직선으로 굳어 있는 붉은빛 데이터 스트림. Suspended digital particles gleam faintly under the dim crimson glow, entirely paralyzed in mid-air, volumetric red haze, 8k photorealistic, vertical 9:16, no text",
          "camera_motion": "Tightly tracking macro pan"
        }},
        {{
          "shot_num": 3,
          "title": "Subtle Pulse Awakening",
          "korean_desc": "미세한 박동의 시작과 부활의 조짐",
          "video_prompt": "An extreme cinematic macro close-up of the flat red line as a tiny microscopic heartbeat spike begins to tremble and pulse forward, glowing neon cyan spark igniting across the surface, dramatic anamorphic lens flare, deep tension, 8k resolution, vertical 9:16, no text",
          "camera_motion": "Dynamic crash zoom into the pulsing spark"
        }}
      ]
    }}
  ]
}}
"""
        resp_json = _call_gemini_api(prompt, gemini_api_key, json_mode=True)
        if resp_json:
            try:
                data = json.loads(resp_json)
                rec_map = {item["id"]: item for item in data.get("rec_guides", [])}
                gen_map = {item["id"]: item for item in data.get("gen_prompts", [])}

                for s in segments:
                    if s["type"] == "REC" and s["id"] in rec_map:
                        rm = rec_map[s["id"]]
                        s["summary_ko"] = rm.get("summary_ko", s.get("summary_ko", ""))
                        s["target"] = rm.get("target", "화면 녹화 창")
                        s["action"] = rm.get("action", "")
                        s["checklist"] = rm.get("checklist", "")
                        s["guide"] = f"[{s.get('target', '')}] {s.get('action', '')}"
                    elif s["type"] == "GEN" and s["id"] in gen_map:
                        gm = gen_map[s["id"]]
                        s["summary_ko"] = gm.get("summary_ko", s.get("summary_ko", ""))
                        g_shots = gm.get("shots", [])
                        if g_shots and len(g_shots) >= 3:
                            s["shots"] = g_shots
                            s["prompt_en"] = g_shots[0].get("video_prompt", "")
                            s["camera_en"] = g_shots[0].get("camera_motion", "Slow push-in")
                            dist_lines = []
                            for sh in g_shots:
                                dist_lines.append(f"[Shot {sh.get('shot_num', 1)}]\n{sh.get('video_prompt', '').strip()}")
                            s["flow_distribution_prompt"] = "\n\n".join(dist_lines)
            except Exception as e:
                print(f"[rec_gen_pipeline] enrich error: {e}")

    # 기본값 및 3컷 보정
    for s in segments:
        if s["type"] == "REC":
            if not s.get("summary_ko"):
                s["summary_ko"] = "화면 녹화 구간"
            if not s.get("target"):
                s["target"] = "화면 캡처 / 브라우저 창"
                s["action"] = "해당 대본을 설명하는 관련 페이지 또는 데이터 화면 녹화"
                s["checklist"] = "OBS 1080x1920 세로 모드 또는 1920x1080 줌 크롭 확인"
                s["guide"] = f"[{s['target']}] {s['action']}"
        elif s["type"] == "GEN":
            _ensure_segment_3shots(s)

    return segments


def calculate_segment_timecodes(
    segments: List[Dict],
    total_audio_duration: float,
) -> List[Dict]:
    """
    전체 오디오 재생 시간을 기준으로 각 세그먼트의 글자 수 비율에 맞추어
    타임코드(시작초, 종료초, 텍스트)를 정밀 계산하여 할당합니다.
    """
    if not segments:
        return segments

    total_chars = sum(max(1, len(re.sub(r'\s+', '', s["text"]))) for s in segments)
    current_time = 0.0

    for i, s in enumerate(segments):
        c_len = max(1, len(re.sub(r'\s+', '', s["text"])))
        if total_audio_duration > 0:
            dur = total_audio_duration * (c_len / total_chars)
        else:
            dur = c_len / 7.5

        start_sec = round(current_time, 2)
        end_sec = round(current_time + dur, 2)
        if i == len(segments) - 1 and total_audio_duration > 0:
            end_sec = round(total_audio_duration, 2)

        s["start_sec"] = start_sec
        s["end_sec"] = end_sec
        s["duration_sec"] = round(end_sec - start_sec, 2)
        s["start_tc"] = format_seconds_to_timecode(start_sec)
        s["end_tc"] = format_seconds_to_timecode(end_sec)
        s["timecode_range"] = f"{s['start_tc']} ~ {s['end_tc']} ({s['duration_sec']:.1f}초)"

        current_time = end_sec

    return segments


def generate_flow_storyboard_script(segments: List[Dict], output_path: str = "") -> str:
    """
    Flow 스토리보드(Storyboard) 전용 일괄 붙여넣기 스크립트 생성.
    Flow의 [스토리보드] 또는 [각본] 창에 붙여넣으면 각 씬마다 3컷(이미지 3장)이 한 번에 자동 생성됩니다.
    하단에는 각 씬의 [전체 프롬프트 일괄 분배] 창에 붙여넣을 3컷 비디오 프롬프트가 정렬되어 있습니다.
    """
    gen_segs = [s for s in segments if s["type"] == "GEN"]
    if not gen_segs:
        return ""

    lines = []
    lines.append("/* Flow 스토리보드(Storyboard) 전용 각본 (1씬 3컷 규격) */")
    lines.append("/* Flow 사이트의 [스토리보드] 창에 그대로 붙여넣으면 각 씬마다 3개의 키프레임 이미지가 일괄 생성됩니다. */\n")

    for idx, s in enumerate(gen_segs, 1):
        _ensure_segment_3shots(s)
        clean_name = re.sub(r'[^\w\s]', '', s.get("summary_ko", "SCENE")).strip().upper()
        tc = s.get("timecode_range", "")
        lines.append(f"### INT. SCENE {idx} - {s['id']} {clean_name} ({tc})")
        shots = s.get("shots", [])
        for sh in shots:
            sh_num = sh.get("shot_num", 1)
            vp = sh.get("video_prompt", "").strip() or sh.get("visual_prompt_en", "").strip()
            lines.append(f"Shot {sh_num}: {vp}")
        lines.append("")

    lines.append("=" * 72)
    lines.append("=== [Flow 각 씬별 '전체 프롬프트 일괄 분배' 붙여넣기 텍스트 모음] ===")
    lines.append("=== (각 씬 상단의 [전체 프롬프트 일괄 분배] 버튼을 누르고 아래 해당 씬의 3컷 블록을 붙여넣으세요) ===")
    lines.append("=" * 72)
    for idx, s in enumerate(gen_segs, 1):
        lines.append(f"\n▼▼▼ [Scene {idx} ({s['id']}) - {s.get('summary_ko', '')}] ▼▼▼")
        lines.append(s.get("flow_distribution_prompt", ""))
        lines.append("")

    content = "\n".join(lines)
    if output_path:
        os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(content)

    return content


def generate_ai_prompts_file(segments: List[Dict], output_path: str) -> str:
    """[GEN: AI 비디오] 씬별 1씬 3컷 비디오 프롬프트 및 Flow 일괄 분배용 목록 파일 생성"""
    gen_segs = [s for s in segments if s["type"] == "GEN"]
    if not gen_segs:
        return ""

    lines = [
        "=" * 72,
        "  🤖 [GEN] Flow AI 영상 씬별 3컷 비디오 프롬프트 목록",
        "=" * 72,
        f"총 AI 영상 씬(Scene): {len(gen_segs)}개 (씬당 3컷 = 총 {len(gen_segs)*3}개 비디오)",
        "추천 도구: Flow (Shorts Story Studio) / Runway Gen-3 / Kling 1.5 / Luma",
        "화면 비율: 9:16 (Vertical Shorts)",
        "💡 Flow 반자동 사용법:",
        "   1) Flow 스토리보드에서 각 씬의 [전체 프롬프트 일괄 분배] 버튼을 누릅니다.",
        "   2) 아래 해당 씬의 [Flow 전체 프롬프트 일괄 분배용 텍스트]를 복사해서 붙여넣습니다.",
        "   3) 컷 01, 컷 02, 컷 03에 프롬프트가 자동 분배되면 [비디오 (360p)]를 누릅니다.",
        "-" * 72,
        "",
    ]

    for idx, s in enumerate(gen_segs, 1):
        _ensure_segment_3shots(s)
        clean_name = s.get("summary_ko", "AI 영상")
        tc = s.get("timecode_range", "")
        lines.append(f"■ [Scene {idx} - {s['id']}] {clean_name} ({tc})")
        lines.append(f"  * 매칭 대본: \"{s.get('text', '')}\"")
        lines.append("")
        lines.append("  ┌── 📋 Flow [전체 프롬프트 일괄 분배] 전용 복사 블록 ──┐")
        for sh in s.get("shots", []):
            lines.append(f"  [Shot {sh.get('shot_num', 1)}]")
            lines.append(f"  {sh.get('video_prompt', '')}")
            lines.append("")
        lines.append("  └────────────────────────────────────────────────┘")
        lines.append("")
        lines.append("  * 3컷 개별 상세:")
        for sh in s.get("shots", []):
            lines.append(f"    - 컷 0{sh.get('shot_num', 1)} ({sh.get('title', '')}): {sh.get('korean_desc', '')}")
            lines.append(f"      프롬프트: {sh.get('video_prompt', '')}")
            lines.append(f"      카메라 무빙: {sh.get('camera_motion', '')}")
        lines.append("")
        lines.append("-" * 72)
        lines.append("")

    content = "\n".join(lines)
    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(content)

    return content


def generate_rec_checklist_file(segments: List[Dict], output_path: str) -> str:
    """[REC: 화면 녹화] 체크리스트 텍스트 파일 생성"""
    rec_segs = [s for s in segments if s["type"] == "REC"]

    lines = [
        "=" * 70,
        "  📹 [REC] 화면 녹화 작업 체크리스트 & 촬영 가이드",
        "=" * 70,
        f"총 녹화 구간: {len(rec_segs)}개 클립",
        "권장 해상도: 1080x1920 (쇼츠 세로 모드) 또는 1920x1080 녹화 후 캡컷에서 크롭",
        "-" * 70,
        "",
    ]

    for s in rec_segs:
        tc = s.get("timecode_range", "")
        lines.append(f"■ [{s['id']}] {s.get('summary_ko', '화면 녹화')} ({tc})")
        lines.append(f"  * 녹화 대상: {s.get('target', '화면/브라우저 창')}")
        lines.append(f"  * 연출 조작: {s.get('action', '핵심 화면 시연')}")
        if s.get("checklist"):
            lines.append(f"  * 사전 체크: {s.get('checklist')}")
        lines.append(f"  * 매칭 대본: \"{s['text']}\"")
        lines.append(f"  [ ] 녹화 완료 체크 (파일명: {s['id']}.mp4)")
        lines.append("")

    content = "\n".join(lines)
    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(content)

    return output_path


def generate_capcut_timeline_guide_file(segments: List[Dict], output_path: str, total_duration: float = 0.0) -> str:
    """캡컷(CapCut) 최종 조립용 타임라인 배치표 텍스트 파일 생성"""
    lines = [
        "=" * 80,
        "  ✂️ 캡컷(CapCut) 최종 조립용 타임라인 배치표 (타임코드 매핑 가이드)",
        "=" * 80,
        f"총 영상 길이: {format_seconds_to_timecode(total_duration)} ({total_duration:.1f}초) | 총 클립 수: {len(segments)}개",
        "",
        "💡 [캡컷 초고속 3단계 조립법]",
        "  1. 캡컷을 켜고 'narration.mp3'와 'subtitles.srt'를 오디오/자막 트랙에 드래그합니다.",
        "  2. 아래 타임라인 배치표 순서대로 비디오 트랙 1번에 REC 녹화 파일과 GEN AI 영상 파일을 배치합니다.",
        "  3. 각 클립의 재생 길이를 아래 표시된 '지속 시간(초)'에 맞춰 잘라내고 배치하면 끝!",
        "-" * 80,
        "",
        f"{'순번':<4} | {'타임코드':<18} | {'구분':<6} | {'클립 ID':<8} | {'클립 내용 / 연출':<28} | {'매칭 대본 요약'}",
        "-" * 80,
    ]

    for idx, s in enumerate(segments, 1):
        s_type_kr = "📹녹화" if s["type"] == "REC" else "🤖AI영상"
        tc = f"{s.get('start_tc','00:00')} ~ {s.get('end_tc','00:00')} ({s.get('duration_sec', 0):.1f}s)"
        desc = s.get("summary_ko", "") or s.get("target", "") or s["text"][:15]
        clean_desc = desc[:26]
        sub_text = s["text"].replace("\n", " ")[:25]
        lines.append(f"{idx:<4} | {tc:<18} | {s_type_kr:<6} | {s['id']:<8} | {clean_desc:<28} | \"{sub_text}...\"")

    lines.append("-" * 80)
    lines.append("")
    lines.append("■ 클립 파일명 정리 추천:")
    for s in segments:
        lines.append(f"  - {s['id']}.mp4  ({s['type']})  -->  {s.get('start_tc','00:00')} 위치에 스냅 배치")

    content = "\n".join(lines)
    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(content)

    return output_path


def run_dual_pipeline(
    script_text: str,
    output_dir: str,
    gemini_api_key: str = "",
    voice: str = "ko-KR-InJoonNeural",
    rate: str = "+20%",
    progress_callback = None,
    engine: str = "edge-tts",
    qwen_mode: str = "custom_voice",
    qwen_speaker: str = "Sohee",
    qwen_instruct: str = "",
    qwen_model_size: str = "0.6B",
    qwen_ref_audio: str = "",
    qwen_ref_text: str = "",
) -> Dict:
    """
    [REC/GEN 이원화 전체 파이프라인 일괄 실행기]
    1. 대본 태그([REC], [GEN]) 제거 후 순수 텍스트로 TTS(narration.mp3) 및 자막(subtitles.srt) 일괄 생성
    2. 대본 분석 및 REC vs GEN 구간 이원화 분리 (태그 또는 LLM 문맥 기반)
    3. 오디오 재생 시간 기준으로 정확한 타임코드 매핑
    4. 4대 핵심 결과물 파일 생성:
       - Flow_스토리보드_일괄스크립트.txt
       - 화면_녹화_체크리스트.txt
       - 캡컷_타임라인_배치표.txt
    """
    os.makedirs(output_dir, exist_ok=True)

    if progress_callback:
        progress_callback("1/4", "대본 분석 및 [REC:화면녹화] vs [GEN:AI생성] 이원화 분리 중...")

    # 1. REC / GEN 세그먼트 분리
    segments = parse_script_rec_gen(script_text, gemini_api_key=gemini_api_key)
    if not segments:
        raise ValueError("대본 분석 결과 유효한 문장이 없습니다.")

    # 프롬프트 및 가이드 보강 (Gemini 키 있으면 고품질 생성, 없으면 자동 폴백)
    if progress_callback:
        progress_callback("2/4", "녹화 가이드 및 Flow 스토리보드 영문 프롬프트 생성 중...")
    segments = enrich_segments_with_prompts_and_guides(segments, gemini_api_key=gemini_api_key)

    # 2. TTS 음성 합성용 순수 텍스트 생성 (태그 완전 제거)
    clean_tts_script = strip_pipeline_tags(script_text)

    if progress_callback:
        progress_callback("3/4", "순수 대본 기반 고음질 나레이션(TTS) 및 1줄 싱크 자막 합성 중...")

    tts_result = generate_narration_from_full_script(
        script_text=clean_tts_script,
        output_dir=output_dir,
        voice=voice,
        rate=rate,
        title="쇼츠 나레이션",
        progress_callback=None,
        engine=engine,
        qwen_mode=qwen_mode,
        qwen_speaker=qwen_speaker,
        qwen_instruct=qwen_instruct,
        qwen_model_size=qwen_model_size,
        qwen_ref_audio=qwen_ref_audio,
        qwen_ref_text=qwen_ref_text,
    )

    total_duration = tts_result.get("total_duration", 0.0)

    # 3. 타임코드 매핑
    segments = calculate_segment_timecodes(segments, total_duration)

    if progress_callback:
        progress_callback("4/4", "Flow 스토리보드 스크립트, 체크리스트, 캡컷 배치 가이드 파일 생성 중...")

    # 4. 파일 출력
    flow_script_path = os.path.join(output_dir, "Flow_스토리보드_일괄스크립트.txt")
    ai_prompts_path = os.path.join(output_dir, "AI_영상_프롬프트_목록.txt")
    rec_checklist_path = os.path.join(output_dir, "화면_녹화_체크리스트.txt")
    capcut_guide_path = os.path.join(output_dir, "캡컷_타임라인_배치표.txt")

    flow_script_content = generate_flow_storyboard_script(segments, flow_script_path)
    generate_ai_prompts_file(segments, ai_prompts_path)
    generate_rec_checklist_file(segments, rec_checklist_path)
    generate_capcut_timeline_guide_file(segments, capcut_guide_path, total_duration=total_duration)

    # 구조 데이터 저장
    with open(os.path.join(output_dir, "대본_REC_GEN_구조.json"), "w", encoding="utf-8") as f:
        json.dump(segments, f, ensure_ascii=False, indent=2)

    return {
        "segments": segments,
        "total_duration": total_duration,
        "narration_path": tts_result.get("narration_path"),
        "subtitles_srt_path": tts_result.get("subtitles_srt_path"),
        "flow_script_path": flow_script_path,
        "flow_script_content": flow_script_content,
        "ai_prompts_path": ai_prompts_path,
        "rec_checklist_path": rec_checklist_path,
        "capcut_guide_path": capcut_guide_path,
        "rec_count": len([s for s in segments if s["type"] == "REC"]),
        "gen_count": len([s for s in segments if s["type"] == "GEN"]),
    }
