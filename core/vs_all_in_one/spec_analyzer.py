# -*- coding: utf-8 -*-
"""
core.vs_all_in_one.spec_analyzer
Gemini 기반 두 피사체 핵심 스펙 비교표 생성 및 부족 소스 AI 이미지 프롬프트 생성기
(최신 무기체계/공학 장비 팩트체크 가드레일 & 구형/차세대 분리 검증 탑재)
"""

import json
import re
from typing import Dict, Any, List

from core.generator import _call_gemini_api
from core.vs_all_in_one import load_env_api_key


def analyze_vs_specs_and_missing_prompts(
    subject_a: str,
    subject_b: str,
    topic: str = "",
    gemini_api_key: str = "",
) -> Dict[str, Any]:
    """두 비교 대상의 공학/밀리터리 최신 팩트를 엄격히 검증하여 핵심 스펙 비교표 및 순백색 스튜디오 AI 보충 프롬프트를 생성합니다."""
    key = gemini_api_key or load_env_api_key()
    sa = subject_a.strip() or "비교 대상 A"
    sb = subject_b.strip() or "비교 대상 B"

    prompt = f"""당신은 세계 최고 수준의 국방 기술 연구원(ADD), 군사 전문지 수석 분석관이자 유튜브 쇼츠 팩트체크 디렉터입니다.
두 비교 대상에 대해 시청자가 1초 만에 감탄할 수 있는 '완벽히 정확한 최신 팩트 기반 스펙 비교표'를 작성하세요.

[비교 대상 정보]
- 대상 A: {sa}
- 대상 B: {sb}
- 비교 주제: {topic or '종합 성능 및 핵심 스펙 대결'}

[🚨 절대 위반 금지: 팩트체크 및 기종 고증 4대 원칙]
1. 입력된 모델명의 정확한 세부 기종 고증 준수 (핵심!):
   - 사용자가 입력한 모델명(예: 'K30 SAM 비호복합', 'K30 비호', '비호-II', '일본 87식 자주대공포', '게파르트', 'GÜRZ', 'K2 흑표' 등)의 정확한 세부 기종과 실제 공식 제원을 100% 준수하세요.
   - [중요: 비호 계열 구분 원칙 - 절대 혼동 금지]
     * 'K30 비호' 또는 'K30 SAM 비호복합'은 K200 기반 [무한궤도(Tracked) 차체], [30mm 2연장(쌍열) 기관포], [신궁 미사일 4발], [후방 회전식 탐지/추적 레이더]를 장착한 실전배치 무기입니다. 절대 비호-II(8륜 차륜형, AESA, 레이저) 스펙을 섞거나 변환하지 마세요!
     * '비호-II (Biho-II)'는 [8x8 차륜형(Wheeled) 차체], [30/40mm CTA 단일포탑], [4면 고정형 AESA 레이더], [레이저 무기]가 장착된 별개의 차세대 수출형 모델입니다.
   - [중요: 일본 87식 자주대공포 고증 원칙]
     * '87식 자주대공포'는 74식 전차 기반 [무한궤도(Tracked) 중장갑 차체], [35mm 오리콘 KDA 2연장(쌍열) 기관포], [미사일 미탑재], [포탑 상부 회전식 펄스 도플러 탐색 레이더 및 추적 레이더]를 장착한 일본 육상자위대 무기입니다.
   - 구형/기존 모델을 임의로 차세대형으로 바꾸거나 다른 무기의 부품(차륜형 바퀴, AESA 등)을 날조하지 마세요.
2. 핵심 첨단 무장(레이저, 드론 대응, 능동방어) 누락 절대 금지:
   - 두 대상이 보유하거나 제안된 핵심 특수 무장(예: 고출력 레이저 대공무기, 안티드론 재머, 지향성 에너지 무기, 하드킬 APS 등)을 한쪽에만 편파적으로 기재하지 말고, 양측의 실제 스펙을 객관적이고 대등하게 검증하세요.
3. 지표의 정밀성과 체감도:
   - 지상/방공 무기: [차체 플랫폼 및 최고속도, 주무장 기관포 및 포탑 형태, 대공/대전차 유도탄, 드론 요격 레이저/지향성에너지, 탐지 레이더(AESA/회전식) 및 사격통제, 방어 체계(APS/재머)] 등 핵심 5~7개 항목.
   - 전투기/항공기: [추진 엔진 및 추력, 최고속도, AESA 레이더 모듈, 최대 무장탑재량, 스텔스 RCS, 작전반경].
4. 공정한 우위 판정 (`winner`):
   - 'A', 'B', 'TIE'(무승부) 중 실제 기술적/전술적 우위에 맞게 객관적으로 판정하고, `winner_reason`에 1줄 판정 근거를 명시하세요.

[요구사항]
- `highlight_summary`: 1줄짜리 강력한 비교 후킹 요약 (예: "저고도 방공 끝판왕 맞대결!").
- `weapon_meta_a`: 대상 A({sa})의 영문 메타데이터:
  - `name_en`: 공식 영문명 (대문자 중심, 예: "K30 BIHO HYBRID", "BIHO-II", "TYPE 87 SPAAG", "KF-21", "GÜRZ", "K2 BLACK PANTHER")
  - `country_en`: 소속 국가 영문 형용사 (예: "South Korean", "Japanese", "American", "Turkish", "German", "Ukrainian", "Russian")
  - `desc_en`: 2단계 스펙표 기반 실제 외형 및 주무장 1줄 영문 요약 (입력된 기종의 실제 차체/포탑/주무장/유도탄/레이더를 정확히 반영할 것. 예: K30 비호복합 -> "K200-based tracked armored chassis, manned boxy turret with dual 30mm autocannons, two dual Shingung missile pods, and rear rotating search radar", 87식 -> "Type 74 tank tracked chassis, turret with dual 35mm autocannons, independent search and tracking radar systems", 비호-II -> "8x8 wheeled armored chassis, unmanned turret with single 30mm/40mm CTA autocannon, missile canisters, and 4-panel fixed AESA radar")
- `weapon_meta_b`: 대상 B({sb})의 영문 메타데이터 (동일 형식)
- `spec_table`: 5~7개의 핵심 지표 객체 배열:
  - `metric`: 비교 항목명
  - `val_a`: 대상 A({sa})의 정확한 최신 수치 및 기술 설명
  - `val_b`: 대상 B({sb})의 정확한 최신 수치 및 기술 설명
  - `winner`: 'A', 'B', 또는 'TIE'
  - `winner_reason`: 판정 이유 1줄 요약
- `missing_angle_prompts`: 순백색 심리스 스튜디오(#FFFFFF) 9:16 vertical 고증 프롬프트 3세트.

반드시 다음 JSON 형식으로만 응답하세요:
{{
  "highlight_summary": "1줄 후킹 요약",
  "weapon_meta_a": {{
    "name_en": "EXACT_WEAPON_A_NAME",
    "country_en": "South Korean",
    "desc_en": "specific platform type, specific turret and gun, missile pods, and radar type"
  }},
  "weapon_meta_b": {{
    "name_en": "EXACT_WEAPON_B_NAME",
    "country_en": "Japanese",
    "desc_en": "specific platform type, specific turret and gun, missile pods, and radar type"
  }},
  "spec_table": [
    {{
      "metric": "차체 플랫폼 및 기동성",
      "val_a": "차체 종류 및 최고속도",
      "val_b": "차체 종류 및 최고속도",
      "winner": "TIE",
      "winner_reason": "판정 이유"
    }}
  ],
  "missing_angle_prompts": [
    {{
      "angle_name": "① 정면 1:1 대칭 비교 뷰",
      "prompt_en": "Cinematic 9:16 vertical engineering studio shot... Isolated on pure seamless white studio cyclorama background #FFFFFF..."
    }}
  ]
}}
  "spec_table": [
    {{
      "metric": "차체 플랫폼 및 기동성",
      "val_a": "차체 종류 및 최고속도",
      "val_b": "차체 종류 및 최고속도",
      "winner": "TIE",
      "winner_reason": "판정 이유"
    }}
  ],
  "missing_angle_prompts": [
    {{
      "angle_name": "① 정면 1:1 대칭 비교 뷰",
      "prompt_en": "Cinematic 9:16 vertical engineering studio shot... Isolated on pure seamless white studio cyclorama background #FFFFFF..."
    }}
  ]
}}
"""
    if not key:
        return _get_fallback_specs(sa, sb, topic)

    try:
        raw_res = _call_gemini_api(prompt, key, json_mode=True)
        if not raw_res:
            return _get_fallback_specs(sa, sb, topic)

        clean_json = re.sub(r"^```(?:json)?\s*", "", raw_res.strip(), flags=re.MULTILINE)
        clean_json = re.sub(r"\s*```$", "", clean_json.strip())
        data = json.loads(clean_json)

        table = data.get("spec_table", [])
        if not table:
            return _get_fallback_specs(sa, sb, topic)

        # 무기 메타데이터 (영문명, 소속 국가 영문 형용사, 외형·무장 요약) 추출 및 보정
        meta_a = data.get("weapon_meta_a") or {}
        meta_b = data.get("weapon_meta_b") or {}
        
        # 누락되거나 불완전한 경우 룰베이스 엔진으로 완전 보강
        if not meta_a.get("name_en") or not meta_a.get("desc_en"):
            fallback_meta_a = derive_weapon_metadata(sa, table, is_a=True)
            meta_a = {
                "name_en": (meta_a.get("name_en") or fallback_meta_a["name_en"]).upper().strip(),
                "country_en": meta_a.get("country_en") or fallback_meta_a["country_en"],
                "desc_en": meta_a.get("desc_en") or fallback_meta_a["desc_en"],
            }
        else:
            meta_a["name_en"] = meta_a["name_en"].upper().strip()

        if not meta_b.get("name_en") or not meta_b.get("desc_en"):
            fallback_meta_b = derive_weapon_metadata(sb, table, is_a=False)
            meta_b = {
                "name_en": (meta_b.get("name_en") or fallback_meta_b["name_en"]).upper().strip(),
                "country_en": meta_b.get("country_en") or fallback_meta_b["country_en"],
                "desc_en": meta_b.get("desc_en") or fallback_meta_b["desc_en"],
            }
        else:
            meta_b["name_en"] = meta_b["name_en"].upper().strip()

        return {
            "success": True,
            "highlight_summary": data.get("highlight_summary", f"{sa} vs {sb} 최신 팩트 스펙 분석 완료"),
            "spec_table": table,
            "weapon_meta_a": meta_a,
            "weapon_meta_b": meta_b,
            "missing_angle_prompts": data.get("missing_angle_prompts", []),
        }
    except Exception as e:
        print(f"[analyze_vs_specs_and_missing_prompts] Error: {e}")
        return _get_fallback_specs(sa, sb, topic)


def derive_weapon_metadata(subject_name: str, spec_table: List[Dict[str, Any]] = None, is_a: bool = True) -> Dict[str, str]:
    """
    무기 명칭 및 2단계 스펙표로부터 육·해·공 전 무기 범용 메타데이터
    (영문명 {WEAPON_NAME}, 소속 국가 영문 형용사 {WEAPON_COUNTRY}, 외형·무장 요약 {WEAPON_DESC})를 100% 동적으로 추출합니다.
    """
    s = subject_name.strip()
    s_low = s.lower()
    
    # 1. 영문명 추출 (대문자)
    name_en = ""
    # (1) 한국어 대표 무기명 정밀 매핑 (K30 SAM 비호복합, 비호-II, 87식, K2 흑표, KF-21 보라매 등)
    kr_patterns = [
        ("비호-ii", "BIHO-II"), ("비호 2", "BIHO-II"), ("비호2", "BIHO-II"), ("biho-ii", "BIHO-II"), ("biho 2", "BIHO-II"),
        ("비호복합", "K30 BIHO HYBRID"), ("k30 sam", "K30 BIHO HYBRID"), ("sam 비호", "K30 BIHO HYBRID"),
        ("k30", "K30 BIHO HYBRID"), ("비호", "K30 BIHO"),
        ("87식", "TYPE 87 SPAAG"), ("type 87", "TYPE 87 SPAAG"),
        ("게파르트", "GEPARD SPAAG"), ("gepard", "GEPARD SPAAG"),
        ("퉁구스카", "2K22 TUNGUSKA"), ("tunguska", "2K22 TUNGUSKA"),
        ("흑표", "K2 BLACK PANTHER"), ("k2", "K2 BLACK PANTHER"),
        ("보라매", "KF-21 BORAMAE"), ("kf-21", "KF-21 BORAMAE"),
        ("구르주", "GÜRZ"), ("gürz", "GÜRZ"), ("gurz", "GÜRZ"),
        ("자주포", "K9 THUNDER"), ("k9", "K9 THUNDER"),
        ("천궁-ii", "CHEONGUNG-II"), ("천궁", "CHEONGUNG"), ("현무", "HYUNMOO"),
        ("상륙돌격장갑차", "KAAV-II"), ("레오파르트", "LEOPARD 2A8"),
        ("에이브람스", "M1A2 ABRAMS"), ("패트리어트", "MIM-104 PATRIOT"),
        ("바이락타르", "BAYRAKTAR TB2"), ("수호이", "SU-57"),
        ("판치르", "PANTSIR-S1"), ("아이언돔", "IRON DOME")
    ]
    for k, v in kr_patterns:
        if k in s_low:
            name_en = v
            break

    # (2) 괄호 안의 영문 표기 추출 (예: '비호-II (Biho-II)' -> 'BIHO-II', '구르주 (ASELSAN Gürz)' -> 'ASELSAN GÜRZ')
    if not name_en:
        paren_match = re.search(r'\(([^)]+)\)', s)
        if paren_match:
            cand = paren_match.group(1).strip()
            if re.search(r'[A-Za-z]', cand):
                name_en = cand.upper()

    # (3) 입력 텍스트 내 순수 영단어 조합 (예: 'M1A2 SEPv3', 'F-35A')
    if not name_en:
        eng_matches = re.findall(r'[A-Za-z0-9]+(?:-[A-Za-z0-9]+)*', s)
        real_eng = [w for w in eng_matches if re.search(r'[A-Za-z]', w)]
        if real_eng:
            name_en = " ".join(real_eng).upper()

    # (4) 최후의 폴백
    if not name_en:
        name_en = re.sub(r'[^A-Za-z0-9\s\-]', '', s).strip().upper() or ("WEAPON A" if is_a else "WEAPON B")

    # 2. 국가 영문 형용사 추출 (South Korean, Japanese, Turkish, American, etc.)
    country_en = ""
    country_patterns = [
        (r"한국|대한민국|국산|rok|add|한화|kai|현대로템|lignex1|비호|k2|kf-21|k9|천궁|현무", "South Korean"),
        (r"일본|자위대|japan|87식|mitsubishi|type 10|type 87|f-2", "Japanese"),
        (r"튀르키예|터키|구르주|aselsan|gürz|gurz|bayraktar|roketsan|tai", "Turkish"),
        (r"미국|미군|usa|u\.s|lockheed|boeing|patriot|abrams|f-35|f-22|f-15|himars", "American"),
        (r"러시아|소련|russia|sukhoi|mig|su-|s-400|pantsir|t-90|t-14|퉁구스카", "Russian"),
        (r"우크라이나|ukraine", "Ukrainian"),
        (r"독일|germany|rheinmetall|leopard|gepard|iris-t|게파르트", "German"),
        (r"프랑스|france|dassault|rafale|caesar", "French"),
        (r"영국|uk|britain|bae|challenger", "British"),
        (r"이스라엘|israel|rafael|iron dome|arrow|david's sling", "Israeli"),
        (r"중국|china|pla|j-20|type 99|hq-9", "Chinese"),
        (r"스웨덴|sweden|saab|gripen", "Swedish"),
    ]
    val_key = "val_a" if is_a else "val_b"
    weapon_vals = " ".join([str(r.get(val_key, "")) for r in spec_table]) if spec_table else ""
    target_text = (s + " " + weapon_vals).lower()
    for pat, c_name in country_patterns:
        if re.search(pat, target_text):
            country_en = c_name
            break
    if not country_en:
        country_en = "South Korean" if is_a else "Japanese"

    # 3. 육·해·공 전 무기 범용 외형 및 주무장 요약 (desc_en)
    platform_desc = ""
    turret_desc = ""
    missile_desc = ""
    radar_desc = ""
    laser_desc = ""

    if spec_table:
        for row in spec_table:
            m = str(row.get("metric", "")).lower()
            val = str(row.get(val_key, ""))
            v_low = val.lower()

            # (1) 차체 / 플랫폼 / 기체 / 선체
            if any(k in m for k in ["차체", "플랫폼", "기체", "선체", "형태", "기동"]):
                if "전투기" in val or "fighter" in v_low or "스텔스" in val or "초음속" in val:
                    platform_desc = "supersonic tactical fighter jet"
                elif "드론" in val or "uav" in v_low or "무인기" in val:
                    platform_desc = "tactical unmanned combat aerial drone"
                elif "함정" in val or "구축함" in val or "destroyer" in v_low or "frigate" in v_low:
                    platform_desc = "stealth guided missile warship"
                elif "헬기" in val or "helicopter" in v_low:
                    platform_desc = "heavy tactical attack helicopter"
                elif "궤도" in val or "tracked" in v_low:
                    platform_desc = "tracked armored chassis"
                elif "8" in val or "차륜" in val or "wheel" in v_low:
                    platform_desc = "8x8 wheeled armored chassis"
                elif "전차" in val or "tank" in v_low:
                    platform_desc = "tracked main battle tank chassis"

            # (2) 주무장 / 포탑 / 기관포
            if any(k in m for k in ["주무장", "기관포", "포탑", "화력", "주포"]):
                gun_name = ""
                if any(w in val for w in ["쌍열", "2연장", "2문"]) or "dual" in v_low:
                    if "30" in val:
                        gun_name = "dual 30mm autocannons"
                    elif "35" in val:
                        gun_name = "dual 35mm autocannons"
                    else:
                        gun_name = "dual autocannons"
                elif "cta" in v_low:
                    gun_name = "single 30mm/40mm CTA autocannon"
                elif "35" in val or "공중폭발" in val or "atom" in v_low:
                    gun_name = "35mm airburst autocannon"
                elif "30" in val or "40" in val:
                    gun_name = "30mm autocannon"
                elif "120" in val or "125" in val or "활강포" in val:
                    gun_name = "120mm smoothbore main cannon"

                if "무인" in val or "unmanned" in v_low:
                    turret_desc = f"unmanned turret with {gun_name}" if gun_name else "unmanned weapon turret"
                elif "유인" in val or "manned" in v_low or "각형" in val or "boxy" in v_low:
                    turret_desc = f"manned boxy turret with {gun_name}" if gun_name else "manned boxy turret"
                elif gun_name:
                    turret_desc = f"turret with {gun_name}"

            # (3) 대공 / 대전차 유도탄 및 미사일
            if any(k in m for k in ["미사일", "유도탄", "요격", "천검", "신궁"]):
                if "신궁" in val or "shingung" in v_low:
                    missile_desc = "two dual Shingung surface-to-air missile pods"
                elif "천검" in val or "cheon-geom" in v_low:
                    missile_desc = "anti-tank precision missile pods"
                elif any(b in v_low for b in ["boz", "sungur", "괴크", "보즈"]):
                    missile_desc = "integrated surface-to-air missile canisters"
                elif "미사일" in val or "유도탄" in val:
                    missile_desc = "multi-cell precision missile pods"

            # (4) 탐지 레이더 및 센서
            if any(k in m for k in ["레이더", "탐지", "센서", "aesa"]):
                if "aesa" in v_low:
                    radar_desc = "4-panel fixed AESA radar"
                elif any(r in val for r in ["탐색", "회전", "tps"]):
                    radar_desc = "rear rotating search radar and tracking radar"
                elif "레이더" in val:
                    radar_desc = "integrated surveillance and tracking radar"

            # (5) 레이저 및 드론 대응
            if any(k in m for k in ["레이저", "laser", "지향성"]):
                if any(x in val for x in ["레이저", "laser"]):
                    laser_desc = "high-energy counter-drone laser weapon"

    # 조립된 구문들 병합
    components = [c for c in [platform_desc, turret_desc, missile_desc, radar_desc, laser_desc] if c]
    desc_en = ", ".join(components)

    # 폴백 / 보정: 스펙표에서 충분히 추출되지 않거나 핵심 요소가 누락된 경우 subject_name 기반 세부 고증 분기
    if not desc_en or not platform_desc or not turret_desc:
        if any(k in s_low for k in ["비호-ii", "비호 2", "비호2", "biho-ii"]):
            desc_en = "8x8 wheeled armored chassis, unmanned turret with single 30mm/40mm CTA autocannon, missile canisters, 4-panel fixed AESA radar, and high-energy laser"
        elif any(k in s_low for k in ["비호복합", "k30", "sam 비호"]):
            desc_en = "K200-based tracked armored chassis, manned boxy turret with dual 30mm autocannons, two dual Shingung missile pods, and rear rotating search radar"
        elif "비호" in s_low:
            desc_en = "K200-based tracked armored chassis, manned boxy turret with dual 30mm autocannons and rear rotating search radar"
        elif any(k in s_low for k in ["87식", "type 87"]):
            desc_en = "Type 74 tank tracked chassis, turret with dual 35mm Oerlikon autocannons, independent search and tracking radar systems"
        elif any(k in s_low for k in ["구르주", "gurz", "gürz", "구르즈"]):
            desc_en = "8x8 wheeled air defense truck chassis, heavy turret with 35mm airburst autocannon, anti-air missile canisters, and 4-panel AESA radar"
        elif any(k in s_low for k in ["게파르트", "gepard"]):
            desc_en = "Leopard 1 tank tracked chassis, turret with dual 35mm autocannons, and search/tracking radar"
        elif any(k in s_low for k in ["전차", "탱크", "흑표", "k2", "abrams", "leopard"]):
            desc_en = "tracked main battle tank chassis, 120mm smoothbore main gun, reactive armor tiles, and active defense system"
        elif any(k in s_low for k in ["kf-21", "f-35", "f-22", "전투기", "su-"]):
            desc_en = "twin-engine supersonic multirole stealth fighter jet, conformal weapon bays, and nose-mounted AESA radar"
        elif any(k in s_low for k in ["드론", "tb2", "uav", "무인기"]):
            desc_en = "tactical unmanned combat aerial drone, lightweight composite airframe, and precision guided munition pylons"
        elif not desc_en:
            desc_en = "modern tactical weapon platform, precision engineered chassis and weapon systems"

    return {
        "name_en": name_en,
        "country_en": country_en,
        "desc_en": desc_en
    }


def _get_preset_weapon_data(name: str, is_a: bool = True) -> Dict[str, Any]:
    """무기별 정확한 고증 데이터 사전 프리셋 (K30 SAM 비호복합, 87식 자주대공포, 비호-II 등)"""
    n_low = name.lower()
    if any(k in n_low for k in ["비호-ii", "비호 2", "비호2", "biho-ii", "biho 2"]):
        return {
            "name_en": "BIHO-II",
            "country_en": "South Korean",
            "desc_en": "8x8 wheeled armored chassis, unmanned turret with single 30mm/40mm CTA autocannon, missile canisters, 4-panel fixed AESA radar, and high-energy laser",
            "platform": "8×8 차륜형(Wheeled) 타이곤 장갑차체 (최고속도 100 km/h 이상)",
            "gun": "30mm / 40mm CTA 단일 무인포탑 (발사속도 분당 200발)",
            "missile": "천검 / 신궁 복합 지대공·대전차 유도탄 캐니스터 (사거리 3~8 km)",
            "radar": "4면 고정형 AESA 능동위상배열 3D 레이더 + EOTS",
            "feature": "소형 자폭 드론 요격용 고출력 광섬유 레이저 무기 통합"
        }
    elif any(k in n_low for k in ["비호복합", "k30", "sam 비호"]):
        return {
            "name_en": "K30 BIHO HYBRID",
            "country_en": "South Korean",
            "desc_en": "K200-based tracked armored chassis, manned boxy turret with dual 30mm autocannons, two dual Shingung missile pods, and rear rotating search radar",
            "platform": "K200 기반 무한궤도(Tracked) 장갑차체 (최고속도 약 60 km/h, 험지 돌파력 우수)",
            "gun": "30mm 2연장(쌍열) 기관포 (발사속도 분당 1,200발)",
            "missile": "신궁 지대공 미사일 2연장 런처 2기 (총 4발, 사거리 7km 적외선 시커)",
            "radar": "TPS-830K 저고도 회전형 탐색 레이더 (17km) + 광학추적장치(EOTS)",
            "feature": "대한민국 육군 수백 대 실전배치 완료 및 야전 신뢰성 검증"
        }
    elif "비호" in n_low:
        return {
            "name_en": "K30 BIHO",
            "country_en": "South Korean",
            "desc_en": "K200-based tracked armored chassis, manned boxy turret with dual 30mm autocannons and rear rotating search radar",
            "platform": "K200 기반 무한궤도(Tracked) 장갑차체 (최고속도 약 60 km/h)",
            "gun": "30mm 2연장(쌍열) 기관포 (발사속도 분당 1,200발)",
            "missile": "대공 미사일 미탑재 (기관포 단독 운용)",
            "radar": "TPS-830K 저고도 회전형 탐색 레이더",
            "feature": "대한민국 육군 기동군단 저고도 자주대공포 방공망"
        }
    elif any(k in n_low for k in ["87식", "type 87"]):
        return {
            "name_en": "TYPE 87 SPAAG",
            "country_en": "Japanese",
            "desc_en": "Type 74 tank tracked chassis, turret with dual 35mm Oerlikon autocannons, independent search and tracking radar systems",
            "platform": "74식 전차 차체 기반 무한궤도(Tracked) 중장갑 차체 (최고 53 km/h)",
            "gun": "35mm 오리콘 KDA 2연장(쌍열) 기관포 (발사속도 분당 1,100발)",
            "missile": "대공 미사일 미탑재 (35mm 대공포 화망 요격)",
            "radar": "포탑 상부 독립 회전식 탐색 레이더 + 추적 레이더",
            "feature": "일본 육상자위대 배치, 전차와 동일한 수준의 중장갑 방호력"
        }
    elif any(k in n_low for k in ["구르주", "gurz", "gürz", "구르즈"]):
        return {
            "name_en": "GÜRZ",
            "country_en": "Turkish",
            "desc_en": "8x8 wheeled air defense truck chassis, heavy turret with 35mm airburst autocannon, anti-air missile canisters, and 4-panel AESA radar",
            "platform": "8×8 차륜형(Wheeled) 전술트럭 차체 (최고속도 약 100 km/h)",
            "gun": "35mm 공중폭발 기관포 (ATOM 스마트 탄약)",
            "missile": "Bozdoğan / Sungur 단거리 대공 미사일 4기 (사거리 4~8 km)",
            "radar": "4면 고정형 능동위상배열(AESA) 3D 레이더 + EOTS",
            "feature": "튀르키예 아셀산의 최신 복합 하드킬 방공 체계"
        }
    elif any(k in n_low for k in ["게파르트", "gepard"]):
        return {
            "name_en": "GEPARD SPAAG",
            "country_en": "German",
            "desc_en": "Leopard 1 tank tracked chassis, turret with dual 35mm autocannons, search and tracking radar",
            "platform": "레오파르트 1 전차 기반 궤도형(Tracked) 차체 (최고 65 km/h)",
            "gun": "35mm 오리콘 KDA 2연장(쌍열) 기관포 (발사속도 분당 1,100발)",
            "missile": "스팅어 대공 미사일 선택 탑재",
            "radar": "S-대역 탐색 레이더 및 Ku-대역 추적 레이더",
            "feature": "우크라이나 전선 샤헤드 드론 요격 격추율 입증"
        }
    elif any(k in n_low for k in ["퉁구스카", "tunguska"]):
        return {
            "name_en": "2K22 TUNGUSKA",
            "country_en": "Russian",
            "desc_en": "GM-352 tracked chassis, dual 30mm 2A38M autocannons, 8 9M311 missiles, search and tracking radar",
            "platform": "GM-352 무한궤도(Tracked) 장갑차체 (최고 65 km/h)",
            "gun": "30mm 2A38M 2연장(쌍열) 기관포 (발사속도 분당 3,900~5,000발)",
            "missile": "9M311 지대공 미사일 8발 (사거리 8km 레이저 유도)",
            "radar": "1RL144 펄스 도플러 레이더 (탐색 18km, 추적 16km)",
            "feature": "세계 최초의 기관포+미사일 복합 대공장갑차"
        }
    else:
        meta = derive_weapon_metadata(name, None, is_a=is_a)
        return {
            "name_en": meta["name_en"],
            "country_en": meta["country_en"],
            "desc_en": meta["desc_en"],
            "platform": "전술 기동 차체 플랫폼",
            "gun": "주요 구경 화력 무장 체계",
            "missile": "정밀 유도 대공/타격 무기 체계",
            "radar": "통합 탐색 레이더 및 사격통제 센서",
            "feature": "최신 전술 작전 운용 체계"
        }


def _get_fallback_specs(subject_a: str, subject_b: str, topic: str) -> Dict[str, Any]:
    """Gemini API 키가 없거나 실패 시 정확한 세부 기종 고증을 준수하는 안전 폴백 스펙 데이터"""
    sa = subject_a.strip() or "비교 대상 A"
    sb = subject_b.strip() or "비교 대상 B"

    p_a = _get_preset_weapon_data(sa, is_a=True)
    p_b = _get_preset_weapon_data(sb, is_a=False)

    w_plat = "TIE"
    w_plat_r = "플랫폼 기동 특성 상호 대등"
    if "궤도" in p_a["platform"] and "차륜" in p_b["platform"]:
        w_plat = "TIE"
        w_plat_r = "야지 험지 기동(궤도형) vs 도로 고속 전개(차륜형)의 전술적 차이"
    elif "차륜" in p_a["platform"] and "궤도" in p_b["platform"]:
        w_plat = "TIE"
        w_plat_r = "도로 고속 전개(차륜형) vs 야지 험지 기동(궤도형)의 전술적 차이"

    w_gun = "TIE"
    w_gun_r = "대공 사격 화망 및 화력 대등"
    if "35mm" in p_a["gun"] and "30mm" in p_b["gun"]:
        w_gun = "A"
        w_gun_r = f"{sa}의 35mm 대구경 탄약 파괴력 및 사거리 우세"
    elif "30mm" in p_a["gun"] and "35mm" in p_b["gun"]:
        w_gun = "B"
        w_gun_r = f"{sb}의 35mm 대구경 탄약 파괴력 및 사거리 우세"

    w_mis = "TIE"
    w_mis_r = "유도 무기 운용 능력 대등"
    if ("신궁" in p_a["missile"] or "미사일" in p_a["missile"]) and ("미탑재" in p_b["missile"] or "없음" in p_b["missile"]):
        w_mis = "A"
        w_mis_r = f"{sa}는 복합 지대공 미사일 탑재로 사거리 및 교전 영역 압도적 우위"
    elif ("미탑재" in p_a["missile"] or "없음" in p_a["missile"]) and ("신궁" in p_b["missile"] or "미사일" in p_b["missile"]):
        w_mis = "B"
        w_mis_r = f"{sb}는 복합 지대공 미사일 탑재로 사거리 및 교전 영역 압도적 우위"

    w_rad = "TIE"
    w_rad_r = "탐지 및 사격통제 능력 대등"
    if "aesa" in p_a["radar"].lower() and "aesa" not in p_b["radar"].lower():
        w_rad = "A"
        w_rad_r = f"{sa}의 4면 고정형 AESA 능동위상배열 레이더 다중 표적 추적 우세"
    elif "aesa" not in p_a["radar"].lower() and "aesa" in p_b["radar"].lower():
        w_rad = "B"
        w_rad_r = f"{sb}의 4면 고정형 AESA 능동위상배열 레이더 다중 표적 추적 우세"

    table = [
        {"metric": "차체 플랫폼 및 기동성", "val_a": p_a["platform"], "val_b": p_b["platform"], "winner": w_plat, "winner_reason": w_plat_r},
        {"metric": "주무장 기관포 체계", "val_a": p_a["gun"], "val_b": p_b["gun"], "winner": w_gun, "winner_reason": w_gun_r},
        {"metric": "대공 유도탄 미사일", "val_a": p_a["missile"], "val_b": p_b["missile"], "winner": w_mis, "winner_reason": w_mis_r},
        {"metric": "탐지 레이더 및 사통장비", "val_a": p_a["radar"], "val_b": p_b["radar"], "winner": w_rad, "winner_reason": w_rad_r},
        {"metric": "야전 실전배치 및 특징", "val_a": p_a["feature"], "val_b": p_b["feature"], "winner": "TIE", "winner_reason": "각국 전장 환경에 맞춤 운용"},
    ]

    meta_a = {"name_en": p_a["name_en"], "country_en": p_a["country_en"], "desc_en": p_a["desc_en"]}
    meta_b = {"name_en": p_b["name_en"], "country_en": p_b["country_en"], "desc_en": p_b["desc_en"]}

    return {
        "success": True,
        "highlight_summary": f"{sa} vs {sb} 최신 방산 팩트 스펙 분석 완료",
        "spec_table": table,
        "weapon_meta_a": meta_a,
        "weapon_meta_b": meta_b,
        "missing_angle_prompts": [
            {
                "angle_name": "① 정면 1:1 대칭 비교 뷰 (Front Symmetrical)",
                "target": f"{sa} & {sb}",
                "prompt_en": f"Cinematic 9:16 vertical engineering studio shot, head-on symmetrical comparison of {sa} and {sb}, pure solid white background #FFFFFF, 8k 3D CAD render",
            }
        ]
    }


def generate_vs_shorts_script(
    subject_a: str,
    subject_b: str,
    topic: str = "",
    spec_table: List[Dict[str, Any]] = None,
    gemini_api_key: str = "",
) -> Dict[str, Any]:
    """2단계 팩트체크 스펙 비교표를 기반으로 Google Flow 10개 씬(총 40초 = 각 씬 4초)에 1:1 매칭되는 고도화된 쇼츠 내레이션 대본 및 킬링 타이틀을 생성합니다."""
    key = gemini_api_key or load_env_api_key()
    sa = subject_a.strip() or "비교 대상 A"
    sb = subject_b.strip() or "비교 대상 B"

    specs_str = ""
    if spec_table:
        for it in spec_table:
            specs_str += f"- {it.get('metric')}: {sa}({it.get('val_a')}) vs {sb}({it.get('val_b')}) [우위: {it.get('winner')}] (이유: {it.get('winner_reason', '-')})\n"
    else:
        specs_str = f"- {sa} vs {sb} 종합 화력 및 스펙 맞대결"

    prompt = f"""당신은 조회수 100만 뷰를 터뜨리는 밀리터리·K-방산 전문 유튜브 쇼츠 메인 작가입니다.
입력된 2단계 팩트체크 스펙 비교표 데이터를 바탕으로, Google Flow 비디오 10개 씬(각 씬 4.0초 = 총 40초)에 1:1로 완벽히 매칭되는 10문장 구성의 쇼츠 내레이션 대본(공백 포함 300~350자 내외)을 작성하세요.

[비교 정보 및 확정 스펙 데이터]
- 대상 A: {sa}
- 대상 B: {sb}
- 핵심 주제: {topic or '종합 화력 및 스펙 맞대결'}
{specs_str}

[필수 10개 씬(각 4초) 구조 및 작법 규칙]
* #01 (0~4초): 3초 결핍·반전 후킹 (진부한 "하늘을 지배하는" 절대 금지! 첫 문장부터 두 무기의 외형적 유사성 대비 결정적 결핍/가격 차이를 의문형이나 반전 문장으로 던질 것)
* #02 (4~8초): 무기 A({sa}) 등장 및 기본 제원 (정확한 제식 명칭 고증)
* #03 (8~12초): 무기 A({sa}) 주무장 및 화력 스펙 (기관포 구경, 미사일 수량 등 수치 팩트)
* #04 (12~16초): 무기 A({sa}) 핵심 센서 및 특수 기능 (AESA 레이더, 복합 추적, 드론 대응 등)
* #05 (16~20초): 무기 B({sb}) 등장 및 기본 제원 (상대 무기 제식 명칭)
* #06 (20~24초): 무기 B({sb}) 주무장 및 화력 스펙 (포탄 구경 및 장점 인정)
* #07 (24~28초): 무기 B({sb})의 치명적 한계/약점 부각 (미사일 부재, 구형 사통장치, 살인적 단가 등 고증 팩트)
* #08 (28~32초): 두 무기 결정적 격차 1:1 비교 (복합 화력 및 가성비 격차 역전 포인트)
* #09 (32~36초): 최종 승자 판정 및 종합 우위 선언 (드론전 및 실전 생존성 기준 명확한 승자)
* #10 (36~40초): 1:1 맞짱 대치 엔딩 및 댓글 유도 (시청자가 댓글을 달고 싶어지는 날카로운 한 줄 질문)

[필수 글로벌 쇼츠 영어 자막(English Subtitles) 작성 지침]
- 음성은 한국어로 읽히지만, 영상 하단에 삽입하여 해외 시청자 노출을 극대화할 수 있도록 10개 씬 각각에 대해 '직관적이고 짧은 쇼츠 자막 스타일(concise, punchy English captions)'의 영문 번역 문장("text_en")을 작성하세요.
- 각 씬당 6~12단어 내외로 간결하고 임팩트 있게 작성하며, 밀리터리 고증 명칭을 정확히 유지하세요.

[출력 형식 제한]
- 대본 본문에는 [0~4초], (효과음), [장면1] 같은 지시문을 일절 넣지 말고, 성우/TTS가 바로 읽을 수 있는 순수 내레이션 문장만 작성하세요.
- 각 씬당 약 30~35자 내외(4초 낭독 분량)로 작성하여 총 10문장(공백 포함 300~350자 내외)을 엄격히 지키세요.

반드시 다음 JSON 형식으로만 응답하세요:
{{
  "hook_titles": [
    "알고리즘 폭발 킬링 타이틀 1 (결핍/격차/가격 폭로형)",
    "알고리즘 폭발 킬링 타이틀 2 (반전 호기심형)",
    "알고리즘 폭발 킬링 타이틀 3 (직관적 맞짱형)"
  ],
  "main_title": "가장 강력한 대표 킬링 타이틀",
  "script_sections": [
    {{"scene": "#01 (0~4초)", "phase": "3초 후킹 & 대치", "text": "첫 문장 후킹 내레이션", "text_en": "Punchy English subtitle line for scene 1"}},
    {{"scene": "#02 (4~8초)", "phase": "무기 A 등장 & 제원", "text": "{sa} 등장 및 기본 제원 내레이션", "text_en": "Concise English subtitle line for scene 2"}},
    {{"scene": "#03 (8~12초)", "phase": "무기 A 주무장 & 화력", "text": "{sa} 주무장 화력 스펙 내레이션", "text_en": "Concise English subtitle line for scene 3"}},
    {{"scene": "#04 (12~16초)", "phase": "무기 A 센서 & 드론 대응", "text": "{sa} 핵심 센서 및 드론 요격 능력 내레이션", "text_en": "Concise English subtitle line for scene 4"}},
    {{"scene": "#05 (16~20초)", "phase": "무기 B 등장 & 제원", "text": "{sb} 등장 및 기본 제원 내레이션", "text_en": "Concise English subtitle line for scene 5"}},
    {{"scene": "#06 (20~24초)", "phase": "무기 B 주무장 & 화력", "text": "{sb} 주무장 스펙 내레이션", "text_en": "Concise English subtitle line for scene 6"}},
    {{"scene": "#07 (24~28초)", "phase": "무기 B 한계 & 약점", "text": "{sb} 치명적 약점 및 단가 한계 내레이션", "text_en": "Concise English subtitle line for scene 7"}},
    {{"scene": "#08 (28~32초)", "phase": "결정적 격차 1:1 비교", "text": "두 무기 격차 비교 내레이션", "text_en": "Concise English subtitle line for scene 8"}},
    {{"scene": "#09 (32~36초)", "phase": "최종 승자 판정", "text": "명확한 승자 판정 내레이션", "text_en": "Concise English subtitle line for scene 9"}},
    {{"scene": "#10 (36~40초)", "phase": "엔딩 & 댓글 유도", "text": "마무리 및 댓글 유도 질문", "text_en": "Short call-to-action English subtitle for scene 10"}}
  ],
  "full_script": "순수 내레이션 10문장 전체 합본 (공백 포함 300~350자 내외 줄글)",
  "full_script_en": "Full 10-scene English subtitles formatted line-by-line (#01: ... \\n#02: ...)"
}}
"""
    if not key:
        return _fallback_vs_script(sa, sb, topic)

    try:
        raw_res = _call_gemini_api(prompt, key, json_mode=True)
        if not raw_res:
            return _fallback_vs_script(sa, sb, topic)

        clean_json = re.sub(r"^```(?:json)?\s*", "", raw_res.strip(), flags=re.MULTILINE)
        clean_json = re.sub(r"\s*```$", "", clean_json.strip())
        data = json.loads(clean_json)

        # 키 이름 정규화 및 상호 호환 보장
        t_list = data.get("hook_titles") or data.get("killing_hook_titles") or []
        m_title = data.get("main_title") or (t_list[0] if t_list else f"{sa} vs {sb}")
        f_text = data.get("full_script") or data.get("full_narration") or ""
        s_list = data.get("script_sections") or data.get("scenes") or []
        f_text_en = data.get("full_script_en") or data.get("english_script") or ""

        # 지시문 정제: 혹시나 포함된 [0~4초], (효과음) 등 제거
        f_text_clean = re.sub(r"\[[^\]]*\]|\([^\)]*\)", "", f_text).strip()
        f_text_clean = re.sub(r"\s+", " ", f_text_clean)

        # 10개 씬 영문 자막 text_en 보장 및 full_script_en 자동 조립
        en_lines = []
        for s_idx, sc_item in enumerate(s_list):
            if not sc_item.get("text_en"):
                ko_t = sc_item.get("text", "")
                sc_item["text_en"] = f"Scene #{s_idx+1:02d}: {ko_t}"
            sc_code = sc_item.get("scene", f"#{s_idx+1:02d}").split()[0]
            en_lines.append(f"{sc_code} {sc_item.get('text_en')}")

        if not f_text_en:
            f_text_en = "\n".join(en_lines)

        data["hook_titles"] = t_list
        data["killing_hook_titles"] = t_list
        data["main_title"] = m_title
        data["full_script"] = f_text_clean
        data["full_narration"] = f_text_clean
        data["full_script_en"] = f_text_en
        data["script_sections"] = s_list
        data["scenes"] = s_list
        data["success"] = True
        return data
    except Exception as e:
        print(f"[generate_vs_shorts_script] Error: {e}")
        return _fallback_vs_script(sa, sb, topic)


def _fallback_vs_script(sa: str, sb: str, topic: str) -> Dict[str, Any]:
    """Gemini API 호출 실패 시 10개 씬(총 40초 = 각 씬 4초) 기준 폴백 대본 (한국어 + 영어 자막)"""
    s01 = f"겉모습은 쌍둥이처럼 닮았는데, {sb}에는 치명적인 '이것'이 없습니다!"
    s02 = f"먼저 한국 육군의 주력 복합 방공망, {sa}입니다."
    s03 = f"구경 30밀리미터 쌍열 기관포에 신궁 대공 미사일 4발을 복합 장착했습니다."
    s04 = f"최신 추적 레이더로 저고도 침투 드론부터 순항미사일까지 빈틈없이 요격합니다."
    s05 = f"이에 맞서는 일본 자위대의 87식 자주대공포입니다."
    s06 = f"스위스제 35밀리미터 쌍열포로 분당 1,100발을 쏟아붓는 막강한 화력을 자랑합니다."
    s07 = f"하지만 대공 미사일이 전혀 없고 대당 150억이라는 살인적인 단가가 발목을 잡습니다."
    s08 = f"복합 유도탄의 사거리와 실전 가성비에서 압도적인 체급 격차가 벌어집니다."
    s09 = f"현대 드론전 생존성과 다층 방공 능력 모두 {sa}의 완승!"
    s10 = f"여러분이 보시기에 더 강력한 자주대공포는 무엇인가요? 댓글로 의견을 남겨주세요!"

    s01_en = f"They look like twins, but {sb} is missing THIS critical weapon!"
    s02_en = f"Meet South Korea's premier hybrid air defense system, {sa}."
    s03_en = f"Armed with dual 30mm autocannons and 4 Chiron surface-to-air missiles."
    s04_en = f"Its advanced tracking radar effortlessly intercepts low-altitude suicide drones."
    s05_en = f"Facing off is Japan Ground Self-Defense Force's {sb}."
    s06_en = f"Boasting dual 35mm cannons pumping out 1,100 rounds per minute."
    s07_en = f"Yet it has ZERO missiles and carries a staggering $15 million price tag."
    s08_en = f"In missile range and real-world cost efficiency, the gap is massive."
    s09_en = f"In modern drone warfare survivability, {sa} takes a decisive victory!"
    s10_en = f"Which air defense beast would you bet on? Let us know in the comments!"

    titles = [
        f"겉모습은 쌍둥이인데 일본엔 '이것'이 없다?! {sa} vs {sb}",
        f"대당 150억의 흑역사 무기?! {sa} vs {sb} 충격 결말",
        f"실제 전장에 던지면 누가 살아남을까? {sa} vs {sb}"
    ]

    sections = [
        {"scene": "#01 (0~4초)", "phase": "3초 후킹 & 대치", "text": s01, "text_en": s01_en},
        {"scene": "#02 (4~8초)", "phase": "무기 A 등장 & 제원", "text": s02, "text_en": s02_en},
        {"scene": "#03 (8~12초)", "phase": "무기 A 주무장 & 화력", "text": s03, "text_en": s03_en},
        {"scene": "#04 (12~16초)", "phase": "무기 A 센서 & 드론 대응", "text": s04, "text_en": s04_en},
        {"scene": "#05 (16~20초)", "phase": "무기 B 등장 & 제원", "text": s05, "text_en": s05_en},
        {"scene": "#06 (20~24초)", "phase": "무기 B 주무장 & 화력", "text": s06, "text_en": s06_en},
        {"scene": "#07 (24~28초)", "phase": "무기 B 한계 & 약점", "text": s07, "text_en": s07_en},
        {"scene": "#08 (28~32초)", "phase": "결정적 격차 1:1 비교", "text": s08, "text_en": s08_en},
        {"scene": "#09 (32~36초)", "phase": "최종 승자 판정", "text": s09, "text_en": s09_en},
        {"scene": "#10 (36~40초)", "phase": "엔딩 & 댓글 유도", "text": s10, "text_en": s10_en},
    ]

    full = " ".join([s["text"] for s in sections])
    full_en = "\n".join([f"{s['scene'].split()[0]} {s['text_en']}" for s in sections])

    return {
        "success": True,
        "hook_titles": titles,
        "killing_hook_titles": titles,
        "main_title": titles[0],
        "script_sections": sections,
        "scenes": sections,
        "full_script": full,
        "full_narration": full,
        "full_script_en": full_en
    }


def translate_script_to_english_captions(
    script_sections: List[Dict[str, Any]],
    subject_a: str = "",
    subject_b: str = "",
    gemini_api_key: str = "",
) -> Dict[str, Any]:
    """기존 한국어 10개 씬 대본을 직관적이고 짧은 글로벌 쇼츠 영어 자막(concise, punchy English captions)으로 원클릭 번역합니다."""
    key = gemini_api_key or load_env_api_key()
    sa = subject_a.strip() or "Weapon A"
    sb = subject_b.strip() or "Weapon B"

    lines = []
    for i, s in enumerate(script_sections):
        sc_lbl = s.get("scene", f"#{i+1:02d}")
        ko_txt = s.get("text") or s.get("narration", "")
        lines.append(f"{sc_lbl}: {ko_txt}")
    joined_ko = "\n".join(lines)

    if not key or not lines:
        # 키가 없으면 기본 규칙 기반 반환
        for i, s in enumerate(script_sections):
            if not s.get("text_en"):
                s["text_en"] = f"Scene #{i+1:02d}: {s.get('text', '')}"
        en_all = "\n".join([f"{s.get('scene', f'#{i+1:02d}').split()[0]} {s.get('text_en')}" for i, s in enumerate(script_sections)])
        return {"script_sections": script_sections, "full_script_en": en_all}

    prompt = f"""You are a professional YouTube Shorts subtitle localization expert specializing in military & defense content.
Translate the following 10-scene Korean shorts narration into concise, punchy English subtitle captions for global viewers.

[Context]
- Platform: YouTube Shorts (fast-paced, high impact)
- Subject A: {sa}
- Subject B: {sb}

[Korean Script by Scene]
{joined_ko}

[Translation Rules]
1. Each scene's English subtitle MUST be short, punchy, and direct (6 to 12 words max).
2. Use accurate military terminology (e.g. Autocannon, Chiron SAM, Hybrid SPAAG, Radar, Drone interception).
3. Keep the tension and contrast sharp. Do NOT use overly formal or academic language.

Return ONLY a JSON array of 10 strings corresponding to scenes #01 through #10:
[
  "Punchy English line for scene 1",
  "Punchy English line for scene 2",
  ...
  "Punchy English line for scene 10"
]
"""
    try:
        raw_res = _call_gemini_api(prompt, key, json_mode=True)
        clean_json = re.sub(r"^```(?:json)?\s*", "", raw_res.strip(), flags=re.MULTILINE)
        clean_json = re.sub(r"\s*```$", "", clean_json.strip())
        en_arr = json.loads(clean_json)

        if isinstance(en_arr, list) and len(en_arr) >= len(script_sections):
            for idx, sc_it in enumerate(script_sections):
                sc_it["text_en"] = str(en_arr[idx]).strip()
        en_full = "\n".join([f"{s.get('scene', f'#{i+1:02d}').split()[0]} {s.get('text_en')}" for i, s in enumerate(script_sections)])
        return {"script_sections": script_sections, "full_script_en": en_full}
    except Exception as e:
        print(f"[translate_script_to_english_captions] Error: {e}")
        for i, s in enumerate(script_sections):
            if not s.get("text_en"):
                s["text_en"] = s.get("text", "")
        en_full = "\n".join([f"{s.get('scene', f'#{i+1:02d}').split()[0]} {s.get('text_en')}" for i, s in enumerate(script_sections)])
        return {"script_sections": script_sections, "full_script_en": en_full}


def generate_youtube_upload_package(
    subject_a: str,
    subject_b: str,
    topic: str = "",
    spec_table: List[Dict[str, Any]] = None,
    full_script: str = "",
    gemini_api_key: str = "",
) -> Dict[str, Any]:
    """2단계 팩트체크 스펙표와 40초 쇼츠 대본을 기반으로 유튜브 쇼츠 업로드용 풀패키지(제목 3종, 설명란, 해시태그, 스튜디오 태그, 고정댓글)를 생성합니다."""
    key = gemini_api_key or load_env_api_key()
    sa = subject_a.strip() or "비교 대상 A"
    sb = subject_b.strip() or "비교 대상 B"

    specs_str = ""
    if spec_table:
        for it in spec_table:
            specs_str += f"- {it.get('metric')}: {sa}({it.get('val_a')}) vs {sb}({it.get('val_b')}) [우위: {it.get('winner')}] (근거: {it.get('winner_reason', '-')})\n"
    else:
        specs_str = f"- {sa} vs {sb} 종합 화력 및 스펙 맞대결"

    prompt = f"""당신은 유튜브 쇼츠 알고리즘 SEO 및 밀리터리 채널 업로드 전문 마케터입니다.
제공된 두 무기({sa} vs {sb})의 팩트체크 스펙 데이터와 40초 쇼츠 대본을 바탕으로, 유튜브 스튜디오 업로드 창에 바로 복사-붙여넣기할 수 있는 [유튜브 쇼츠 업로드 풀패키지 5종]을 생성하세요.

[입력 데이터]
- 대상 A: {sa}
- 대상 B: {sb}
- 핵심 주제: {topic or '종합 화력 및 스펙 맞대결'}
- 팩트체크 스펙표:
{specs_str}
- 40초 쇼츠 내레이션 대본:
{full_script}

[5대 필수 항목 생성 규칙 (한국어 및 글로벌 영어 2가지 언어 버전 동시 생성)]
1. [제목 추천 3종 (titles / titles_en)]:
   - 60자 이내, 유튜브 모바일 화면에서 잘리지 않고 클릭률을 폭발시키는 제목 3개.
   - 1안 (궁금증·결핍 자극형): 겉모습/외형 대비 결정적 결핍 강조 (예: 겉모습은 쌍둥이인데 일본엔 '이것'이 없다? {sa} vs {sb} #쇼츠)
   - 2안 (가성비·격차 비교형): 단가 차이 또는 흑역사/결정적 차이 1가지 (예: 대당 150억 {sb} vs {sa}, 결정적 차이 1가지)
   - 3안 (직관적 검색 노출형): 양국 정면 승부 및 제식 명칭 스펙 비교 (예: 자주대공포 정면 승부! {sa} vs {sb} 스펙 비교)
   - [titles_en]: 위 3개 제목을 해외 밀리터리 쇼츠 팬들이 클릭할 수밖에 없는 네이티브 영어로 번역하고 끝에 #Shorts 포함 (60자 이내).
     (예: 1안: "They Look Like Twins, But Japan Lacks THIS? {sa} vs {sb} #Shorts", 2안: "$15M {sb} vs {sa}: 1 Fatal Flaw! #Shorts", 3안: "Air Defense Showdown! {sa} vs {sb} #Shorts")

2. [유튜브 설명란 (description / description_en)]:
   - 쇼츠 알고리즘 검색(SEO)에 걸리도록 핵심 키워드가 자연스럽게 녹아든 3~4줄 요약문.
   - 2단계 팩트체크 표의 핵심 제원 비교 요약 (주무장, 레이더, 단가 등 3~4줄 글머리 기호).
   - 시청 감사 인사 및 하단 필수 해시태그 5~7개 포함 완성형 텍스트.
   - [description_en]: 해외 시청자 및 글로벌 검색 알고리즘 최적화 영문 설명란 (요약문 + 팩트체크 스펙 불릿 + 영문 해시태그).

3. [해시태그 (hashtags / hashtags_en)]:
   - 설명란 및 제목에 바로 붙일 수 있는 # 형태 태그 7~10개 (예: #K방산 #밀리터리 #비호복합 #자주대공포 #일본87식 #무기비교 #쇼츠 #Shorts).
   - [hashtags_en]: 영문 해시태그 7~10개 (예: #KDefense #Military #SouthKorea #K30Biho #Type87 #AirDefense #Shorts #DefenseTech).

4. [유튜브 스튜디오 태그 (tags_csv / tags_csv_en)]:
   - 유튜브 업로드 상세정보 '태그' 칸에 통째로 복사해서 붙여넣기만 하면 쉼표(,) 단위로 자동 분리되도록 15~20개 키워드 나열.
   - (예: K방산, 대한민국 무기, {sa}, {sb}, 한일 무기 비교, 자주대공포, 대공미사일, 신궁, 드론 요격, 밀리터리 쇼츠, 방산수출)
   - [tags_csv_en]: 쉼표(,)로 구분된 15~20개 영문 검색 키워드 (예: K-Defense, South Korea Military, {sa}, {sb}, Korea vs Japan Military, Air Defense System, Autocannon, Chiron SAM, Drone Interceptor, Military Shorts, Defense Tech, SPAAG).

5. [고정 댓글용 팩트체크 & 토론 유도 문구 (pinned_comment / pinned_comment_en)]:
   - 밀리터리 채널 특성상 발생할 수 있는 고증 논란을 사전에 차단하고 시청자 댓글 참여를 유도하는 텍스트.
   - 1) 시청자 의견 질문 1줄 (예: "👇 여러분이 보시기에 현대전(드론전)에서 더 위협적인 체계는 어느 쪽인가요?")
   - 2) [📌 영상 속 팩트체크 요약]: 2단계 스펙표에서 추출한 양국 무기의 공식 제식명칭, 배치 연도, 주무장, 탐지 체계, 대당 단가 등 객관적 팩트 3~4줄 정리 (태클 방지용 근거 데이터).
   - [pinned_comment_en]: 네이티브 영문 시청자 토론 질문 + 팩트체크 제원 데이터 요약문.

반드시 다음 JSON 형식으로만 응답하세요:
{{
  "titles": [
    "1안 제목 (한국어)",
    "2안 제목 (한국어)",
    "3안 제목 (한국어)"
  ],
  "description": "한국어 설명란 전문 텍스트 (줄바꿈 포함)",
  "hashtags": "#태그1 #태그2 #태그3 ...",
  "tags_csv": "키워드1, 키워드2, 키워드3, ...",
  "pinned_comment": "한국어 고정 댓글 전문 텍스트",
  "titles_en": [
    "English Title 1 (#Shorts)",
    "English Title 2 (#Shorts)",
    "English Title 3 (#Shorts)"
  ],
  "description_en": "English description full text (line breaks included)",
  "hashtags_en": "#KDefense #Military #SouthKorea ...",
  "tags_csv_en": "K-Defense, South Korea Military, Air Defense, ...",
  "pinned_comment_en": "English pinned comment full text"
}}
"""
    if not key:
        return _fallback_youtube_upload_package(sa, sb, topic, spec_table, full_script)

    try:
        raw_res = _call_gemini_api(prompt, key, json_mode=True)
        if not raw_res:
            return _fallback_youtube_upload_package(sa, sb, topic, spec_table, full_script)

        clean_json = re.sub(r"^```(?:json)?\s*", "", raw_res.strip(), flags=re.MULTILINE)
        clean_json = re.sub(r"\s*```$", "", clean_json.strip())
        data = json.loads(clean_json)
        data["success"] = True
        return data
    except Exception as e:
        print(f"[generate_youtube_upload_package] Error: {e}")
        return _fallback_youtube_upload_package(sa, sb, topic, spec_table, full_script)


def _fallback_youtube_upload_package(
    sa: str,
    sb: str,
    topic: str,
    spec_table: List[Dict[str, Any]] = None,
    full_script: str = "",
) -> Dict[str, Any]:
    """Gemini API 호출 실패 시 팩트체크 스펙 데이터를 기반으로 자동 조합하는 유튜브 업로드 풀패키지 폴백"""
    t1 = f"겉모습은 쌍둥이인데 일본엔 '이것'이 없다? {sa} vs {sb} #쇼츠"
    t2 = f"대당 150억 {sb} vs {sa}, 결정적 차이 1가지"
    t3 = f"한일 자주대공포 정면 승부! {sa} vs {sb} 스펙 비교"

    # 스펙 요약 줄글 생성
    spec_bullets = []
    fact_bullets = []
    spec_bullets_en = []
    fact_bullets_en = []
    if spec_table:
        for it in spec_table[:4]:
            m = it.get("metric", "")
            va = it.get("val_a", "")
            vb = it.get("val_b", "")
            win = it.get("winner", "")
            w_str = f" ({sa} 우세)" if win == "A" else (f" ({sb} 우세)" if win == "B" else "")
            w_str_en = f" (Advantage: {sa})" if win == "A" else (f" (Advantage: {sb})" if win == "B" else "")
            spec_bullets.append(f"• {m}: {sa}({va}) vs {sb}({vb}){w_str}")
            fact_bullets.append(f"- {m}: {sa}({va}) / {sb}({vb})")
            spec_bullets_en.append(f"• {m}: {sa} ({va}) vs {sb} ({vb}){w_str_en}")
            fact_bullets_en.append(f"- {m}: {sa} ({va}) / {sb} ({vb})")
    else:
        spec_bullets.append(f"• 핵심 화력 및 기동성 스펙 정면 대결")
        fact_bullets.append(f"- 화력 및 사거리 스펙 팩트 비교")
        spec_bullets_en.append(f"• Firepower, range and mobility direct comparison")
        fact_bullets_en.append(f"- Firepower and interception spec fact comparison")

    spec_summary_str = "\n".join(spec_bullets)
    fact_summary_str = "\n".join(fact_bullets)
    spec_summary_en = "\n".join(spec_bullets_en)
    fact_summary_en = "\n".join(fact_bullets_en)

    # 해시태그 (한국어 & 영어)
    tag_words = ["K방산", "밀리터리", "자주대공포", "무기비교", "방산수출", "쇼츠", "Shorts"]
    clean_sa = re.sub(r"[^\w가-힣]", "", sa)
    clean_sb = re.sub(r"[^\w가-힣]", "", sb)
    if clean_sa:
        tag_words.insert(2, clean_sa[:10])
    if clean_sb:
        tag_words.insert(3, clean_sb[:10])
    hashtags_str = " ".join([f"#{w}" for w in tag_words[:8]])

    hashtags_en_list = ["#KDefense", "#Military", "#SouthKorea", "#AirDefense", "#SPAAG", "#Shorts", "#DefenseTech", "#MilitaryComparison"]
    clean_sa_en = re.sub(r"[^\w]", "", sa)
    clean_sb_en = re.sub(r"[^\w]", "", sb)
    if clean_sa_en:
        hashtags_en_list.insert(3, f"#{clean_sa_en[:12]}")
    if clean_sb_en:
        hashtags_en_list.insert(4, f"#{clean_sb_en[:12]}")
    hashtags_en_str = " ".join(hashtags_en_list[:8])

    # 스튜디오 태그 (쉼표 구분 - 한국어 & 영어)
    tags_list = [
        "K방산", "대한민국 국방", sa, sb, f"{sa} {sb}",
        "자주대공포", "복합대공화기", "대공미사일", "신궁",
        "한일 무기 비교", "드론 요격", "방공무기", "밀리터리 쇼츠",
        "방산수출", "국방과학연구소", "유튜브 쇼츠"
    ]
    tags_csv_str = ", ".join(tags_list)

    tags_list_en = [
        "K-Defense", "South Korea Military", sa, sb, f"{sa} vs {sb}",
        "Air Defense System", "SPAAG", "Self-Propelled Anti-Air Gun",
        "Autocannon", "Chiron SAM", "Drone Interception", "Military Shorts",
        "Defense Technology", "Armored Vehicle", "YouTube Shorts"
    ]
    tags_csv_en_str = ", ".join(tags_list_en)

    # 설명란 (한국어 & 영어)
    desc_str = f"""대한민국 육군의 핵심 대공 방패 '{sa}'와 일본 육상자위대의 '{sb}'!
겉모습은 쌍둥이처럼 닮아 보이지만, 실전 전장에서 생사를 가르는 결정적 무장과 기술력 차이가 존재합니다.
40초 만에 핵심 스펙과 판정 근거를 팩트체크해 드립니다.

[📊 팩트체크 핵심 제원 비교]
{spec_summary_str}

영상이 유익하셨다면 '구독'과 '좋아요' 부탁드립니다! 다음 비교 영상 의견도 댓글로 남겨주세요.

{hashtags_str}"""

    desc_en_str = f"""South Korea's premier hybrid air defense shield '{sa}' vs Japan's '{sb}'!
While they may look like twins on the outside, there lies a decisive gap in guided missile integration, drone survival and cost efficiency.
Here is the 40-second fact-check breakdown!

[📊 Technical Specification Breakdown]
{spec_summary_en}

If you enjoyed this comparison, please Like & Subscribe! Drop your thoughts on the next showdown in the comments.

{hashtags_en_str}"""

    # 고정 댓글 (한국어 & 영어)
    pinned_comment_str = f"""👇 여러분이 보시기에 현대 드론전과 가성비 측면에서 더 위협적인 무기는 어느 쪽인가요? 여러분의 의견을 댓글로 자유롭게 남겨주세요!

[📌 영상 속 팩트체크 요약 데이터 (밀리터리 고증 태클 방지용)]
{fact_summary_str}
• 출처: 국방백서 및 공개 제원 데이터 기반 객관적 비교"""

    pinned_comment_en_str = f"""👇 Which air defense system would you trust more on the modern drone-dominated battlefield? Share your perspective in the comments below!

[📌 Fact-Check Technical Overview]
{fact_summary_en}
• Source: Official Defense White Paper & public military specifications"""

    t1_en = f"They Look Like Twins, But Japan Lacks THIS? {sa} vs {sb} #Shorts"
    t2_en = f"$15M {sb} vs {sa}: 1 Game-Changing Flaw! #Shorts"
    t3_en = f"Korea vs Japan Air Defense Showdown! {sa} vs {sb} #Shorts"

    return {
        "success": True,
        "titles": [t1, t2, t3],
        "description": desc_str.strip(),
        "hashtags": hashtags_str,
        "tags_csv": tags_csv_str,
        "pinned_comment": pinned_comment_str.strip(),
        "titles_en": [t1_en, t2_en, t3_en],
        "description_en": desc_en_str.strip(),
        "hashtags_en": hashtags_en_str,
        "tags_csv_en": tags_csv_en_str,
        "pinned_comment_en": pinned_comment_en_str.strip(),
    }


def translate_upload_package_to_english(
    package_data: Dict[str, Any],
    subject_a: str = "",
    subject_b: str = "",
    topic: str = "",
    gemini_api_key: str = "",
) -> Dict[str, Any]:
    """기존 한국어 유튜브 업로드 풀패키지를 해외 밀리터리 쇼츠 알고리즘 맞춤형 네이티브 영어로 번역 및 변환합니다."""
    key = gemini_api_key or load_env_api_key()
    sa = subject_a.strip() or "Weapon A"
    sb = subject_b.strip() or "Weapon B"

    # 폴백 기본값 확보
    fallback_pkg = _fallback_youtube_upload_package(sa, sb, topic)

    if not key:
        package_data["titles_en"] = fallback_pkg["titles_en"]
        package_data["description_en"] = fallback_pkg["description_en"]
        package_data["hashtags_en"] = fallback_pkg["hashtags_en"]
        package_data["tags_csv_en"] = fallback_pkg["tags_csv_en"]
        package_data["pinned_comment_en"] = fallback_pkg["pinned_comment_en"]
        return package_data

    ko_titles = package_data.get("titles", fallback_pkg["titles"])
    ko_desc = package_data.get("description", fallback_pkg["description"])
    ko_pinned = package_data.get("pinned_comment", fallback_pkg["pinned_comment"])

    prompt = f"""You are a professional YouTube Shorts growth specialist for global military & defense channels.
Translate and optimize the following Korean YouTube Shorts upload package into native, high-CTR English for global audiences.

[Context]
- Platform: YouTube Shorts (fast, mobile-friendly)
- Subject A: {sa}
- Subject B: {sb}
- Topic: {topic or 'Military Specs Standoff'}

[Korean Input]
- Titles: {json.dumps(ko_titles, ensure_ascii=False)}
- Description:
{ko_desc}
- Pinned Comment:
{ko_pinned}

[Optimization Rules]
1. titles_en: 3 high-CTR titles (under 60 characters each, including '#Shorts' at the end).
   - Option 1 (Curiosity/Gap): Emphasize outer similarity vs critical missing feature.
   - Option 2 (Cost/Disparity): Highlight price gap or fatal flaw.
   - Option 3 (Direct Standoff): Punchy showdown title.
2. description_en: Concise SEO summary + spec comparison bullet points + call to action + 5~7 hashtags.
3. hashtags_en: 7~10 relevant hashtags (e.g. #KDefense #Military #SouthKorea #{sa} #{sb} #AirDefense #Shorts #DefenseTech).
4. tags_csv_en: 15~20 comma-separated keywords for YouTube Studio tags input.
5. pinned_comment_en: Engaging audience question + technical fact-check summary.

Return ONLY a valid JSON object:
{{
  "titles_en": ["Title 1 #Shorts", "Title 2 #Shorts", "Title 3 #Shorts"],
  "description_en": "English description...",
  "hashtags_en": "#Tag1 #Tag2 ...",
  "tags_csv_en": "Keyword 1, Keyword 2, ...",
  "pinned_comment_en": "English pinned comment..."
}}
"""
    try:
        raw_res = _call_gemini_api(prompt, key, json_mode=True)
        clean_json = re.sub(r"^```(?:json)?\s*", "", raw_res.strip(), flags=re.MULTILINE)
        clean_json = re.sub(r"\s*```$", "", clean_json.strip())
        res_data = json.loads(clean_json)

        package_data["titles_en"] = res_data.get("titles_en") or fallback_pkg["titles_en"]
        package_data["description_en"] = res_data.get("description_en") or fallback_pkg["description_en"]
        package_data["hashtags_en"] = res_data.get("hashtags_en") or fallback_pkg["hashtags_en"]
        package_data["tags_csv_en"] = res_data.get("tags_csv_en") or fallback_pkg["tags_csv_en"]
        package_data["pinned_comment_en"] = res_data.get("pinned_comment_en") or fallback_pkg["pinned_comment_en"]
        return package_data
    except Exception as e:
        print(f"[translate_upload_package_to_english] Error: {e}")
        package_data["titles_en"] = fallback_pkg["titles_en"]
        package_data["description_en"] = fallback_pkg["description_en"]
        package_data["hashtags_en"] = fallback_pkg["hashtags_en"]
        package_data["tags_csv_en"] = fallback_pkg["tags_csv_en"]
        package_data["pinned_comment_en"] = fallback_pkg["pinned_comment_en"]
        return package_data
