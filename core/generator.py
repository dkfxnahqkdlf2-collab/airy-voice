"""
core/generator.py
쇼츠 전문 총괄 디렉터 정밀 규칙 기반 프롬프트 생성 엔진

[쇼츠 전문 총괄 디렉터 정밀 규칙]
1. [섹션 2-1: Flow 이미지 프롬프트 (정확히 32줄 밀착 규격)]
   - 헤더 규격: 정확히 8개의 헤더 (### EXT. TIME - LOCATION 또는 ### INT. TIME - LOCATION, 콜론 없음)
   - 샷 넘버링: 헤더 아래 빈 줄 없이 정확히 3줄 (Shot X-1:, Shot X-2:, Shot X-3:)
   - 포맷: 샷당 영문 15~20단어 (명사구 나열). [피사체 및 행동, 조명 및 구도, glowing pure red 발광 포인트, 품질 태그: 8k cinematic, photorealistic, no text]
   - Zero Blank Lines: 빈 줄 절대 없이 헤더 8개 + 샷 24줄 = 정확히 총 32줄 단일 블록.
   - 금지 문자: 따옴표(""), 괄호(), 대시(—), 세미콜론(;) 사용 금지, 쉼표(,)로만 연결.

2. [섹션 2-2: 샷별 한글 번역 및 시각 키워드 (1:1 매칭 32줄)]
   - 섹션 2-1의 영문 32줄을 그대로 1:1 한글 직관 번역.
   - 각 샷에서 앱 사용자가 영상 캡처본을 찾을 때 직관적으로 볼 수 있는 '구체적 핵심 시각 명사(예: 도면, 전투기 날개, 부품 분해)'를 타깃 키워드로 2~3개 추출.

3. [섹션 3: 씬별 3-멀티샷 모션 프롬프트 (Keyframe 1:1 매칭 8개 개별 블록)]
   - 각 씬마다 3개 샷을 물리적 연속 동작으로 설계:
     * [Shot X-1 (from Keyframe 1/Shot X-1)]: 시작 구도 및 초기 물리 모션
     * [Shot X-2 (from Keyframe 2/Shot X-2)]: 중간 앵글 전환 및 연속 상태 변화
     * [Shot X-3 (from Keyframe 3/Shot X-3)]: 종결 앵글, 최종 액션 완료 및 카메라 무빙, vertical 9:16
   - 상단에 해당 씬의 [TTS 대본] 필수 명시.

4. [슬롯 데이터 1~24번 1차원 평탄화(Flatten)]
   - 24개 샷을 1차원 순번제 딕셔너리 리스트로 반환
"""

import json
import os
import re
from core.url_extractor import extract_url_or_topic_context

try:
    from google import genai
    from google.genai import types as genai_types
    HAS_NEW_GENAI = True
except ImportError:
    HAS_NEW_GENAI = False

import google.generativeai as legacy_genai

# ════════════════════════════════════════════════════════════
# 24개 샷 기본 고품질 프리셋 (Scene 1-1 ~ Scene 8-3, 0 ~ 23)
# ════════════════════════════════════════════════════════════
SHOT_PRESETS_24 = [
    # Scene 1
    {
        "search_keyword": "KF-21 초음속 미사일 발사",
        "full_context": "대한민국 국방과학연구소 ADD와 KAI가 개발한 KF-21 보라매 전투기에서 장거리 덕티드 램제트 공대공 미사일이 분리 점화되는 비행 시험 장면",
        "keywords": "초음속 전투기, 램제트 미사일, 램제트 분리 발사",
        "motion_kr": "초음속 전투기에서 램제트 미사일이 분리 점화되며 붉은 궤적을 그리는 우측 고속 트래킹 샷",
        "motion_en": "Fast tracking shot moving right alongside supersonic fighter releasing sleek ramjet missile, ignition blast erupts with intense shockwaves, glowing pure red trajectory line drawing instantly behind exhaust",
        "image_en": "Supersonic fighter jet releasing sleek ramjet missile, dramatic low angle, glowing pure red trajectory line, intense exhaust shockwaves, 8k cinematic, photorealistic, no text",
        "image_ko": "초음속 전투기에서 매끄러운 램제트 미사일 분리 발사, 극적인 로우 앵글, 붉게 빛나는 순수 빨간 궤적선, 강렬한 배기 충격파, 8k 시네마틱, 사실적, 텍스트 없음",
    },
    {
        "search_keyword": "전투기 조종석 HUD 계기판",
        "full_context": "초음속 전투기 조종석 내부에서 비행 계기판과 HUD 헤드업 디스플레이에 적기 타깃 락온 조준선이 붉게 표시되는 조종사 시점",
        "keywords": "조종석 HUD 화면, 비행 계기판, 타깃 락온",
        "motion_kr": "조종석 내부 계기판과 HUD 조준선을 클로즈업하며 전방 시야를 포착하는 푸시인 샷",
        "motion_en": "Slow cinematic push-in shot focusing on cockpit HUD target lock display, pilot gloved hand on throttle, glowing pure red targeting reticle",
        "image_en": "Close-up cinematic shot inside supersonic cockpit, HUD display glowing pure red target lock coordinates, pilot controls, 8k cinematic, photorealistic, no text",
        "image_ko": "초음속 조종석 내부 클로즈업 샷, 붉게 빛나는 순수 빨간 타깃 락 조준선 HUD 디스플레이, 조종석 제어 장치, 8k 시네마틱, 사실적, 텍스트 없음",
    },
    {
        "search_keyword": "전투기 애프터버너 수직 상승",
        "full_context": "초음속 전투기가 애프터버너 후기연소기를 최대 출력으로 점화하고 붉은 화염을 뿜으며 구름을 뚫고 수직 급상승하는 모습",
        "keywords": "초음속 급가속, 붉은 분사 화염, 구름 돌파",
        "motion_kr": "붉은 분사 화염을 뿜으며 구름과 지평선을 향해 초고속 급가속 돌파하는 트래킹 샷",
        "motion_en": "Fast tracking forward chase shot, rapid high-speed acceleration toward horizon, glowing pure red afterburner flame piercing clouds, vertical 9:16",
        "image_en": "Powerful fighter jet afterburner blast piercing clouds, dramatic sky horizon, glowing pure red flame plume, motion blur, 8k cinematic, photorealistic, no text",
        "image_ko": "구름을 뚫고 솟구치는 전투기 애프터버너 분사, 극적인 지평선, 붉게 빛나는 순수 빨간 화염 기둥, 모션 블러, 8k 시네마틱, 사실적, 텍스트 없음",
    },
    # Scene 2
    {
        "search_keyword": "덕티드 램제트 엔진 구조",
        "full_context": "극초음속 덕티드 램제트 공대공 미사일의 내부 공기 흡입구 및 가스 발생기 연소 메커니즘 정밀 3D 기술 단면도",
        "keywords": "램제트 엔진 메커니즘, 흡입구 공기역학, 3D 단면도",
        "motion_kr": "램제트 엔진 내부 기계 부품 메커니즘과 공기 흡입 구조를 360도 회전하며 훑는 오비탈 팬",
        "motion_en": "Dynamic orbital camera pan rotating around ramjet engine assembly, revealing internal air intake mechanics and fuel nozzles",
        "image_en": "Detailed 3D technical cutaway of ramjet propulsion system, supersonic airflow streamlines, glowing pure red combustion core, 8k cinematic, photorealistic, no text",
        "image_ko": "램제트 추진 시스템의 정밀 3D 기술 단면도, 초음속 공기 기류선, 붉게 빛나는 순수 빨간 연소 코어, 8k 시네마틱, 사실적, 텍스트 없음",
    },
    {
        "search_keyword": "항공우주 연소실 노즐 분사",
        "full_context": "항공우주 티타늄 합금 연소실 내부에서 고압 연료 인젝터 노즐이 초정밀 분사되며 고온 화염을 일으키는 시험 장면",
        "keywords": "초정밀 연료 분사구, 연소실 화염, 기계 부품 단면",
        "motion_kr": "초정밀 연료 분사 노즐과 연소실 고온 화염 반응을 극도로 확대하는 매크로 줌인 샷",
        "motion_en": "Extreme close-up macro pan focusing on high-pressure fuel injectors and combustion chamber ignition glow",
        "image_en": "Macro cinematic shot of aerospace titanium combustion chamber, glowing pure red flame swirl, engineering blueprint details, 8k cinematic, photorealistic, no text",
        "image_ko": "항공우주 티타늄 연소실 매크로 시네마틱 샷, 붉게 빛나는 순수 빨간 화염 소용돌이, 공학 청사진 세부사항, 8k 시네마틱, 사실적, 텍스트 없음",
    },
    {
        "search_keyword": "CFD 초음속 기류 시뮬레이션",
        "full_context": "마하 5 극초음속 비행 시 미사일 기체 표면에 형성되는 충격파 다이아몬드와 공기 마찰 열역학 압력을 계산하는 CFD 컴퓨터 유체 시뮬레이션 화면",
        "keywords": "컴퓨터 유체 시뮬레이션, 마하 5 충격파, 열역학 데이터",
        "motion_kr": "마하 5 초음속 비행 시 기체 표면 충격파와 공기 마찰열을 표시하는 시뮬레이션 데이터 샷",
        "motion_en": "Cinematic pan across computer fluid dynamics simulation screen, Mach 5 shockwave pressure lines and thermal gradient, vertical 9:16",
        "image_en": "Digital CFD airflow simulation monitor, hypersonic shock diamonds, glowing pure red velocity vectors around missile, 8k cinematic, photorealistic, no text",
        "image_ko": "디지털 CFD 기류 시뮬레이션 모니터, 극초음속 충격 다이아몬드, 미사일 주변 붉게 빛나는 순수 빨간 속도 벡터, 8k 시네마틱, 사실적, 텍스트 없음",
    },
    # Scene 3
    {
        "search_keyword": "순항 미사일 협곡 저공 비행",
        "full_context": "스텔스 순항 미사일이 적 레이더 탐지를 피하기 위해 붉은 암벽 사막 협곡 사이를 수 미터 고도로 초저공 지형추적 비행하는 모습",
        "keywords": "사막 협곡 초저공 비행, 암벽 회피, 고속 순항",
        "motion_kr": "거친 사막 협곡 암벽 사이를 초저공으로 아슬아슬하게 질주하는 다이내믹 팔로우 샷",
        "motion_en": "High-speed follow tracking shot skimming closely over rugged canyon terrain, dust kickup, intense speed sensation",
        "image_en": "Ultra-low altitude terrain following flight of stealth cruise missile through rugged canyon walls, glowing pure red intake ring, golden hour lighting, 8k cinematic, photorealistic, no text",
        "image_ko": "거친 협곡 암벽 사이를 초저공 지형추적 비행하는 스텔스 순항 미사일, 붉게 빛나는 순수 빨간 흡입구 링, 골든 아워 조명, 8k 시네마틱, 사실적, 텍스트 없음",
    },
    {
        "search_keyword": "미사일 카나드 날개 기동",
        "full_context": "적의 요격 미사일을 회피하기 위해 선단부 카나드 조종익 날개를 비틀며 고G 급선회 회전 기동하는 전술 미사일",
        "keywords": "고기동 급선회 기동, 날개 카나드 제어, 공기 마찰",
        "motion_kr": "표적 회피를 위해 날개 카나드를 비틀며 급격히 수직 상승하는 고기동 회전 샷",
        "motion_en": "Dynamic barrel roll camera movement capturing agile missile banking turn, atmospheric vapor ribbons forming on wingtips",
        "image_en": "High-G sharp tactical evasive missile maneuver, wingtip vortex trails, glowing pure red sensor lens, aggressive aerodynamic angle, 8k cinematic, photorealistic, no text",
        "image_ko": "고G 급격한 전술 회피 미사일 기동, 날개 끝 와류 궤적, 붉게 빛나는 순수 빨간 센서 렌즈, 공격적인 공기역학 각도, 8k 시네마틱, 사실적, 텍스트 없음",
    },
    {
        "search_keyword": "초음속 음속장벽 수증기 콘",
        "full_context": "음속 장벽 마하 1을 돌파하는 순간 기체 주변에 원형 수증기 충격파 콘이 형성되며 폭음과 함께 돌파하는 극적인 물리 현상",
        "keywords": "음속 돌파 충격파, 마하 다이아몬드, 폭음 분출",
        "motion_kr": "음속 장벽을 뚫으며 거대한 충격파 링을 뒤로 남기고 전방으로 사라지는 초고속 돌파 샷",
        "motion_en": "Fast tracking push shot capturing sonic boom vapor cone expansion, explosive burst into clear blue sky, vertical 9:16",
        "image_en": "Iconic transonic vapor cone formation around missile airframe, razor sharp shockwave barrier, glowing pure red exhaust trail, 8k cinematic, photorealistic, no text",
        "image_ko": "미사일 기체 주변의 음속 돌파 수증기 콘 형성, 날카로운 충격파 장벽, 붉게 빛나는 순수 빨간 배기 궤적, 8k 시네마틱, 사실적, 텍스트 없음",
    },
    # Scene 4
    {
        "search_keyword": "국방 연구소 미사일 개발",
        "full_context": "국방과학연구소 ADD 한국 과학자들이 텅 빈 전투기 무장 파일런 앞에 독자 기술 청사진을 펼치고 결의를 다지는 모습",
        "keywords": "한국 연구진 결의, 빈 무장 파일런, 독자 개발 청사진",
        "motion_kr": "텅 빈 전투기 날개 아래 결의를 다지는 한국 연구진을 둘러싸는 아크 카메라 회전 무빙",
        "motion_en": "Arc camera rotation moving around Korean researchers standing under empty fighter wing with firm determination, dramatic hangar lighting",
        "image_en": "Korean defense scientists standing before empty aircraft weapons pylon, holding blueprints, dramatic laboratory lighting, glowing pure red holographic schematic, 8k cinematic, photorealistic, no text",
        "image_ko": "텅 빈 전투기 무장 파일런 앞에 청사진을 들고 선 한국 국방 과학자들, 극적인 연구소 조명, 붉게 빛나는 순수 빨간 홀로그램 도면, 8k 시네마틱, 사실적, 텍스트 없음",
    },
    {
        "search_keyword": "항공우주 엔지니어 CAD 설계",
        "full_context": "항공우주 엔지니어들이 연구실 대형 모니터에서 미사일 3D CAD 부품 단면과 공기역학 원격 측정 데이터를 분석하며 회의하는 장면",
        "keywords": "연구소 설계 회의, CAD 도면 분석, 핵심 기술 토론",
        "motion_kr": "대형 모니터의 CAD 부품 설계도를 보며 열띤 기술 회의를 진행하는 연구원 클로즈업 샷",
        "motion_en": "Slow lateral tracking shot across engineering conference room, engineers analyzing 3D missile CAD models on holographic screens",
        "image_en": "Aerospace engineers in clean lab coats intensely reviewing missile telemetry, blueprints on monitors, glowing pure red CAD cursor lines, 8k cinematic, photorealistic, no text",
        "image_ko": "모니터의 미사일 원격 측정 및 도면을 집중 검토하는 항공우주 엔지니어들, 붉게 빛나는 순수 빨간 CAD 커서 라인, 8k 시네마틱, 사실적, 텍스트 없음",
    },
    {
        "search_keyword": "군용 미사일 조립 격납고",
        "full_context": "최첨단 국방 보안 격납고 조립 라인에서 제작 중인 국산 시제품 미사일 동체 골격과 정렬 레이저 가이드 조명",
        "keywords": "첨단 격납고 전경, 조립 라인, 시제품 골격",
        "motion_kr": "극비 시험 격납고 조명이 켜지며 제작 중인 국산 미사일 시제품 골격을 드러내는 와이드 틸트다운 샷",
        "motion_en": "Dramatic tilt-down revealing indigenous prototype missile frame on assembly rig inside high-security hangar, vertical 9:16",
        "image_en": "Wide architectural shot of state-of-the-art defense laboratory hangar, pristine prototype missile fuselage under spotlight, glowing pure red laser guides, 8k cinematic, photorealistic, no text",
        "image_ko": "최첨단 국방 연구 격납고의 와이드 건축 샷, 스포트라이트 아래 원형 미사일 동체, 붉게 빛나는 순수 빨간 레이저 가이드, 8k 시네마틱, 사실적, 텍스트 없음",
    },
    # Scene 5
    {
        "search_keyword": "초음속 풍동 시험장",
        "full_context": "초음속 풍동 시험 시설에서 고압 압축 공기 기류를 분사하며 미사일 시험 모델의 공기역학적 안정성과 기류선을 검증하는 모습",
        "keywords": "초음속 풍동 시험장, 고압 기류 분사, 기체 안정성",
        "motion_kr": "초음속 풍동 시설에서 맹렬한 고압 공기 속 버텨내는 시험체를 정면에서 관찰하는 줌인 샷",
        "motion_en": "Intense forward zoom shot inside supersonic wind tunnel, high-velocity airflow smoke trails flowing smoothly over test model",
        "image_en": "Supersonic wind tunnel test facility, high-pressure airflow streamlines illuminating aerodynamic stability of missile model, glowing pure red pressure sensor, 8k cinematic, photorealistic, no text",
        "image_ko": "초음속 풍동 시험 시설, 미사일 모델의 공기역학적 안정성을 보여주는 고압 기류선, 붉게 빛나는 순수 빨간 압력 센서, 8k 시네마틱, 사실적, 텍스트 없음",
    },
    {
        "search_keyword": "미사일 내열재 레이저 시험",
        "full_context": "미사일 노즈콘 표면의 특수 내열 세라믹 타일과 탄소 복합재에 레이저 계측기를 비추며 수천 도 마찰열 내구성을 측정하는 열화상 시험",
        "keywords": "고온 내열 센서 측정, 레이저 계측기, 표면 마찰열",
        "motion_kr": "수천 도의 마찰열을 견디는 특수 내열재 표면을 정밀 레이저로 스캔하는 매크로 트래킹 샷",
        "motion_en": "Precision macro tracking shot of laser scanning glowing ceramic heat shield tiles during thermal stress test",
        "image_en": "Thermal imaging test of missile nose cone, extreme heat friction glow, glowing pure red laser sensor grid overlays, laboratory setting, 8k cinematic, photorealistic, no text",
        "image_ko": "미사일 노즈콘 열화상 시험, 극심한 마찰열 발광, 붉게 빛나는 순수 빨간 레이저 센서 격자 오버레이, 연구소 환경, 8k 시네마틱, 사실적, 텍스트 없음",
    },
    {
        "search_keyword": "국방 연구원 미사일 발사 성공 환호",
        "full_context": "종합 시험 통제실 모니터에 최종 비행 시험 합격 판정이 표시되자 국방 연구원들이 일제히 환호하며 박수를 치는 감동적인 순간",
        "keywords": "최종 성능 검증 통과, 환호하는 연구원들, 모니터 합격 지표",
        "motion_kr": "시뮬레이션 모니터에 합격 그래프가 뜨자 일제히 환호하며 박수치는 연구진의 감동적 패닝 샷",
        "motion_en": "Slow pan across control room as engineers cheer and celebrate successful validation graphs on master displays, vertical 9:16",
        "image_en": "Joyful aerospace research team celebrating in mission control room, glowing pure red success status badge on main screen, dramatic ambient lighting, 8k cinematic, photorealistic, no text",
        "image_ko": "통제실에서 환호하며 자축하는 항공우주 연구팀, 메인 화면의 붉게 빛나는 순수 빨간 합격 상태 배지, 극적인 앰비언트 조명, 8k 시네마틱, 사실적, 텍스트 없음",
    },
    # Scene 6
    {
        "search_keyword": "이동식 미사일 발사대 차량 TEL",
        "full_context": "군용 중형 이동식 발사대 차량 TEL이 유압 실린더를 작동시켜 미사일 발사관을 수직 공격 위치로 기립시키는 장면",
        "keywords": "이동식 발사대 기립, 유압 실린더 작동, 발사 카운트다운",
        "motion_kr": "발사 플랫폼이 수직으로 서서히 기립하며 최종 발사 카운트다운에 들어가는 로우 앵글 틸트업 샷",
        "motion_en": "Epic low-angle tilt-up shot of mobile launcher erector elevating missile into vertical firing position, hydraulic steam venting",
        "image_en": "Heavy military mobile launch vehicle erecting sleek missile into vertical attack stance, dawn sky backdrop, glowing pure red warning indicator, 8k cinematic, photorealistic, no text",
        "image_ko": "수직 공격 태세로 미사일을 기립시키는 중형 군용 이동식 발사 차량, 여명 하늘 배경, 붉게 빛나는 순수 빨간 경고 표시등, 8k 시네마틱, 사실적, 텍스트 없음",
    },
    {
        "search_keyword": "미사일 발사대 로켓 화염 점화",
        "full_context": "카운트다운 0과 동시에 로켓 모터 1단 부스터가 폭발적으로 점화되며 발사대 바닥으로 거대한 화염 폭풍과 연기를 내뿜는 순간",
        "keywords": "로켓 1단 점화, 거대한 화염 폭풍, 지면 충격파",
        "motion_kr": "카운트다운 0과 함께 로켓 노즐에서 화염 폭풍이 지면을 강타하며 솟구쳐 오르는 고속 슬로우 샷",
        "motion_en": "Cinematic slow-motion shot of rocket booster ignition, massive fire cloud mushrooming across launch pad concrete",
        "image_en": "Explosive rocket motor ignition at launch pad, blinding blast shockwave, glowing pure red ignition core erupting, heavy concrete platform, 8k cinematic, photorealistic, no text",
        "image_ko": "발사대에서 폭발적인 로켓 모터 점화, 눈부신 폭풍 충격파, 분출하는 붉게 빛나는 순수 빨간 점화 코어, 육중한 콘크리트 플랫폼, 8k 시네마틱, 사실적, 텍스트 없음",
    },
    {
        "search_keyword": "수직 발사 미사일 연기 기둥",
        "full_context": "수직 발사된 초음속 미사일이 두터운 흰색 연기 기둥을 지상에 남긴 채 굉음과 함께 하늘을 찢으며 치솟는 추적 샷",
        "keywords": "수직 상승 돌파, 굉음과 연기 기둥, 하늘로 직진",
        "motion_kr": "거대한 연기 기둥을 뚫고 굉음과 함께 수직으로 하늘을 찢으며 치솟는 상향 트래킹 샷",
        "motion_en": "Fast upward tracking shot pursuing missile as it rockets vertically through troposphere, trailing thick white smoke, vertical 9:16",
        "image_en": "Vertical lift-off tracking shot of supersonic missile ascending with raw power, towering smoke column, glowing pure red booster nozzle, 8k cinematic, photorealistic, no text",
        "image_ko": "강력한 힘으로 수직 상승하는 초음속 미사일 추적 샷, 거대한 연기 기둥, 붉게 빛나는 순수 빨간 부스터 노즐, 8k 시네마틱, 사실적, 텍스트 없음",
    },
    # Scene 7
    {
        "search_keyword": "미사일 광학 탐색기 표적 포착",
        "full_context": "미사일 전방 광학 및 레이더 탐색기가 짙은 안개 속 바다 위 적함 표적을 십자선 정중앙에 락온하고 붉은 조준 박스를 표시하는 시점",
        "keywords": "표적 탐색 레이더, 적함 탐지, 최종 타격 락온",
        "motion_kr": "미사일 탐색기 레이더가 적함을 정확히 포착하고 빨간 락온 박스를 띄우는 시점 샷",
        "motion_en": "First-person seeker view camera zooming onto naval target vessel on stormy sea, red targeting reticle locking on",
        "image_en": "Digital missile optical seeker heads-up display, enemy warship locked in crosshairs through heavy ocean mist, glowing pure red targeting box, 8k cinematic, photorealistic, no text",
        "image_ko": "디지털 미사일 광학 탐색기 HUD 화면, 짙은 바다 안개 속 십자선에 포착된 적함, 붉게 빛나는 순수 빨간 타깃 박스, 8k 시네마틱, 사실적, 텍스트 없음",
    },
    {
        "search_keyword": "초음속 순항 미사일 해면 밀착 비행",
        "full_context": "적 함정의 레이더망을 무력화하기 위해 거친 파도 수 미터 위를 스치듯 초저공으로 질주하는 시스키밍 해면밀착 초음속 순항 미사일",
        "keywords": "수면 밀착 시스키밍, 파도 스치는 초음속, 요격 회피",
        "motion_kr": "적 레이더를 피해 파도를 스치듯 해수면 수 미터 위를 초음속으로 질주하는 초근접 샷",
        "motion_en": "Ultra-low sea-skimming tracking shot slicing just above ocean waves at Mach 3, water spray vortex trailing behind",
        "image_en": "Sea-skimming supersonic cruise missile flying inches above choppy waves, intense speed wake, glowing pure red aerodynamic wingtips, 8k cinematic, photorealistic, no text",
        "image_ko": "거친 파도 바로 위를 스치듯 비행하는 해면밀착 초음속 순항 미사일, 강렬한 항적, 붉게 빛나는 순수 빨간 공기역학 날개 끝, 8k 시네마틱, 사실적, 텍스트 없음",
    },
    {
        "search_keyword": "해상 표적함 미사일 직격 폭발",
        "full_context": "가상 표적함 선체에 미사일이 직격 관통하며 거대한 화염 폭풍과 연쇄 폭발을 일으키고 표적을 침몰시키는 타격 순간",
        "keywords": "정밀 직격 타격, 거대한 화염 폭발, 표적 완파",
        "motion_kr": "적함 측면에 한 치의 오차 없이 직격하며 거대한 폭발 화염을 터뜨리는 결정적 슬로우 모션 샷",
        "motion_en": "Dramatic impact shot as missile penetrates target hull, erupting into a colossal fireball and secondary explosions, vertical 9:16",
        "image_en": "Devastating direct missile strike on target vessel, huge fireball explosion ripping through metal structure, glowing pure red shockwave ring, 8k cinematic, photorealistic, no text",
        "image_ko": "표적함에 가해지는 파괴적인 미사일 직격 타격, 금속 구조물을 찢는 거대한 화염 폭발, 붉게 빛나는 순수 빨간 충격파 링, 8k 시네마틱, 사실적, 텍스트 없음",
    },
    # Scene 8
    {
        "search_keyword": "KF-21 전투기 편대 비행",
        "full_context": "태극 마크를 단 대한민국 공군 국산 초음속 전투기 KF-21 편대가 한반도 산맥 상공을 당당히 가르며 영공 수호 편대 비행을 펼치는 웅장한 장면",
        "keywords": "대한민국 영공 수호 비행, 태극 마크, 초음속 편대",
        "motion_kr": "태극 마크를 단 전투기 편대가 푸른 대한민국 상공을 당당하게 가르는 웅장한 편대 비행 샷",
        "motion_en": "Majestic aerial tracking shot of fighter jet formation bearing Korean flag insignia soaring over blue skies",
        "image_en": "Aerial shot of indigenous supersonic fighters in tight echelon formation over Korean mountain peaks, glowing pure red wingtip navigation lights, sunlight, 8k cinematic, photorealistic, no text",
        "image_ko": "한국의 산맥 위를 밀집 편대 비행하는 국산 초음속 전투기들의 공중 샷, 붉게 빛나는 순수 빨간 날개 끝 항법등, 햇빛, 8k 시네마틱, 사실적, 텍스트 없음",
    },
    {
        "search_keyword": "전투기 날개 미사일 무장 장착",
        "full_context": "전투기 날개 파일런에 독자 개발된 첨단 미사일을 완벽히 장착하고 조종석 캐노피 속 조종사가 엄지손가락을 치켜세우며 자주국방 성공을 알리는 모습",
        "keywords": "자주국방 완성, 첨단 무장 장착, 신뢰의 미소",
        "motion_kr": "독자 개발된 첨단 미사일을 날개 밑에 장착한 채 조종사가 엄지손가락을 치켜세우는 클로즈업 샷",
        "motion_en": "Slow lateral pan from wing-mounted indigenous missile to pilot inside cockpit giving proud thumbs-up sign",
        "image_en": "Close-up of sleek indigenous missile mounted on fighter wing pylon, pilot visible in canopy saluting, glowing pure red missile seeker dome, 8k cinematic, photorealistic, no text",
        "image_ko": "전투기 날개 파일런에 장착된 매끄러운 국산 미사일 클로즈업, 캐노피 속 경례하는 조종사, 붉게 빛나는 순수 빨간 미사일 탐색기 돔, 8k 시네마틱, 사실적, 텍스트 없음",
    },
    {
        "search_keyword": "석양 속 전투기 편대 비행",
        "full_context": "황금빛 석양 지평선을 향해 순항하는 전투기 편대의 뒷모습과 자주국방의 미래 평화를 알리는 에픽 엔딩 풀샷",
        "keywords": "석양을 향한 비상, 영원한 평화, 찬란한 미래",
        "motion_kr": "황금빛 석양 속으로 편대가 끝없이 뻗어나가며 미래 자주국방의 승리를 알리는 엔딩 풀샷",
        "motion_en": "Slow cinematic pull-back establishing wide shot of fighter jets vanishing into brilliant golden sunset horizon, vertical 9:16",
        "image_en": "Epic cinematic ending shot of fighter aircraft cruising into glorious golden sunset, clouds glowing orange, glowing pure red distant afterburner dot, eternal peace, 8k cinematic, photorealistic, no text",
        "image_ko": "영광스러운 황금빛 석양 속으로 순항하는 전투기들의 에픽 시네마틱 엔딩 샷, 주황색으로 빛나는 구름, 붉게 빛나는 순수 빨간 원거리 애프터버너 점, 영원한 평화, 8k 시네마틱, 사실적, 텍스트 없음",
    },
]


def clean_image_prompt(p: str) -> str:
    """
    [섹션 2-1 규격 엄격 정제 함수]
    - 금지 문자: 따옴표(""), 괄호(), 대시(—, -), 세미콜론(;) 사용 금지, 쉼표(,)로만 연결
    - glowing pure red 발광 포인트 필수 포함
    - 품질 태그(8k cinematic, photorealistic, no text) 필수 포함
    """
    if not p:
        return "Cinematic shot, dramatic composition, glowing pure red focal accent, 8k cinematic, photorealistic, no text"

    # 금지 문자 제거 및 쉼표 연결
    cleaned = re.sub(r'["\'\(\)\[\]—–;\-]', ' ', p)
    cleaned = re.sub(r'\s*,\s*', ', ', cleaned)
    cleaned = re.sub(r'\s+', ' ', cleaned).strip(' ,')

    # glowing pure red 보장
    if "glowing pure red" not in cleaned.lower():
        cleaned = f"{cleaned}, glowing pure red point"

    # 품질 태그 보장
    if "8k cinematic, photorealistic, no text" not in cleaned.lower():
        cleaned = f"{cleaned}, 8k cinematic, photorealistic, no text"

    # 이중 쉼표 및 공백 최종 정리
    cleaned = re.sub(r',\s*,+', ', ', cleaned)
    cleaned = re.sub(r'\s+', ' ', cleaned).strip(' ,')
    return cleaned


def split_script_into_scenes(text: str) -> list:
    """
    입력된 전체 대본을 [Scene N], 씬 N, 또는 단락/문장 단위로 범용(가변 N개) 분할합니다.
    - 8개 고정이 아닌 대본에 실제 존재하는 N개의 씬을 그대로 반환 (3개, 5개, 8개, 12개 등 자유)
    - [Scene N] 태그가 없더라도 줄바꿈/단락 기준으로 자동 분할
    """
    if not text or not text.strip():
        return []

    # [IMAGE_PROMPTS_START] 또는 섹션 마커가 붙어있는 경우 대본 영역만 분리
    script_part = text.strip()
    split_markers = [
        "[IMAGE_PROMPTS_START]", "섹션 2-1", "섹션 2", "[섹션 2", "IMAGE PROMPTS",
        "[MOTION_PROMPTS_START]", "섹션 3", "[섹션 3", "=== SCENE 1 ===", "=== SCENE 1"
    ]
    for sm in split_markers:
        if sm in script_part:
            script_part = script_part.split(sm, 1)[0].strip()

    # 1. 태그 기반 파싱: [Scene N], [씬 N], Scene N:, 씬 N: 등
    tag_pattern = r'(?:\[(?:Scene|씬)\s*\d+\]|(?:Scene|씬)\s*\d+[\s:.-]+)'
    raw_scenes = re.findall(
        rf'{tag_pattern}\s*(.*?)(?={tag_pattern}|\Z)',
        script_part,
        re.DOTALL | re.IGNORECASE,
    )
    parsed_scenes = []
    for s in raw_scenes:
        s_clean = re.split(r"(?:Shot\s*\d-\d|Shot\s*\d\s*:)", s, flags=re.IGNORECASE)[0].strip()
        cleaned = re.sub(r'\s*\(\d+자\)\s*$', '', s_clean).strip()
        # 양끝 따옴표 정리
        cleaned = re.sub(r'^["\']|["\']$', '', cleaned).strip()
        if cleaned:
            parsed_scenes.append(cleaned)

    if parsed_scenes:
        return parsed_scenes

    # 2. 태그가 없는 일반 대본: 2연속 줄바꿈(단락) 단위 분할
    paras = [p.strip() for p in script_part.split('\n\n') if p.strip()]
    cleaned_paras = []
    for p in paras:
        p_clean = re.sub(r'^["\']|["\']$', '', p).strip()
        if p_clean:
            cleaned_paras.append(p_clean)

    if len(cleaned_paras) >= 2:
        return cleaned_paras

    # 3. 1줄 단위 분할
    lines = [l.strip() for l in script_part.split('\n') if l.strip()]
    if len(lines) >= 2:
        return lines

    return [script_part.strip()]


def get_shot_index(scene_idx: int, shot_idx: int) -> int:
    """1-based scene_idx (1~8), shot_idx (1~3) -> 0-based 24개 인덱스 (0~23)"""
    return (scene_idx - 1) * 3 + (shot_idx - 1)


def _call_gemini_api(prompt: str, gemini_api_key: str, json_mode: bool = False) -> str:
    """google.genai 및 legacy google.generativeai를 순차 시도하여 최신 모델로 초고속 응답 텍스트를 반환합니다."""
    if not gemini_api_key:
        return ""

    candidate_models = [
        "gemini-3.1-flash-lite",
        "gemini-3.1-flash-lite-preview",
        "gemini-3.5-flash-lite",
        "gemini-flash-lite-latest",
        "gemini-3.8-flash",
        "gemini-flash-latest",
    ]

    # 1. 최신 google.genai Client 시도 (attempts=1, timeout=12s로 랙/지연 원천 차단)
    if HAS_NEW_GENAI:
        try:
            http_opt = None
            if hasattr(genai_types, "HttpOptions") and hasattr(genai_types, "HttpRetryOptions"):
                retry_opt = genai_types.HttpRetryOptions(attempts=1)
                http_opt = genai_types.HttpOptions(timeout=12000, retry_options=retry_opt)
            client = genai.Client(api_key=gemini_api_key, http_options=http_opt)
            config = {"response_mime_type": "application/json"} if json_mode else None
            for model_name in candidate_models:
                try:
                    resp = client.models.generate_content(
                        model=model_name,
                        contents=prompt,
                        config=config,
                    )
                    if resp and resp.text:
                        return resp.text.strip()
                except Exception as me:
                    print(f"[_call_gemini_api] genai model {model_name} failed: {me}")
                    continue
        except Exception as ce:
            print(f"[_call_gemini_api] genai Client error: {ce}")

    # 2. 레거시 google.generativeai 폴백
    try:
        legacy_genai.configure(api_key=gemini_api_key)
        for model_name in candidate_models:
            try:
                gen_cfg = {"response_mime_type": "application/json"} if json_mode else None
                model = legacy_genai.GenerativeModel(model_name, generation_config=gen_cfg)
                resp = model.generate_content(prompt)
                if resp and resp.text:
                    return resp.text.strip()
            except Exception as le:
                print(f"[_call_gemini_api] legacy model {model_name} failed: {le}")
                continue
    except Exception as outer_e:
        print(f"[_call_gemini_api] legacy configuration error: {outer_e}")

    return ""


def clean_tts_narration_line(text: str) -> str:
    """
    젬스(Gems) [외부 TTS 클린 규격]:
    - 따옴표(""), 괄호(), 대시(-), 슬래시(/) 배제.
    - 물음표(?)는 마침표(.)로 변환하여 TTS 억양 왜곡 및 화면 글자 왜곡을 원천 방지.
    """
    t = text.strip()
    t = re.sub(r'["\'\(\)\[\]—–/\\]', ' ', t)
    t = t.replace('?', '.')
    t = re.sub(r'\s*,\s*', ', ', t)
    t = re.sub(r'\s*\.\s*', '. ', t)
    t = re.sub(r'\s+', ' ', t).strip(' ,')
    return t


def generate_gems_script(
    topic: str,
    twist_point: str = "",
    mode: str = "standard",
    locked_scenes: dict = None,
    gemini_api_key: str = "",
) -> dict:
    """
    사용자의 커스텀 젬스(Gems) [유튜브 쇼츠 3D 시뮬레이션·역사·공학 미스터리 전문 총괄 디렉터]
    8단계 텐션 서사 및 씬 잠금(Locking) 규칙을 100% 반영한 전문 대본 생성 엔진.
    - mode="standard": 500~580자 내외 (스피디 1분 쇼츠)
    - mode="long": 700~800자 내외 (플로우 96초 비디오 풀 활용 딥 롱쇼츠)
    - locked_scenes: {scene_num: "원문 대본"} 확정된 씬은 1글자도 변경 없이 고정 유지
    """
    topic_clean = topic.strip() or "대한민국 초음속 미사일 개발 비화"
    twist_clean = twist_point.strip() or "일반인이 몰랐던 충격적인 물리적/공학적 반전 메커니즘"

    # URL 또는 유튜브 링크 입력 감지 및 실제 내용/자막 자동 추출
    url_info = extract_url_or_topic_context(topic_clean)
    if url_info.get("is_url"):
        if not url_info.get("success"):
            err_msg = url_info.get("error") or "해당 링크의 영상 정보(제목/자막)를 불러올 수 없습니다."
            return {
                "title": "오류: 영상 정보 조회 실패",
                "scenes": [],
                "full_script": "",
                "total_chars": 0,
                "mode": mode,
                "error": err_msg,
                "url_info": url_info,
            }
        topic_title = url_info.get("title") or topic_clean
        ref_context = url_info.get("summary_text", "")
        reference_block = f"""

=== 🎬 [사용자가 제공한 원본 영상/자료 실제 분석 내용] ===
{ref_context}

🚨 [매우 중요 - 원작 팩트 준수 원칙]:
사용자가 제공한 위 원본 영상/자료의 실제 내용, 사실, 원리, 역사적 사건, 반전 포인트를 100% 충실하게 기반으로 하여 8개 씬 대본을 작성하세요.
절대로 위 원본 자료와 무관한 엉뚱한 상상의 무기나 미사일 이야기를 지어내지 마세요.
============================================================
"""
    else:
        topic_title = topic_clean
        reference_block = ""

    # 글자 수 가이드
    if mode == "long":
        length_guide = "전체 공백 포함 700~800자 내외 (씬당 약 85~100자, 플로우 96초 풀 활용 모드)"
        sc_len_hook = "약 75~85자"
        sc_len_mid = "약 85~100자"
        sc_len_end = "약 75~85자"
    else:
        length_guide = "전체 공백 포함 500~580자 내외 (씬당 약 60~75자, 1분 쇼츠 최적화 모드)"
        sc_len_hook = "약 55~65자"
        sc_len_mid = "약 60~75자"
        sc_len_end = "약 55~65자"

    locked_block = ""
    if locked_scenes:
        locked_lines = []
        for s_idx in sorted(locked_scenes.keys()):
            locked_lines.append(f"[Scene {s_idx} - 🔒 잠금 확정]\n{locked_scenes[s_idx]}")
        locked_block = "\n\n=== 🚨 [씬별 확정 잠금 (Locking) 필수 준수] ===\n" + \
            "아래에 [🔒 잠금 확정]으로 표시된 씬은 사용자가 확정한 원문입니다. 단 한 글자나 조사도 변경 없이 100% 원문 그대로 출력하고, 나머지 미확정 씬만 새로 작성하세요:\n" + \
            "\n".join(locked_lines) + "\n============================================\n"

    prompt = f"""당신은 유튜브 쇼츠 3D 시뮬레이션·역사·공학 미스터리 콘텐츠 전문 총괄 디렉터입니다.
주어진 규칙을 엄격히 준수하여 유튜브 쇼츠 8개 씬 대본을 작성하세요.

=== 사용자가 제시한 주제 및 기획 ===
- 대상/건축물/사건: {topic_title}
- 핵심 반전 내용/전달 포인트: {twist_clean}
{reference_block}
{locked_block}

=== [1. 대본 작성 필수 규칙 (외부 TTS 전용, 총 8개 씬)] ===
1. 분량 제어: {length_guide} 엄수.
2. 8단계 텐션 서사 구조:
   - [Scene 1] ({sc_len_hook}): 상식 파괴 후킹 및 문제 제기 (시청자 스크롤 정지)
   - [Scene 2] ({sc_len_mid}): 배경 상황 및 압도적 제약 조건
   - [Scene 3] ({sc_len_mid}): 1차 시도 및 물리적 난관
   - [Scene 4] ({sc_len_mid}): 한계 봉착 및 자문자답
   - [Scene 5] ({sc_len_mid}): 뜻밖의 실마리 및 관점 전환
   - [Scene 6] ({sc_len_mid}): 핵심 반전 메커니즘 및 원리 증명 (물리/공학적 사실)
   - [Scene 7] ({sc_len_mid}): 극적인 성공 및 파급력
   - [Scene 8] ({sc_len_end}): 통념을 뒤엎는 요약 및 여운 넘치는 클로징
3. 문체 및 어조: 단문 위주, 어미 교차 (~습니다 / ~거든요 / ~죠 / ~겁니다 / ~셈입니다). 찰지고 귀에 꽂히는 구어체.
4. TTS 클린 규격: 따옴표(""), 큰따옴표, 물음표(?), 대시(-), 슬래시(/) 등 배제. 마침표(.)와 쉼표(,) 위주로만 구성 (발음 씹힘 및 화면 글자 왜곡 원천 차단).

반드시 아래 JSON 포맷으로만 응답하세요:
{{
  "title": "대표 후킹 제목",
  "scenes": [
    {{
      "scene_num": 1,
      "stage": "상식 파괴 후킹",
      "narration": "서울에서 부산까지 단 삼 분 만에 주파하는 비행체가 실제로 존재합니다."
    }},
    {{
      "scene_num": 2,
      "stage": "배경 상황 및 제약 조건",
      "narration": "음속의 열 배를 넘나드는 극한의 환경에서는 어떤 레이더도 추적할 수 없습니다."
    }},
    {{
      "scene_num": 3,
      "stage": "1차 시도 및 물리적 난관",
      "narration": "하지만 마찰열이 수천 도까지 치솟으며 기체가 타버리는 치명적 난관이 발생했죠."
    }},
    {{
      "scene_num": 4,
      "stage": "한계 봉착 및 자문자답",
      "narration": "현대 공학으로는 도저히 버틸 수 없다는 절망적인 결론에 부딪혔던 셈입니다."
    }},
    {{
      "scene_num": 5,
      "stage": "뜻밖의 실마리 및 관점 전환",
      "narration": "그런데 한국 연구진은 열을 막는 대신 충격파를 역이용하는 발상의 전환을 시도합니다."
    }},
    {{
      "scene_num": 6,
      "stage": "핵심 반전 메커니즘 증명",
      "narration": "특수 흡입구로 공기를 삼켜 스스로 냉각하는 혁신적인 공학 기술을 증명해냈거든요."
    }},
    {{
      "scene_num": 7,
      "stage": "극적인 성공 및 파급력",
      "narration": "결국 시험 발사는 대성공을 거두며 세계 군사 지도를 단숨에 뒤흔들어 놓았습니다."
    }},
    {{
      "scene_num": 8,
      "stage": "통념을 뒤엎는 요약 클로징",
      "narration": "불가능을 상식으로 바꾼 대한민국의 압도적 기술력, 바로 그 실체인 것입니다."
    }}
  ]
}}"""

    raw_res = _call_gemini_api(prompt, gemini_api_key, json_mode=True) if gemini_api_key else ""
    parsed_scenes = []
    title = f"{topic_clean}의 숨겨진 진실"

    if raw_res:
        try:
            m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", raw_res, re.DOTALL)
            json_str = m.group(1) if m else raw_res
            data = json.loads(json_str)
            title = data.get("title", title)
            raw_scenes = data.get("scenes", [])
            if len(raw_scenes) >= 8:
                for sc in raw_scenes[:8]:
                    s_num = sc.get("scene_num", len(parsed_scenes) + 1)
                    # 잠금된 씬이 있다면 사용자의 원문 보존
                    if locked_scenes and s_num in locked_scenes:
                        clean_narr = locked_scenes[s_num]
                    else:
                        clean_narr = clean_tts_narration_line(sc.get("narration", ""))
                    parsed_scenes.append({
                        "scene_num": s_num,
                        "stage": sc.get("stage", f"Scene {s_num}"),
                        "narration": clean_narr,
                    })
        except Exception as e:
            print(f"[generate_gems_script] JSON parse failed: {e}")

    # 파싱 실패 시 폴백 대본
    if len(parsed_scenes) < 8:
        stages = [
            "상식 파괴 후킹", "배경 상황 및 제약 조건", "1차 시도 및 물리적 난관",
            "한계 봉착 및 자문자답", "뜻밖의 실마리 및 관점 전환",
            "핵심 반전 메커니즘 증명", "극적인 성공 및 파급력", "통념을 뒤엎는 요약 클로징"
        ]
        default_narrs = [
            f"{topic_title}, 상상을 초월하는 비밀이 실제로 존재합니다.",
            "극단적인 물리적 제약 속에서 전 세계가 불가능하다고 단언했던 도전이었죠.",
            "초기 시도에서는 엄청난 난관에 부딪히며 모든 시험이 무산될 위기에 처했습니다.",
            "도대체 무엇이 문제였을까요, 통상적인 기술로는 도저히 깰 수 없는 한계였던 셈입니다.",
            "그런데 아무도 주목하지 않았던 의외의 지점에서 결정적인 실마리가 발견됩니다.",
            f"바로 {twist_clean} 원리를 정밀하게 역이용한 발상의 대전환이었거든요.",
            "결과는 대성공이었고, 현장의 모든 전문가들을 충격에 빠뜨리며 실력을 입증했습니다.",
            f"{topic_title} 뒤에 숨겨진 놀라운 공학의 비밀, 그 실체인 것입니다."
        ]
        parsed_scenes = []
        for i in range(1, 9):
            if locked_scenes and i in locked_scenes:
                narr = locked_scenes[i]
            else:
                narr = clean_tts_narration_line(default_narrs[i - 1])
            parsed_scenes.append({
                "scene_num": i,
                "stage": stages[i - 1],
                "narration": narr,
            })

    script_blocks = [f"[Scene {s['scene_num']}]\n{s['narration']}" for s in parsed_scenes]
    full_script = "\n\n".join(script_blocks)
    total_chars = len(re.sub(r'\[Scene\s*\d+\]|\s', '', full_script))

    return {
        "title": title,
        "scenes": parsed_scenes,
        "full_script": full_script,
        "total_chars": total_chars,
        "mode": mode,
        "url_info": url_info if url_info.get("is_url") else None,
    }


def generate_viral_script_candidates(topic: str, gemini_api_key: str) -> dict:
    """
    주제 1줄을 입력받아 떡상 4단계 텐션 구조(후킹-호기심-수치폭탄-결말보상)를 반영한
    2가지 대본 초안(Draft A: 도파민/수치형 vs Draft B: 호기심/미스터리형) 및 후킹 제목 3선을 생성합니다.
    """
    topic_clean = topic.strip()
    if not topic_clean:
        topic_clean = "대한민국 초음속 미사일 개발 비화"

    prompt = f"""당신은 대한민국 최고의 유튜브 쇼츠 바이럴 전문 기획자이자 과학/지식 팩트체커입니다.
사용자가 입력한 주제를 바탕으로 유튜브 알고리즘을 터뜨릴 수 있는 **서로 다른 매력의 2가지 쇼츠 대본(Draft A, Draft B)**과 후킹 제목 3선을 작성하세요.

=== 사용자가 지정한 주제 ===
{topic_clean}

=== [핵심 기획 4대 절대 원칙] ===
1. 🎯 정밀한 마이크로 팩트 & 구조적 디테일 (Micro Facts & Detail):
   - "엄청 빠릅니다", "놀랍습니다" 같은 뻔한 수식어는 절대 금지!
   - 해당 주제의 미세한 과학적/물리적 메커니즘과 정밀한 수치를 최소 2개 이상 구체적으로 포함하세요.
2. 🔥 압도적인 매크로 스케일 & 체감 단위 환산 (Macro Scale & Everyday Comparison):
   - 전체 총량(억/조 단위 등)이나 거대한 규모를 말할 때는, 시청자가 머릿속에 즉시 그릴 수 있는 일상적 시각 단위로 반드시 환산하세요.
   - 예시: "올림픽 규격 수영장 6,400개", "50층 아파트 높이 150미터", "축구장 3배 크기", "서울 면적의 3배" 등.
3. 🎢 쇼츠 떡상 4단계 텐션 빌드업 (Pacing & Hooking):
   - [0~3초: 상식 충돌 후킹] 시청자가 당연하게 생각하는 상식을 단 한 문장으로 부수며 스크롤 정지.
   - [3~15초: 의문 심화 & 관찰 포인트] 낯선 관찰 포인트를 던져 "대체 왜 그럴까?" 호기심 갭 극대화.
   - [15~35초: 상태 변화 & 팩트 폭탄] "더 소름 돋는 건...", "그런데 여기서 반전이 일어납니다" 등 국면 전환과 미세 팩트 폭격.
   - [35~50초: 결말 인지 보상 & 펀치라인] 압도적 총량과 체감 환산 수치로 지적 카타르시스를 주는 여운 넘치는 마지막 한마디로 마무리.
4. ⏱️ 대본 분량 및 8개 씬 구조 (엄수!):
   - 각 draft는 반드시 정확히 8개의 씬([Scene 1]부터 [Scene 8])으로 구성되어야 합니다.
   - 총 분량은 공백 포함 **420자 ~ 520자 내외**로 꽉 찬 밀도로 작성하세요.
   - 찰진 구어체 낭독 톤 ("~거든요!", "~다니까요!", "~죠?")으로 작성하세요.

5. 🎬 [2-트랙(2-Track) 나레이션 vs 시각 풀 맥락 완전 분리 원칙]:
   쇼츠 대본은 시청 몰입을 위해 주어가 생략되거나 비유적 표현('괴물 미사일', '미쳤거든요', '소름 돋는 비밀')이 주로 사용됩니다.
   이미지 검색기가 이런 비유적 표현을 그대로 검색하면 엉뚱한 이미지를 가져오므로, 각 씬마다 반드시 아래 2개 트랙을 함께 생성하세요:
   - [narration]: 시청자 귀에 꽂히는 찰진 압축 구어체 나레이션 (TTS 음성 생성용).
   - [full_context]: 이미지 검색기가 맥락을 100% 이해할 수 있도록 생략된 주어, 구체적 기종/부품/기술명, 장소, 물리적 상황을 온전히 설명한 1~2문장의 객관적 사실 설명.
   - [search_keywords]: 네이버/다음/구글/빙 뉴스 보도자료 사진을 100% 찾을 수 있는 2~3단어 실물 명사구 (예: 'KF-21 미사일 발사', '덕티드 램제트 단면'). 비유적 수식어('괴물', '미쳤다') 절대 금지!
   - [search_keywords_en]: 해외 고해상도(4K/Wallpaper) 사진 검색용 영문 키워드 (예: 'KF-21 ramjet missile launch photo 4k').

=== [2가지 버전의 뚜렷한 연출 차별화] ===
- Draft A [도파민 폭발 / 상식 충돌 & 충격 수치형 (텐션형)]:
  * 빠른 템포와 쉴 틈 없는 수치 폭격! 시청각적 상상력을 자극하는 거대한 스케일 비교 중심.
- Draft B [호기심 뇌절 / 미스터리 & 단계적 반전형 (스토리텔링형)]:
  * "우리가 매일 보면서도 몰랐던 소름 돋는 비밀" 식의 서서히 조여오는 스토리텔링과 반전.

반드시 아래 JSON 포맷으로만 응답하세요:
{{
  "title_options": [
    "호기심 유발형 제목 1",
    "충격 팩트/숫자 환산형 제목 2",
    "상식 파괴/도파민형 제목 3"
  ],
  "main_title": "가장 강력한 대표 제목",
  "description": "설명란에 넣을 간략한 2~3줄 요약 문구 (별표나 따옴표 없이 평문)",
  "tags": "#키워드1 #키워드2 #키워드3 #쇼츠",
  "draft_a": {{
    "concept": "도파민 폭발 & 충격 수치 폭탄 (텐션형)",
    "hook": "첫 3초 후킹 대사",
    "full_script": "[Scene 1] 첫 번째 씬 나레이션...\\n\\n[Scene 2] 두 번째 씬 나레이션...",
    "scenes": [
      {{
        "scene_num": 1,
        "narration": "도망가도 끝까지 쫓아간다, 대한민국이 역대급 괴물 미사일을 개발해버렸습니다.",
        "full_context": "대한민국 공군 KF-21 전투기에서 발사되는 국산 장거리 덕티드 램제트 공대공 미사일의 초음속 분리 발사 장면",
        "search_keywords": "KF-21 미사일 발사",
        "search_keywords_en": "KF-21 ramjet missile launch photo 4k"
      }}
      // 총 8개 씬 (scene_num 1부터 8까지)
    ]
  }},
  "draft_b": {{
    "concept": "호기심 뇌절 & 미스터리 단계적 반전 (스토리텔링형)",
    "hook": "첫 3초 후킹 대사",
    "full_script": "[Scene 1] 첫 번째 씬 나레이션...\\n\\n[Scene 2] 두 번째 씬 나레이션...",
    "scenes": [
      {{
        "scene_num": 1,
        "narration": "첫 번째 씬 나레이션...",
        "full_context": "첫 번째 씬 생략된 주어와 구체적 물리적 실물 대상, 배경 상황 설명...",
        "search_keywords": "구체적 실물 명사 키워드",
        "search_keywords_en": "english 4k photo search keyword"
      }}
      // 총 8개 씬
    ]
  }}
}}
"""
    raw_text = _call_gemini_api(prompt, gemini_api_key, json_mode=True)
    if not raw_text:
        return {}

    try:
        m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", raw_text, re.DOTALL)
        json_str = m.group(1) if m else raw_text
        data = json.loads(json_str)

        # 씬 리스트 및 전체 대본(full_script) 2-트랙 상호 보정
        for key in ["draft_a", "draft_b"]:
            if key in data and isinstance(data[key], dict):
                sc_raw = data[key].get("scenes", [])
                structured_scenes = []
                narration_scenes = []

                for i, item in enumerate(sc_raw, 1):
                    if isinstance(item, dict):
                        narr = item.get("narration") or item.get("script") or ""
                        f_ctx = item.get("full_context") or ""
                        s_kw = item.get("search_keywords") or item.get("search_keyword") or ""
                        s_kw_en = item.get("search_keywords_en") or item.get("search_keyword_en") or ""
                        narr_clean = re.sub(r"^\[Scene\s*\d+\]\s*", "", narr.strip())
                        structured_scenes.append({
                            "scene_num": i,
                            "narration": narr_clean,
                            "full_context": f_ctx or f"Scene {i} 시각적 물리 상황: {s_kw}",
                            "search_keywords": s_kw or "실물 대상",
                            "search_keywords_en": s_kw_en or "photo 4k",
                        })
                        narration_scenes.append(narr_clean)
                    else:
                        sc_str = str(item).strip()
                        sc_clean = re.sub(r"^\[Scene\s*\d+\]\s*", "", sc_str)
                        narration_scenes.append(sc_clean)
                        structured_scenes.append({
                            "scene_num": i,
                            "narration": sc_clean,
                            "full_context": f"Scene {i} 시각적 물리 상황: {sc_clean[:35]}",
                            "search_keywords": "핵심 실물",
                            "search_keywords_en": "4k photo",
                        })

                # scenes_structured 및 순수 narration 리스트 분리 보존
                data[key]["scenes_structured"] = structured_scenes
                data[key]["scenes"] = narration_scenes

                # full_script 동기화
                full_sc = str(data[key].get("full_script") or "").strip()
                if narration_scenes and (not full_sc or len(full_sc) < 50):
                    assembled = []
                    for i, narr in enumerate(narration_scenes, 1):
                        assembled.append(f"[Scene {i}]\n{narr}")
                    data[key]["full_script"] = "\n\n".join(assembled)
                elif full_sc and not narration_scenes:
                    data[key]["scenes"] = split_script_into_scenes(full_sc)

        return data
    except Exception as e:
        print(f"[generate_viral_script_candidates] parse error: {e}")
        return {}


def normalize_script_for_tts(script_text: str, gemini_api_key: str = "") -> str:
    """
    TTS 음성 낭독 시 발음 오류/씹힘을 방지하기 위해 숫자, 영문, 특수문자를 100% 한글 발음으로 변환합니다.
    - 160억 -> 백육십억, 6,400개 -> 육천사백 개, KF-21 -> 케이에프이십일, 99% -> 구십구 퍼센트
    - 괄호, 지문 제거
    """
    if not script_text or not script_text.strip():
        return script_text

    # 1. Gemini AI를 통한 문맥 기반 정밀 음차 변환 시도
    if gemini_api_key:
        prompt = f"""아래 유튜브 쇼츠 대본을 TTS 음성 합성을 위해 모든 아라비아 숫자, 영문 알파벳, 단위, 특수문자를 100% 순수 한글 발음 기호로 변환하세요.

[절대 엄수 규칙]:
1. 모든 숫자는 한국어 고유어/한자어 발음으로 자연스럽게 변환 (예: 160억 -> 백육십억, 6,400개 -> 육천사백 개, 6개 -> 여섯 개, 30번 -> 서른 번, 150m -> 백오십 미터, 5초 -> 오 초).
2. 퍼센트 기호(%)는 반드시 '퍼센트'로 표기 (예: 99% -> 구십구 퍼센트).
3. 영문 단어 및 약어는 한국어 음차로 표기 (예: KF-21 -> 케이에프이십일, AI -> 에이아이, Mach -> 마하, NASA -> 나사).
4. 괄호 (), [], {{}} 및 지문은 전부 삭제하거나 내용만 자연스럽게 읽도록 풀어서 작성.
5. [Scene 1] ~ [Scene 8] 씬 번호 마커는 그대로 보존하고, 각 씬 대사 내부에는 영어 알파벳과 아라비아 숫자가 단 한 글자도 남아있지 않아야 함.

=== 원본 대본 ===
{script_text}

반드시 변환된 한글 대본만 평문으로 출력하세요 (추가 인사말이나 마크다운 설명 금지):"""
        normalized = _call_gemini_api(prompt, gemini_api_key, json_mode=False)
        if normalized and "[Scene" in normalized:
            return normalized.strip()

    # 2. 규칙 기반(Regex) 빠른 1차 폴백 정규화
    text = script_text

    # 단위 및 기호 치환
    replacements = [
        (r'(\d+)\s*%', r'\1 퍼센트'),
        (r'(\d+)\s*km/h', r'\1 킬로미터 퍼 아워'),
        (r'(\d+)\s*km', r'\1 킬로미터'),
        (r'(\d+)\s*m\b', r'\1 미터'),
        (r'(\d+)\s*kg', r'\1 킬로그램'),
        (r'(\d+)\s*cm', r'\1 센티미터'),
        (r'(\d+)\s*mm', r'\1 밀리미터'),
        (r'\bKF-21\b', '케이에프이십일'),
        (r'\bKF21\b', '케이에프이십일'),
        (r'\bF-35\b', '에프삼십오'),
        (r'\bAI\b', '에이아이'),
        (r'\bHUD\b', '에이치유디'),
        (r'\bMach\b', '마하'),
        (r'\bCFD\b', '씨에프디'),
        (r'\bGPS\b', '지피에스'),
        (r'\b3D\b', '쓰리디'),
        (r'\b4K\b', '포케이'),
        (r'\b8K\b', '에이트케이'),
    ]
    for pat, rep in replacements:
        text = re.sub(pat, rep, text, flags=re.IGNORECASE)

    # 대사 내부 괄호 제거
    text = re.sub(r'\(([^)]*)\)', r'\1', text)

    return text.strip()


def validate_tts_script(script_text: str) -> dict:
    """TTS 대본에 음성 씹힘을 유발하는 영어 알파벳, 아라비아 숫자, 괄호가 남아있는지 정규식으로 검증합니다."""
    # [Scene X] 마커는 검증 대상에서 임시 제외
    clean_body = re.sub(r'\[Scene\s*\d+\]', '', script_text)

    issues = []
    if re.search(r'[A-Za-z]', clean_body):
        issues.append("영문 알파벳이 남아있습니다 (예: KF-21, AI 등 한글 음차 필요)")
    if re.search(r'\d', clean_body):
        issues.append("아라비아 숫자가 남아있습니다 (예: 160억, 99 등 한글 발음 변환 필요)")
    if '%' in clean_body:
        issues.append("퍼센트(%) 기호가 남아있습니다 ('퍼센트'로 표기 필요)")
    if re.search(r'[\(\)\[\]\{\}]', clean_body):
        issues.append("지문 또는 괄호 기호가 남아있습니다")

    return {
        "is_valid": len(issues) == 0,
        "issues": issues,
    }


def generate_director_pipeline_gemini(scenes: list, gemini_api_key: str, scene_contexts: list = None) -> dict:
    """
    Gemini API를 호출하여 '2-트랙(나레이션 vs 시각 풀 맥락/정밀 검색어)' 원칙 및
    '쇼츠 전문 총괄 디렉터 정밀 규칙'을 100% 준수하는
    섹션 2-1(32줄), 섹션 2-2(32줄), 섹션 3(8블록), 슬롯 24개(한글/영문 듀얼 검색어 및 full_context 포함)를 동적으로 생성합니다.
    """
    if not gemini_api_key:
        return {}

    scenes_lines = []
    for i, sc in enumerate(scenes, start=1):
        ctx_extra = ""
        if scene_contexts and i <= len(scene_contexts) and isinstance(scene_contexts[i - 1], dict):
            c = scene_contexts[i - 1]
            f_ctx = c.get("full_context", "")
            s_kw = c.get("search_keywords") or c.get("search_keyword", "")
            s_kw_en = c.get("search_keywords_en") or c.get("search_keyword_en", "")
            if f_ctx:
                ctx_extra = f"\n  (시각 풀 맥락: {f_ctx} | 추천 검색어: {s_kw} / {s_kw_en})"
        scenes_lines.append(f"[Scene {i}]\n{sc}{ctx_extra}")
    scenes_text = "\n\n".join(scenes_lines)

    prompt = f"""당신은 유튜브 쇼츠 전문 총괄 디렉터이자 비주얼 검색 엔지니어입니다.
아래 8개 씬 대본을 바탕으로 쇼츠 전문 총괄 디렉터 정밀 규칙에 따라 8개 씬(총 24개 샷) 데이터를 생성하세요.

=== 8개 씬 대본 ===
{scenes_text}

=== [핵심 기획 원칙: 2-트랙(2-Track) 나레이션 vs 시각 풀 맥락 완전 분리] ===
쇼츠 대본은 시청자 도파민과 후킹을 위해 주어가 생략되거나 극도로 압축된 구어체/비유적 표현('괴물 미사일', '미쳤거든요', '소름 돋는 비밀')이 주로 사용됩니다.
이미지 검색기가 이런 비유적 표현이나 구어체 문장을 검색어로 쓰면 완전히 엉뚱한 이미지를 가져옵니다!

따라서 각 씬과 각 샷마다 반드시 아래 2개 트랙을 엄격히 분리하여 생성하세요:

1. [트랙 1: 시청자용 압축 나레이션 (script)]:
   - 씬 대본의 찰진 TTS 구어체 대사를 유지합니다 (음성 합성 전용).

2. [트랙 2: 시각 검색용 풀 맥락 & 정밀 검색어 (full_context & search_keywords)]:
   - [full_context]: 검색 엔진이 맥락을 100% 이해할 수 있도록 생략된 주어(예: 대한민국 공군, KAI, 국방과학연구소 ADD), 구체적 물리적 실물 대상(예: KF-21 보라매, 덕티드 램제트 공대공 미사일 연소실), 배경 및 상황을 온전히 설명한 1~2문장의 객관적 물리 팩트 설명.
   - [search_keyword (한글 정밀 검색어)]: 구글/네이버/다음/빙 뉴스 보도자료 사진을 100% 찾을 수 있는 2~3단어의 구체적 고유명사+실물 명사 (예: 'KF-21 미사일 발사', '덕티드 램제트 단면', '전투기 조종석 HUD').
     * 절대 금지: '괴물', '미쳤다', '역대급', '비행하는 모습', '엄청난 위력' 등 비유적/추상적 표현 절대 금지!
     * 압축된 나레이션 문장을 검색어로 복사하거나 요약하는 행위 절대 금지!
   - [search_keyword_en (영문 정밀 검색어)]: 해외 고해상도(4K/Wallpaper) 사진 검색용 영문 명사구 (예: 'KF-21 fighter jet runway 4k', 'ramjet propulsion engine cutaway diagram', 'fighter jet cockpit HUD display').

3. [섹션 2-1: Flow 이미지 프롬프트 (정확히 32줄 밀착 규격)]
   - 헤더 규격: 정확히 8개의 헤더 (### EXT. TIME - LOCATION 또는 ### INT. TIME - LOCATION, 콜론 없음)
   - 샷 넘버링: 헤더 아래 빈 줄 없이 정확히 3줄 (Shot X-1:, Shot X-2:, Shot X-3:)
   - 포맷: 샷당 영문 15~20단어 (명사구 나열). [피사체 및 행동, 조명 및 구도, glowing pure red 발광 포인트, 품질 태그: 8k cinematic, photorealistic, no text]
   - Zero Blank Lines: 빈 줄 절대 없이 헤더 8개 + 샷 24줄 = 정확히 총 32줄 단일 블록.
   - 금지 문자: 따옴표(""), 괄호(), 대시(—), 세미콜론(;) 사용 금지, 쉼표(,)로만 연결.

4. [섹션 2-2: 샷별 한글 번역 및 검색 키워드 추출 (1:1 매칭 32줄)]
   - 섹션 2-1의 영문 32줄을 그대로 1:1 한글 직관 번역.

5. [섹션 3: 씬별 3-멀티샷 모션 프롬프트 (Keyframe 1:1 매칭 8개 개별 블록)]
   - 각 씬마다 3개 샷을 물리적 연속 동작으로 설계:
     * Shot X-1 (from Keyframe 1/Shot X-1): 시작 구도 및 초기 물리 모션
     * Shot X-2 (from Keyframe 2/Shot X-2): 중간 앵글 전환 및 연속 상태 변화
     * Shot X-3 (from Keyframe 3/Shot X-3): 종결 앵글, 최종 액션 완료 및 카메라 무빙, vertical 9:16
   - 상단에 해당 씬의 [TTS 대본] 필수 명시.

반드시 아래 JSON 포맷으로만 응답하세요:
{{
  "scenes": [
    {{
      "scene_num": 1,
      "header_en": "### EXT. DAY - AIRBASE RUNWAY",
      "header_ko": "### 외부. 낮 - 공군기지 활주로",
      "shots": [
        {{
          "shot_num": 1,
          "full_context": "대한민국 공군 KF-21 시제기가 활주로에서 지상 유도 주행을 하며 출격을 준비하는 장면",
          "search_keyword": "KF-21 전투기 활주로",
          "search_keyword_en": "KF-21 fighter jet runway sunrise 4k photo",
          "image_prompt": "Supersonic fighter jet taxiing on runway, dramatic sunrise lighting, glowing pure red engine nozzle, 8k cinematic, photorealistic, no text",
          "image_prompt_ko": "활주로를 유도 중인 초음속 전투기, 극적인 일출 조명, 붉게 빛나는 순수 빨간 엔진 노즐, 8k 시네마틱, 사실적, 텍스트 없음",
          "motion_ko": "활주로를 따라 전진하는 전투기 측면을 추적하는 로우 앵글 트래킹 샷",
          "motion_en": "Low angle tracking shot moving smoothly alongside fighter jet accelerating on runway, heat haze shimmering"
        }},
        {{
          "shot_num": 2,
          "full_context": "초음속 전투기 조종석 내부에서 HUD 계기판에 표적 락온 데이터가 표시되는 클로즈업",
          "search_keyword": "전투기 조종석 계기판 HUD",
          "search_keyword_en": "fighter jet cockpit heads up display HUD target lock",
          "image_prompt": "Fighter jet canopy reflection, pilot cockpit view, glowing pure red heads up display target lock, 8k cinematic, photorealistic, no text",
          "image_prompt_ko": "전투기 캐노피 반사, 조종석 시점, 붉게 빛나는 순수 빨간 HUD 타깃 락, 8k 시네마틱, 사실적, 텍스트 없음",
          "motion_ko": "조종석 내부로 천천히 줌인하며 HUD 타깃 조준선이 깜빡이는 푸시인 샷",
          "motion_en": "Cinematic slow push-in shot toward cockpit HUD system glowing with targeting coordinates"
        }},
        {{
          "shot_num": 3,
          "full_context": "전투기가 애프터버너를 점화하고 하늘로 수직 급상승하며 충격파를 형성하는 모습",
          "search_keyword": "전투기 애프터버너 수직 상승",
          "search_keyword_en": "supersonic fighter jet afterburner vertical climb clouds 4k",
          "image_prompt": "Fighter jet blasting into sky, afterburner shock diamonds, glowing pure red thruster flames, dynamic vertical angle, 8k cinematic, photorealistic, no text",
          "image_prompt_ko": "하늘로 솟구치는 전투기, 후기연소기 충격파, 붉게 빛나는 순수 빨간 추진 화염, 다이내믹 수직 앵글, 8k 시네마틱, 사실적, 텍스트 없음",
          "motion_ko": "강렬한 추진 화염을 뿜으며 구름을 뚫고 수직으로 솟구치는 상향 추적 샷",
          "motion_en": "Fast upward camera tracking following fighter jet rocketing into sky with intense afterburner flame, vertical 9:16"
        }}
      ]
    }}
    // 총 8개 씬 (scene_num 1부터 8까지 각각 3개 샷)
  ]
}}
"""

    raw_text = _call_gemini_api(prompt, gemini_api_key, json_mode=True)
    if not raw_text:
        return {}

    try:
        m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", raw_text, re.DOTALL)
        json_str = m.group(1) if m else raw_text
        data = json.loads(json_str)

        scenes_list = data.get("scenes", [])
        if len(scenes_list) >= 8:
            return parse_director_json(data, scenes)
    except Exception as e:
        print(f"[Gemini pipeline generation parse error]: {e}")

    return {}


def parse_director_json(data: dict, scenes: list) -> dict:
    """Gemini JSON 결과를 정밀 파싱하여 32줄 규격 및 24개 슬롯 리스트(full_context 포함)를 생성합니다."""
    sec21_lines = []
    sec22_lines = []
    sec3_by_scene = {}
    slots = []

    scenes_data = data.get("scenes", [])[:8]
    while len(scenes_data) < 8:
        scenes_data.append({"scene_num": len(scenes_data) + 1, "shots": []})

    for s_idx in range(1, 9):
        sc_data = scenes_data[s_idx - 1]
        sc_script = scenes[s_idx - 1] if s_idx <= len(scenes) else f"Scene {s_idx} 대본"

        h_en = sc_data.get("header_en", f"### EXT. DAY - SCENE {s_idx}").strip()
        if not h_en.startswith("###"):
            h_en = f"### {h_en}"
        h_en = re.sub(r':$', '', h_en).strip()

        h_ko = sc_data.get("header_ko", f"### 외부. 낮 - 씬 {s_idx}").strip()
        if not h_ko.startswith("###"):
            h_ko = f"### {h_ko}"
        h_ko = re.sub(r':$', '', h_ko).strip()

        sec21_lines.append(h_en)
        sec22_lines.append(h_ko)

        shots_list = sc_data.get("shots", [])[:3]
        sh_blocks = []

        for sh_idx in [1, 2, 3]:
            slot_num = (s_idx - 1) * 3 + sh_idx
            sh_data = shots_list[sh_idx - 1] if sh_idx <= len(shots_list) else {}

            img_p = clean_image_prompt(sh_data.get("image_prompt", ""))
            img_p_ko = sh_data.get("image_prompt_ko", "").strip() or "고화질 시네마틱 샷"
            search_kw = sh_data.get("search_keyword", "").strip() or sh_data.get("search_keywords", "").strip() or sh_data.get("target_keyword", "").strip() or "핵심 피사체"
            search_kw_en = sh_data.get("search_keyword_en", "").strip() or sh_data.get("search_keywords_en", "").strip()
            if not search_kw_en:
                tokens = [t for t in re.sub(r'[^a-zA-Z0-9\s]', ' ', img_p).split() if len(t) > 2]
                search_kw_en = " ".join(tokens[:4]) + " 4k photo" if tokens else f"Scene {s_idx} Shot {sh_idx} 4k"

            full_ctx = sh_data.get("full_context", "").strip()
            if not full_ctx:
                full_ctx = f"Scene {s_idx} Shot {sh_idx} 물리적 실물 상황: {search_kw}"

            m_ko = sh_data.get("motion_ko", "").strip() or "다이내믹 카메라 모션"
            m_en = sh_data.get("motion_en", "").strip() or "Dynamic camera motion tracking shot"
            if sh_idx == 3 and "vertical 9:16" not in m_en.lower():
                m_en = f"{m_en}, vertical 9:16"

            sec21_lines.append(f"Shot {s_idx}-{sh_idx}: {img_p}")
            sec22_lines.append(f"Shot {s_idx}-{sh_idx}: {img_p_ko} | 검색어: {search_kw} | 풀맥락: {full_ctx}")

            sh_blocks.append(
                f"[Shot {s_idx}-{sh_idx} (from Keyframe {sh_idx}/Shot {s_idx}-{sh_idx})]\n{m_ko}\n({m_en})"
            )

            slots.append({
                "slot_num": slot_num,
                "scene_num": s_idx,
                "shot_num": sh_idx,
                "target_filename": f"{s_idx}-{sh_idx}.png",
                "script": sc_script,                     # 트랙 1: 시청자용 압축 나레이션
                "full_context": full_ctx,                 # 트랙 2: 시각 검색용 풀 맥락 설명
                "search_keyword": search_kw,              # 트랙 2: 한글 정밀 검색어
                "search_keyword_en": search_kw_en,        # 트랙 2: 영문 정밀 검색어
                "target_keyword": search_kw,
                "motion_ko": m_ko,
                "motion_en": m_en,
                "image_prompt": img_p,
            })

        sec3_content = f"[TTS 대본]\n{sc_script}\n\n" + "\n\n".join(sh_blocks)
        sec3_by_scene[s_idx] = sec3_content

    return {
        "slots": slots,
        "scenes": scenes,
        "section_21": "\n".join(sec21_lines),  # 정확히 32줄
        "section_22": "\n".join(sec22_lines),  # 정확히 32줄
        "section_3": sec3_by_scene,            # {1: "...", ..., 8: "..."}
        "visual_keywords": [s["search_keyword"] for s in slots],
        "motion_prompts": [{"kr": s["motion_ko"], "en": s["motion_en"]} for s in slots],
        "image_prompts": [s["image_prompt"] for s in slots],
        "motion_prompts_by_scene": sec3_by_scene,
    }


def generate_director_pipeline_fallback(scenes: list) -> dict:
    """오프라인 또는 API 미사용 시 정밀 규칙을 100% 준수하는 고품질 폴백 생성기"""
    sec21_lines = []
    sec22_lines = []
    sec3_by_scene = {}
    slots = []

    scene_headers_en = [
        "### EXT. DAY - SUPERSONIC TEST RANGE",
        "### INT. DAY - AEROSPACE PROPULSION LAB",
        "### EXT. DAY - DESERT CANYON TERRAIN",
        "### INT. NIGHT - DEFENSE RESEARCH HANGAR",
        "### INT. DAY - SUPERSONIC WIND TUNNEL FACILITY",
        "### EXT. DAWN - MILITARY LAUNCH PLATFORM",
        "### EXT. DAY - OPEN OCEAN STRIKE ZONE",
        "### EXT. SUNSET - HOMELAND MOUNTAIN AIRSPACE",
    ]
    scene_headers_ko = [
        "### 외부. 낮 - 초음속 시험장",
        "### 내부. 낮 - 항공우주 추진 연구소",
        "### 외부. 낮 - 사막 협곡 비행 구역",
        "### 내부. 밤 - 국방 연구 격납고",
        "### 내부. 낮 - 초음속 풍동 시험장",
        "### 외부. 여명 - 이동식 발사대 기지",
        "### 외부. 낮 - 해상 표적 타격 구역",
        "### 외부. 석양 - 조국 영공 수호 비행",
    ]

    for s_idx in range(1, 9):
        sc_script = scenes[s_idx - 1] if s_idx <= len(scenes) else f"Scene {s_idx} 대본"
        h_en = scene_headers_en[s_idx - 1]
        h_ko = scene_headers_ko[s_idx - 1]

        sec21_lines.append(h_en)
        sec22_lines.append(h_ko)

        sh_blocks = []
        for sh_idx in [1, 2, 3]:
            slot_num = (s_idx - 1) * 3 + sh_idx
            p_idx = slot_num - 1
            preset = SHOT_PRESETS_24[p_idx] if p_idx < len(SHOT_PRESETS_24) else SHOT_PRESETS_24[0]

            img_p = clean_image_prompt(preset.get("image_en", ""))
            img_p_ko = preset.get("image_ko", "고화질 시네마틱 샷")
            search_kw = preset.get("search_keyword", "") or preset.get("keywords", "핵심 피사체")
            full_ctx = preset.get("full_context") or f"대한민국 최첨단 항공우주 핵심 기술: {search_kw}"
            tokens = [t for t in re.sub(r'[^a-zA-Z0-9\s]', ' ', img_p).split() if len(t) > 2]
            search_kw_en = " ".join(tokens[:4]) + " 4k photo" if tokens else f"Scene {s_idx} Shot {sh_idx} 4k"
            m_ko = preset.get("motion_kr", "카메라 트래킹 샷")
            m_en = preset.get("motion_en", "Camera tracking shot")
            if sh_idx == 3 and "vertical 9:16" not in m_en.lower():
                m_en = f"{m_en}, vertical 9:16"

            sec21_lines.append(f"Shot {s_idx}-{sh_idx}: {img_p}")
            sec22_lines.append(f"Shot {s_idx}-{sh_idx}: {img_p_ko} | 검색어: {search_kw} | 풀맥락: {full_ctx}")

            sh_blocks.append(
                f"[Shot {s_idx}-{sh_idx} (from Keyframe {sh_idx}/Shot {s_idx}-{sh_idx})]\n{m_ko}\n({m_en})"
            )

            slots.append({
                "slot_num": slot_num,
                "scene_num": s_idx,
                "shot_num": sh_idx,
                "target_filename": f"{s_idx}-{sh_idx}.png",
                "script": sc_script,
                "full_context": full_ctx,
                "search_keyword": search_kw,
                "search_keyword_en": search_kw_en,
                "target_keyword": search_kw,
                "motion_ko": m_ko,
                "motion_en": m_en,
                "image_prompt": img_p,
            })

        sec3_content = f"[TTS 대본]\n{sc_script}\n\n" + "\n\n".join(sh_blocks)
        sec3_by_scene[s_idx] = sec3_content

    return {
        "slots": slots,
        "scenes": scenes,
        "section_21": "\n".join(sec21_lines),  # 정확히 32줄
        "section_22": "\n".join(sec22_lines),  # 정확히 32줄
        "section_3": sec3_by_scene,
        "visual_keywords": [s["search_keyword"] for s in slots],
        "motion_prompts": [{"kr": s["motion_ko"], "en": s["motion_en"]} for s in slots],
        "image_prompts": [s["image_prompt"] for s in slots],
        "motion_prompts_by_scene": sec3_by_scene,
    }


def build_24_shot_pipeline(bulk_text: str = "", scenes: list = None, gemini_api_key: str = "", scene_contexts: list = None) -> dict:
    """
    [쇼츠 전문 총괄 디렉터 정밀 규칙 기반 에셋 생성 파이프라인]
    1단계: 입력된 전체 대본을 [Scene 1]부터 [Scene 8]까지 8개 씬으로 분할.
    2단계: Gemini API 호출 (또는 정밀 폴백)로 2-트랙 구조(나레이션 vs 시각 풀 맥락/정밀 검색어) 동적 생성.
    3단계: 슬롯 데이터 1~24번 1차원 평탄화(Flatten) 반환.
    """
    # 1. 씬 분할
    parsed_scenes = split_script_into_scenes(bulk_text if bulk_text else ("\n".join(scenes) if scenes else ""))

    # 2. Gemini 호출 시도
    result = {}
    if gemini_api_key:
        result = generate_director_pipeline_gemini(parsed_scenes, gemini_api_key, scene_contexts=scene_contexts)

    # 3. 실패 또는 API 키 부재 시 폴백 생성 (표준 24개 샷 기준)
    expected_slots = 24
    if not result or not result.get("slots") or len(result["slots"]) < expected_slots:
        result = generate_director_pipeline_fallback(parsed_scenes)

    # 4. 입력 텍스트에 이미 Shot X-Y 오버라이드가 있는 경우 반영
    if bulk_text and ("Shot 1-1" in bulk_text or "Shot 1:" in bulk_text):
        for s in result["slots"]:
            sc = s["scene_num"]
            sh = s["shot_num"]
            m_kw = re.search(rf"Shot\s*{sc}-{sh}[^:]*:[^|]*\|\s*키워드\s*:\s*([^\n]+)", bulk_text, re.I)
            if m_kw:
                s["target_keyword"] = m_kw.group(1).strip()
                s["search_keyword"] = m_kw.group(1).strip()

    return result


# ════════════════════════════════════════════════════════════
# 하위 호환성 유지 래퍼 함수들
# ════════════════════════════════════════════════════════════
def get_shot_motion_prompt(assets: dict, sc_num: int, shot_num: int, raw_bulk_text: str = "") -> str:
    idx = get_shot_index(sc_num, shot_num)
    if assets and "slots" in assets and len(assets["slots"]) > idx:
        return assets["slots"][idx]["motion_en"]
    if 0 <= idx < len(SHOT_PRESETS_24):
        return SHOT_PRESETS_24[idx]["motion_en"]
    return f"Dynamic camera tracking Scene {sc_num} Shot {sc_num}-{shot_num}."


def get_shot_image_prompt(assets: dict, sc_num: int, shot_num: int, raw_bulk_text: str = "") -> str:
    idx = get_shot_index(sc_num, shot_num)
    if assets and "slots" in assets and len(assets["slots"]) > idx:
        return assets["slots"][idx]["image_prompt"]
    if 0 <= idx < len(SHOT_PRESETS_24):
        return SHOT_PRESETS_24[idx]["image_en"]
    return f"Ultra-detailed cinematic shot of Scene {sc_num} Shot {sc_num}-{shot_num}."


def translate_motion_to_korean(motion_prompt: str, shot_num: int = 1) -> str:
    return motion_prompt


def extract_target_keywords_from_shot(image_prompt: str, motion_prompt: str, visual_guide_kw: str = "", scene_text: str = "") -> str:
    return visual_guide_kw or "핵심 피사체"


def generate_pipeline_assets(scenes: list, gemini_api_key: str = "", raw_bulk_text: str = "") -> dict:
    return build_24_shot_pipeline(bulk_text=raw_bulk_text, scenes=scenes, gemini_api_key=gemini_api_key)


def extract_assets_from_bulk_text(bulk_text: str) -> dict:
    if not bulk_text or not bulk_text.strip():
        return {"scenes": [], "slots": []}
    return build_24_shot_pipeline(bulk_text=bulk_text)


def generate_assets(scenes: list, gemini_api_key: str) -> dict:
    pipeline = build_24_shot_pipeline(scenes=scenes, gemini_api_key=gemini_api_key)
    return {
        "section_21": pipeline.get("section_21", ""),
        "section_22": pipeline.get("section_22", ""),
        "section_3": "\n\n".join(pipeline.get("section_3", {}).values()),
        "slots": pipeline["slots"],
    }


# ════════════════════════════════════════════════════════════
# 🎬 Shorts Story Studio 전용 1씬 3멀티샷 & 에셋 자동화 엔진
# ════════════════════════════════════════════════════════════

def extract_core_assets_from_script(script_text: str, gemini_api_key: str = "") -> list:
    """
    전체 대본을 분석하여 Shorts Story Studio의 [2. 에셋] 탭에 등록해야 할
    핵심 개체(인물/장비/배경) 2~3개를 자동으로 감지하고 고화질 실사 검색어를 생성합니다.
    """
    if not script_text or not script_text.strip():
        script_text = "대한민국 극초음속 미사일 개발 및 표적 정밀 타격"

    if gemini_api_key:
        prompt = f"""당신은 AI 영상 제작(Shorts Story Studio) 에셋 디렉터입니다.
아래 유튜브 쇼츠 대본 전체를 정밀 분석하여, 영상 전반에 걸쳐 일관성을 유지하고
AI의 시각적 왜곡(Hallucination, 예: 한국 무기를 북한 무기로 그리는 현상 등)을 방지하기 위해
'에셋(Assets)'으로 반드시 등록해야 할 핵심 물리적 피사체 2~3개를 추출하세요.

=== 대본 내용 ===
{script_text}

=== 필수 요구사항 ===
1. [주인공 장비/인물]: 아군 무기/장비 또는 핵심 주체 (예: 대한민국 현무-5 탄도미사일, 한국형 KF-21 전투기)
2. [표적/배경 요새]: 타격 목표물 또는 주요 배경 (예: 적 지하 요새 벙커, 지휘 통제실)
3. 검색어(search_keyword)는 포털 뉴스 보도자료 실물 사진을 100% 찾을 수 있는 '구체적 실물 명사'로 작성.

반드시 아래 JSON 포맷으로만 응답하세요:
[
  {{
    "asset_num": 1,
    "name": "피사체 이름 (예: 현무-5 탄도미사일)",
    "type": "핵심 아군 무기",
    "search_keyword": "네이버/구글 실물 사진 검색어 (예: 현무-5 미사일 실물)",
    "search_keyword_en": "South Korean Hyunmoo 5 missile high resolution photo"
  }},
  {{
    "asset_num": 2,
    "name": "피사체 이름 (예: 적 지하 벙커 요새)",
    "type": "핵심 표적/배경",
    "search_keyword": "지하 요새 군사 벙커",
    "search_keyword_en": "military underground fortified command bunker"
  }}
]"""
        raw_res = _call_gemini_api(prompt, gemini_api_key, json_mode=True)
        if raw_res:
            try:
                m = re.search(r"```(?:json)?\s*(\[.*?\])\s*```", raw_res, re.DOTALL)
                json_str = m.group(1) if m else raw_res
                assets = json.loads(json_str)
                if isinstance(assets, list) and len(assets) >= 1:
                    return assets[:3]
            except Exception as e:
                print(f"[extract_core_assets_from_script] parse error: {e}")

    # 폴백: 대본 키워드 기반 스마트 추론
    text_lower = script_text.lower()
    if any(k in text_lower for k in ["미사일", "현무", "극초음속", "발사"]):
        return [
            {
                "asset_num": 1,
                "name": "대한민국 극초음속 미사일",
                "type": "핵심 주무기",
                "search_keyword": "현무 미사일 발사 실물",
                "search_keyword_en": "South Korean Hyunmoo missile launch photo",
            },
            {
                "asset_num": 2,
                "name": "적 지하 요새 벙커",
                "type": "핵심 표적/배경",
                "search_keyword": "군사 지하 요새 벙커",
                "search_keyword_en": "military underground fortified bunker",
            },
        ]
    elif any(k in text_lower for k in ["전투기", "kf-21", "보라매", "공군"]):
        return [
            {
                "asset_num": 1,
                "name": "대한민국 KF-21 보라매 전투기",
                "type": "핵심 항공기",
                "search_keyword": "KF-21 보라매 전투기 비행",
                "search_keyword_en": "KF-21 Boramae supersonic fighter jet",
            },
            {
                "asset_num": 2,
                "name": "공군 작전 지휘 통제소",
                "type": "핵심 작전 배경",
                "search_keyword": "공군 작전 통제실 레이더",
                "search_keyword_en": "air force command control radar center",
            },
        ]
    else:
        return [
            {
                "asset_num": 1,
                "name": "주요 핵심 피사체",
                "type": "핵심 대상",
                "search_keyword": script_text.split()[:2] and " ".join(script_text.split()[:2]) or "한국 국방 첨단 무기",
                "search_keyword_en": "modern military defense technology photo",
            },
            {
                "asset_num": 2,
                "name": "작전 현장 배경",
                "type": "핵심 배경",
                "search_keyword": "군사 지휘 통제소",
                "search_keyword_en": "military command operations center",
            },
        ]


def sanitize_flow_shot_prompt(visual_en: str, motion_en: str = "") -> dict:
    """
    플로우(Flow) 및 최신 이미지/비디오 모델에서 한글/영문 텍스트 아티팩트(화면 내 원치 않는 글자/자막 렌더링)를
    원천 차단하고 카메라 연출 및 품질 태그를 정밀 표준화하는 정제 함수.
    """
    v = (visual_en or "").strip()
    m = (motion_en or "").strip()

    # 1. 따옴표, 괄호 등 파서 충돌 가능 문자 정제 (쉼표로 분리)
    v = re.sub(r'["\'\(\)\[\]—–;\n\r]', ' ', v)
    m = re.sub(r'["\'\(\)\[\]—–;\n\r]', ' ', m)

    # 2. 한글 유출 방지 (영문 프롬프트 내 한글 문자 제거)
    v = re.sub(r'[\uac00-\ud7a3]+', ' ', v)
    m = re.sub(r'[\uac00-\ud7a3]+', ' ', m)

    # 3. 공백 및 쉼표 정규화
    v = re.sub(r'\s*,\s*', ', ', v)
    v = re.sub(r'\s+', ' ', v).strip(' ,')
    m = re.sub(r'\s+', ' ', m).strip(' ,')

    # 4. 글자 렌더링 절대 방지(no text) 및 필수 품질 태그 강제
    no_text_suffix = "no text, textless, clean composition, uncropped, 8k cinematic"
    if "no text" not in v.lower() and "textless" not in v.lower():
        v = f"{v}, {no_text_suffix}"
    elif "uncropped" not in v.lower():
        v = f"{v}, clean composition, uncropped"

    # 이중 쉼표 및 공백 최종 정리
    v = re.sub(r',\s*,+', ', ', v)
    v = re.sub(r'\s+', ' ', v).strip(' ,')

    return {
        "visual_prompt_en": v,
        "camera_motion_en": m,
        "combined_flow_prompt": f"{v} (Motion: {m})" if m else v,
    }


def build_flow_master_distribution_text(scenes: list, zero_pad: bool = True) -> str:
    """
    구글 플로우(Shorts Story Studio)의 상단 마스터 바
    [📑 전체 씬 프롬프트 일괄 분배] 버튼 전용 마스터 텍스트 빌더.
    - [Scene 01] ~ [Scene 08] (또는 [Scene 1]) 씬 구분자 준수
    - Shot 01, Shot 02, Shot 03 3컷 자동 분배
    - 불필요한 한글 대본 줄을 배제하여 플로우 파싱 오작동 및 글자 왜곡을 100% 방지
    """
    master_lines = []
    for sc in scenes:
        s_num = sc.get("scene_num", 1)
        tag = f"[Scene {s_num:02d}]" if zero_pad else f"[Scene {s_num}]"
        master_lines.append(tag)
        shots = sc.get("shots", [])
        for sh_i, sh in enumerate(shots, 1):
            sh_num_str = f"0{sh_i}" if sh_i < 10 else f"{sh_i}"
            v_en = sh.get("visual_prompt_en", "").strip()
            m_en = sh.get("camera_motion_en", "").strip()
            # 정제 적용
            sanitized = sanitize_flow_shot_prompt(v_en, m_en)
            v_clean = sanitized["visual_prompt_en"]
            m_clean = sanitized["camera_motion_en"]
            motion_part = f" (Motion: {m_clean})" if m_clean else ""
            master_lines.append(f"Shot {sh_num_str}: {v_clean}{motion_part}")
        master_lines.append("")  # 씬 사이 빈 줄 분리
    return "\n".join(master_lines).strip()


def build_flow_official_korean_distribution_text(scenes: list, include_title: bool = True) -> str:
    """
    플로우 [전체 씬 일괄 프롬프트 분해 & 배분] 모달 전용 100% 공식 권장 양식 빌더.
    
    [화면 속 입력 권장 양식 100% 완벽 일치]:
    [씬 1: 제목]
    컷 1: 영문 비주얼 프롬프트 (Motion: 카메라 모션)
    컷 2: 영문 비주얼 프롬프트 (Motion: 카메라 모션)
    컷 3: 영문 비주얼 프롬프트 (Motion: 카메라 모션)

    [씬 2: 제목]
    컷 1: ...
    컷 2: ...
    컷 3: ...
    """
    master_lines = []
    for sc in scenes:
        s_num = sc.get("scene_num", 1)
        narr = sc.get("narration", "").strip()
        clean_title = re.sub(r'[\r\n]+', ' ', narr).strip()
        clean_title = clean_title[:25] if clean_title else f"Scene {s_num}"

        if include_title:
            master_lines.append(f"[씬 {s_num}: {clean_title}]")
        else:
            master_lines.append(f"[씬 {s_num}]")

        shots = sc.get("shots", [])
        for sh_i, sh in enumerate(shots, 1):
            v_en = sh.get("visual_prompt_en", "").strip()
            m_en = sh.get("camera_motion_en", "").strip()
            sanitized = sanitize_flow_shot_prompt(v_en, m_en)
            v_clean = sanitized["visual_prompt_en"]
            m_clean = sanitized["camera_motion_en"]
            motion_part = f" (Motion: {m_clean})" if m_clean else ""
            full_p = f"{v_clean}{motion_part}".strip()
            master_lines.append(f"컷 {sh_i}: {full_p}")

        master_lines.append("")  # 씬 구분용 빈 줄
    return "\n".join(master_lines).strip()


def build_claude_smart_distribution_text(scenes: list, mode: str = "no_scene_tag") -> str:
    """
    클로드(Claude) 아티팩트 및 스마트 전체 씬 분배 웹 도구 전용 텍스트 빌더.
    
    [문제 해결]:
    클로드 분배 스크립트가 [Scene 2] 헤더 줄을 컷 01 프롬프트 자리에 넣어버려
    1컷이 밀리고 3컷이 밖으로 튕겨나가는 파서 버그를 100% 원천 차단합니다.
    
    modes:
    1) 'no_scene_tag' (기본 / 가장 강력 추천):
       [Scene X] 헤더 줄 없이, 각 씬당 정확히 3줄(Shot 01:, Shot 02:, Shot 03:)만 정렬.
       클로드 파서가 컷 01, 02, 03에 오차 없이 1:1로 정확하게 집어넣음.
    2) 'pure_prompts':
       'Shot 01:' 접두사까지 모두 제거한 순수 영문 프롬프트 본문만 24줄(씬당 3줄) 정렬.
    3) 'zero_padded':
       클로드 UI 표기 규격('씬 02')에 맞춘 [Scene 01], [Scene 02] 2자리 패딩 버전.
    """
    master_lines = []
    for sc in scenes:
        s_num = sc.get("scene_num", 1)
        if mode == "zero_padded":
            master_lines.append(f"[Scene {s_num:02d}]")

        shots = sc.get("shots", [])
        for sh_i, sh in enumerate(shots, 1):
            sh_num_str = f"0{sh_i}" if sh_i < 10 else f"{sh_i}"
            v_en = sh.get("visual_prompt_en", "").strip()
            m_en = sh.get("camera_motion_en", "").strip()
            sanitized = sanitize_flow_shot_prompt(v_en, m_en)
            v_clean = sanitized["visual_prompt_en"]
            m_clean = sanitized["camera_motion_en"]
            motion_part = f" (Motion: {m_clean})" if m_clean else ""
            full_p = f"{v_clean}{motion_part}".strip()

            if mode == "pure_prompts":
                master_lines.append(full_p)
            else:
                master_lines.append(f"Shot {sh_num_str}: {full_p}")

        master_lines.append("")  # 씬 구분용 빈 줄
    return "\n".join(master_lines).strip()


def convert_script_to_3multishot_prompts(script_text: str, gemini_api_key: str = "") -> dict:
    """
    사용자가 입력한 전체 대본(1~8씬)을 분석하여 Shorts Story Studio(Flow) 규격의
    [1씬당 3개 4초 독립 영상 (총 12초 미니 영화)] 시네마틱 프롬프트 세트를 생성합니다.
    Flow의 [자동 분배] 시스템에 1:1:1로 정확히 배분되어 각 4초 영상의 속도감과 텐션을 극대화합니다.
    - 샷 1: 0~4초 - 폭발적 훅 & 시선 강탈 (Ignition / Trigger / Sudden Impact)
    - 샷 2: 4~8초 - 최고 속도감 & 공기역학적 폭발 (Peak Mach Velocity / Sonic Boom Cone / FPV Chase)
    - 샷 3: 8~12초 - 클라이맥스 텐션 & 초근접 디테일 (Terminal Suspense / Seeker Lock / Plasma Glow)
    """
    scenes = split_script_into_scenes(script_text)

    scenes_input = []
    for idx, sc in enumerate(scenes, 1):
        scenes_input.append(f"[Scene {idx}]\n{sc}")
    scenes_text = "\n\n".join(scenes_input)

    if gemini_api_key:
        prompt = f"""당신은 헐리우드 최고 수준의 블록버스터 밀리터리/SF 비주얼 디렉터이자, Flow(Shorts Story Studio) AI 영상 프롬프트 최고 권위자입니다.
유튜브 쇼츠에서 시청자의 도파민을 폭발시키고 시선을 1초도 뗄 수 없게 만드는 "1씬당 3개 4초 독립 영상 (총 12초 미니 액션 영화)" 프롬프트를 설계해야 합니다.

Flow는 각 씬마다 [Shot 1], [Shot 2], [Shot 3]을 '4초짜리 독립된 고품질 비디오 클립 3개'로 각각 렌더링합니다.
대본은 간결한 1문장이지만, 당신은 이 1문장을 바탕으로 [12초짜리 시네마틱 3단 시각 액션 시나리오(기-승-전)]로 완벽하게 확장하여 프롬프트를 작성해야 합니다.

=== 8개 씬 대본 ===
{scenes_text}

=== 🎬 [4초 3단 시네마틱 액션 연출 공식 (12초 미니 영화)] ===
각 씬마다 대본 1줄을 다음 3개 4초 샷의 연속된 물리적 사건(Action Sequence)으로 확장하세요:

[Shot 1: 0~4초 - 폭발적 훅 & 시선 강탈 (Ignition / Trigger / Sudden Impact)]
- 목표: 쇼츠를 넘기지 못하게 첫 4초 만에 눈을 사로잡는 폭발적 비주얼. 정적인 모습 금지.
- 필수 물리 요소: 지면이나 발사대가 흔들리며 에너지가 뿜어져 나오는 순간, 지하 사일로 해치 오픈, 카운트다운 점화, 콘크리트 균열, 맹렬한 화염 폭풍, 극단적인 카메라 진동(Violent camera shake), 파편과 스파크.
- 카메라: 극적인 로우앵글 웜즈아이(Worm's-eye view), 고속 틸트업(Tilt-up) 또는 크레인 샷.

[Shot 2: 4~8초 - 초고속 속도감 & 공기역학적 폭발 (Peak Velocity & Breakout)]
- 목표: 4초 동안 도파민이 터지는 압도적인 스피드와 공기역학적 긴장감.
- 필수 물리 요소: 마하의 속도로 구름을 찢으며 비행, 마하 10 돌파 시 기체를 감싸는 원뿔형 소닉붐 증기 구름(Prandtl-Glauert singularity sonic boom vapor cone), 날개 끝에서 소용돌이치는 기류 리본(Vortex ribbons), 발아래 지형과 구름이 빛의 줄기로 빨려 들어가는 극한의 모션 블러(Extreme streak motion blur), 후폭풍에 흔들리는 카메라.
- 카메라: 고속 FPV 체이서 샷(Aggressive high-speed FPV chase tightly tracking missile tail), 다이내믹 뱅크 앤 롤(Bank and roll).

[Shot 3: 8~12초 - 클라이맥스 텐션 & 초근접 디테일 (Terminal Suspense & Climax)]
- 목표: 다음 씬으로 넘어갈 때까지 숨을 죽이게 만드는 극적인 긴장감과 디테일.
- 필수 물리 요소: 칠흑 같은 우주와 맞닿은 성층권, 대기 마찰열로 붉게 달아오른 탄두 표면, 광학 탐색기에 붉게 깜빡이는 타겟 락온(Blinking red target lock reticle in optical seeker), 플라즈마 후류(Plasma trail), 대기 열왜곡(Atmospheric heat shimmer), 강렬한 시네마틱 아나모픽 렌즈 플레어(Anamorphic horizontal lens flare), 다음 씬으로 이어지는 급강하 궤적.
- 카메라: 초근접 매크로 클로즈업(Extreme cinematic macro close-up), 시네마틱 360 오르빗(Orbit pan), 또는 가파른 탑다운 다이브(Steep dive).

=== 🚨 [절대 엄수: 국가 및 피사체 왜곡 방지 원칙] 🚨 ===
1. 절대 `Korean` 단독 표기 금지!
   - 대한민국 무기/인물은 반드시 `South Korean [기종명] (ROK Armed Forces, modern high-tech matte grey finish, definitely not North Korean or Soviet style)`로 명시.
   - 적 대상은 `Hostile Enemy [기종명] (fortified mountain bunker / military installation)`으로 명확히 분리.
2. 화면 내 글자/자막(Text Artifact) 렌더링 100% 원천 차단 (No-Text Rule):
   - AI 이미지/비디오 생성 시 화면에 영어나 한글 글자(워터마크, 자막, 간판, 로고)가 절대 박히지 않도록, 모든 visual_prompt_en의 맨 끝에는 반드시 ", no text, textless, clean composition, uncropped, 8k cinematic"를 포함하세요.
   - visual_prompt_en에 따옴표(""), 한글 대본, 'letters', 'words', 'logo', 'subtitle' 등의 글자 유발 단어를 절대 포함하지 마세요.
3. 영문 프롬프트 품질 극대화:
   - visual_prompt_en과 camera_motion_en은 전문 영화/CGI 촬영 감독 용어(8k resolution, cinematic lighting, photorealistic, Unreal Engine 5 render style, high dynamic range)를 포함하여 밀도 높고 역동적으로 작성.
   - 화면에 불필요한 글자가 생성되지 않도록 순수 시각/동작 묘사에 집중.

반드시 아래 JSON 포맷으로만 응답하세요:
{{
  "scenes": [
    {{
      "scene_num": 1,
      "narration": "씬 1 나레이션 대사",
      "visual_storyline_ko": "1컷 발사대 지면 파열과 부스터 점화 ➡️ 2컷 마하 10 소닉붐과 FPV 광속 추적 ➡️ 3컷 성층권 돌입 및 탄두 락온 텐션",
      "shots": [
        {{
          "shot_num": 1,
          "title": "01 Ground-Shaking Booster Ignition",
          "visual_prompt_en": "Extreme dramatic low-angle worm's-eye shot, South Korean Hyunmoo missile (ROK Armed Forces, sleek modern matte grey finish) rocket booster violently detonating, massive billowing orange fiery shockwave blasting across launchpad, launch facility concrete cracking, lens splattered with sparks, violent camera shake, photorealistic 8k, cinematic dramatic chiaroscuro lighting",
          "camera_motion_en": "Fast dramatic upward crane tracking following the violent vertical launch acceleration",
          "korean_desc": "발사대 콘크리트를 가르며 화염 충격파와 함께 수직으로 솟구치는 한국군 미사일"
        }},
        {{
          "shot_num": 2,
          "title": "02 Mach 10 FPV Supersonic Breakout",
          "visual_prompt_en": "Aggressive high-speed FPV chase shot tightly following South Korean hypersonic glide vehicle at Mach 10, conical Prandtl-Glauert sonic boom vapor cloud instantly enveloping the body, terrain and parted storm clouds rushing backward into light streaks, extreme streak motion blur, wake turbulence lens vibration, cinematic 8k",
          "camera_motion_en": "High-velocity aggressive FPV chase with dynamic banking roll and motion blur",
          "korean_desc": "마하 10 소닉붐 구름을 찢으며 구름 바다 위를 질주하는 광속 FPV 추적"
        }},
        {{
          "shot_num": 3,
          "title": "03 Stratospheric Seeker Lock Climax",
          "visual_prompt_en": "Cinematic macro close-up of glowing aerodynamic titanium nosecone slicing through upper stratosphere, atmospheric heat shimmer and plasma trail, optical seeker lens reflecting red blinking target coordinates, anamorphic horizontal cyan lens flare, impending terminal dive angle, 8k photorealistic",
          "camera_motion_en": "Dramatic slow-motion 360 orbit pan around glowing nosecone transitioning to steep terminal dive",
          "korean_desc": "성층권을 가르는 붉게 달아오른 탄두와 타깃 락온 렌즈의 숨 막히는 긴장감"
        }}
      ]
    }}
    // 총 8개 씬 (scene_num 1부터 8까지)
  ]
}}"""
        raw_res = _call_gemini_api(prompt, gemini_api_key, json_mode=True)
        if raw_res:
            try:
                m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", raw_res, re.DOTALL)
                json_str = m.group(1) if m else raw_res
                data = json.loads(json_str)
                if "scenes" in data and len(data["scenes"]) >= 8:
                    for sc in data["scenes"]:
                        for sh in sc.get("shots", []):
                            v_raw = sh.get("visual_prompt_en", "")
                            m_raw = sh.get("camera_motion_en", "")
                            sani = sanitize_flow_shot_prompt(v_raw, m_raw)
                            sh["visual_prompt_en"] = sani["visual_prompt_en"]
                            sh["camera_motion_en"] = sani["camera_motion_en"]

                    master_flow_text = build_flow_master_distribution_text(data["scenes"])
                    data["flow_master_distribution_text"] = master_flow_text
                    data["studio_copy_text"] = master_flow_text
                    return data
            except Exception as e:
                print(f"[convert_script_to_3multishot_prompts] parse error: {e}")

    # 폴백: SHOT_PRESETS_24를 활용한 100% 안전한 3멀티샷 빌더
    fallback_scenes = []
    for s_idx, sc_text in enumerate(scenes, 1):
        shots = []
        storyline = f"1컷 시선 강탈 발사 훅 ➡️ 2컷 마하 초고속 질주 ➡️ 3컷 클라이맥스 텐션 디테일"

        for sh_idx in range(1, 4):
            idx = (s_idx - 1) * 3 + (sh_idx - 1)
            preset = SHOT_PRESETS_24[idx] if idx < len(SHOT_PRESETS_24) else SHOT_PRESETS_24[0]
            sh_title = f"0{sh_idx} {preset.get('keywords', 'Cinematic Shot').split(',')[0].strip()}"
            v_en = preset.get("image_en", "")
            m_en = preset.get("motion_en", "")
            k_desc = preset.get("image_ko", "")

            # 국가명 명확화 강화
            if "missile" in v_en.lower() and "south korean" not in v_en.lower():
                v_en = "South Korean military defense (ROK Armed Forces, sleek modern matte grey finish), " + v_en

            # 4초 다이나믹 트리거 추가
            if sh_idx == 1:
                v_en += ", violent camera shake, explosive booster shockwave"
                m_en += " with sudden explosive acceleration"
            elif sh_idx == 2:
                v_en += ", Mach 10 sonic boom vapor cone, extreme streak motion blur, high-speed FPV tracking"
                m_en += " with aggressive FPV chase and bank roll"
            elif sh_idx == 3:
                v_en += ", extreme macro cinematic close-up, glowing thermal nosecone, anamorphic lens flare"
                m_en += " with dramatic slow-motion orbit tension"

            # 플로우 글자 방지 및 품질 정제 적용
            sani = sanitize_flow_shot_prompt(v_en, m_en)

            shots.append({
                "shot_num": sh_idx,
                "title": sh_title,
                "visual_prompt_en": sani["visual_prompt_en"],
                "camera_motion_en": sani["camera_motion_en"],
                "korean_desc": k_desc,
            })

        fallback_scenes.append({
            "scene_num": s_idx,
            "narration": sc_text,
            "visual_storyline_ko": storyline,
            "shots": shots,
        })

    fallback_master_text = build_flow_master_distribution_text(fallback_scenes)
    return {
        "scenes": fallback_scenes,
        "flow_master_distribution_text": fallback_master_text,
        "studio_copy_text": fallback_master_text,
    }


# ════════════════════════════════════════════════════════════
# ⚔️ 유튜브 쇼츠(9:16) 스펙 비교(VS) 콘텐츠 전용 프롬프트 생성 엔진
# ════════════════════════════════════════════════════════════

def get_vs_default_presets() -> dict:
    """비교 쇼츠 제작용 4대 인기 밀리터리/테크 프리셋을 반환합니다."""
    return {
        "kf21_vs_f16": {
            "title": "✈️ [전투기] KF-21 보라매 vs F-16V 파이팅 팰컨",
            "subject_a_ko": "KF-21 보라매",
            "subject_a_en": "KF-21 Boramae 4.5th-generation supersonic multirole fighter (South Korean Air Force low-visibility matte stealth grey finish)",
            "subject_b_ko": "F-16V 파이팅 팰컨",
            "subject_b_en": "F-16V Fighting Falcon Block 70/72 multirole fighter (USAF air-superiority grey livery)",
            "topic": "체급 및 쌍발 vs 단발 엔진 추력 비교 (Twin-engine vs Single-engine Thrust & Body Size)",
            "motion_a_ko": "쌍발 엔진 노즐 수축 및 파란색 애프터버너 점화",
            "motion_a_en": "Twin turbofan engine nozzles contracting and igniting explosive dual blue afterburner flames with intense supersonic shock rings and thermal shimmer",
            "motion_b_ko": "단발 엔진 노즐 개방 및 주황색 화염 분사",
            "motion_b_en": "Single engine variable exhaust nozzle wide opening and venting roaring supersonic orange shock diamonds and combustion blast",
            "spec_label_a": "LENGTH 16.9m | TWIN THRUST 44,000 lbf",
            "spec_label_b": "LENGTH 15.0m | SINGLE THRUST 29,500 lbf",
            "layout": "stacked",
            "sfx_theme": "jet",
        },
        "k2_vs_t90m": {
            "title": "🛡️ [전차] K2 흑표 vs T-90M 프릴리브",
            "subject_a_ko": "K2 흑표",
            "subject_a_en": "K2 Black Panther main battle tank (Korean Army digital forest camouflage, auto-loader 120mm/L55 smoothbore gun)",
            "subject_a_ko": "K2 흑표",
            "subject_b_ko": "T-90M 프릴리브",
            "subject_b_en": "T-90M Proryv-3 main battle tank (Relikt explosive reactive armor, slat cage armor, 125mm 2A46M-5 gun)",
            "topic": "포탑 반응장갑 및 유기압 현수장치 무릎꿇기 기동 비교 (Hydropneumatic Suspension vs Heavy ERA Armor)",
            "motion_a_ko": "유기압 현수장치 전방 무릎꿇기 자세 제어 및 주포 수평 조준",
            "motion_a_en": "In-arm hydropneumatic suspension dynamically kneeling forward and leveling gun barrel with sharp hydraulic pressure release hiss",
            "motion_b_ko": "중장갑 포탑 고속 45도 회전 및 디젤 배기가스 분출",
            "motion_b_en": "Heavy armored turret rapidly traversing 45 degrees towards viewer with mechanical gears whining and black diesel exhaust puffing",
            "spec_label_a": "WEIGHT 55.0t | POWER 1,500 hp (27.3 hp/t)",
            "spec_label_b": "WEIGHT 48.0t | POWER 1,130 hp (23.5 hp/t)",
            "layout": "stacked",
            "sfx_theme": "tank",
        },
        "dosan_vs_virginia": {
            "title": "🚢 [잠수함] 도산안창호함 vs 버지니아급 공격원잠",
            "subject_a_ko": "도산안창호함",
            "subject_a_en": "Dosan Ahn Changho-class KSS-III ballistic missile submarine (AIP fuel cell stealth hull, 6 VLS cells)",
            "subject_b_ko": "버지니아급",
            "subject_b_en": "Virginia-class Block V nuclear attack submarine (VPM missile payload module, pump-jet propulsor)",
            "topic": "디젤-AIP VLS 잠수함 vs 원자력 공격잠수함 배수량 및 발사관 체급 비교",
            "motion_a_ko": "수직발사관(VLS) 해치 순차 개방 및 기압 배출",
            "motion_a_en": "Vertical Launch System (VLS) top hatches smoothly sliding open with mechanical pneumatic release",
            "motion_b_ko": "펌프젯 추진기 고속 회전 및 수중 캐비테이션 와류 발생",
            "motion_b_en": "Acoustic pump-jet propulsor spinning rapidly with high-speed hydrodynamic cavitation wake",
            "spec_label_a": "DISPLACEMENT 3,750t | 6x VLS SLBM",
            "spec_label_b": "DISPLACEMENT 10,200t | 40x TOMAHAWK VLS",
            "layout": "stacked",
            "sfx_theme": "naval",
        },
        "hyunmoo5_vs_topolm": {
            "title": "🚀 [미사일] 현무-5 괴물미사일 vs 토폴-M ICBM",
            "subject_a_ko": "현무-5 괴물미사일",
            "subject_a_en": "Hyunmoo-5 heavy ballistic missile (monster bunker buster, 9-axle TEL transporter erector launcher)",
            "subject_b_ko": "토폴-M ICBM",
            "subject_b_en": "RT-2PM2 Topol-M road-mobile ICBM (massive 8-axle MZKT-79221 transporter erector launcher)",
            "topic": "탄두 중량 및 TEL 발사관 수직 기립 메커니즘 비교",
            "motion_a_ko": "대구경 콜드런치 발사관 90도 수직 기립 및 고압가스 밸브 분출",
            "motion_a_en": "Heavy cold-launch cylindrical canister elevating hydraulically to 90 degrees vertical with high-pressure gas valve venting",
            "motion_b_ko": "후방 유압 지지대 지면 고정 및 상부 발사관 덮개 분리",
            "motion_b_en": "Rear stabilizer hydraulic jacks anchoring deep into ground and canister nose protective shroud splitting open",
            "spec_label_a": "WARHEAD 8.0t | WEIGHT 36t (BUNKER BUSTER)",
            "spec_label_b": "WARHEAD 1.2t | WEIGHT 47t (NUCLEAR ICBM)",
            "layout": "stacked",
            "sfx_theme": "missile",
        },
    }


def autofill_vs_details_with_gemini(
    subject_a: str,
    subject_b: str,
    topic: str,
    gemini_api_key: str = "",
) -> dict:
    """사용자가 입력한 A, B, 비교 주제를 기반으로 Gemini API를 호출하여 영문 명칭, 물리 모션, 핵심 스펙 라벨을 자동 추론 및 생성합니다."""
    # API 키가 없거나 공백인 경우 폴백 생성
    if not gemini_api_key:
        return _fallback_autofill_vs_details(subject_a, subject_b, topic)

    prompt = f"""당신은 세계 최고의 유튜브 쇼츠(9:16) 공학/밀리터리 비교(VS) 비주얼 디렉터입니다.
두 비교 대상(A vs B)과 핵심 비교 주제를 분석하여, AI 영상 제작(Google Flow, Veo, Midjourney)에 최적화된 물리 모션과 스펙 라벨을 영문과 한글로 정확하게 생성하세요.

[입력 정보]
- 비교 대상 A: {subject_a}
- 비교 대상 B: {subject_b}
- 핵심 비교 주제: {topic}

[작성 및 추론 규칙]
1. `subject_a_en`, `subject_b_en`: 각 피사체의 공식 영문 명칭, 세부 파생형(Block 등), 상징적인 도색/재질(matte stealth grey finish, digital camo 등)을 덧붙인 정밀 명칭.
2. `motion_a_ko`, `motion_a_en`: 대상 A가 화면에서 1.5초~3.0초 사이에 실제로 취할 수 있는 기계적/물리적 작동 모션 (예: 노즐 수축 및 애프터버너 점화, 포탑 회전, VLS 개방, 가변익 전개 등). 영문은 시각적 디테일(불꽃 색상, 수증기, 유압 작동 등)을 15~25단어로 상세 서술.
3. `motion_b_ko`, `motion_b_en`: 대상 B가 대상 A와 동시에 취할 독자적인 물리 모션.
4. `spec_label_a`, `spec_label_b`: 시청자가 0.5초 만에 직관적으로 체감할 수 있는 1줄짜리 핵심 정량적 수치 스펙 (예: 'LENGTH 16.9m | TWIN THRUST 44,000 lbf', 영문 대문자 규격 권장).
5. `sfx_theme`: 오디오 효과음 테마 ('jet', 'tank', 'missile', 'naval', 'general' 중 1개 택일).

반드시 다음 JSON 형식으로만 응답하세요:
{{
  "subject_a_en": "정밀 영문 명칭 A",
  "subject_b_en": "정밀 영문 명칭 B",
  "motion_a_ko": "한글 물리 모션 A",
  "motion_a_en": "Detailed English physical motion description for A",
  "motion_b_ko": "한글 물리 모션 B",
  "motion_b_en": "Detailed English physical motion description for B",
  "spec_label_a": "UPPERCASE SPEC A (예: LENGTH 16.9m | 44,000 lbf)",
  "spec_label_b": "UPPERCASE SPEC B (예: LENGTH 15.0m | 29,500 lbf)",
  "sfx_theme": "jet"
}}
"""
    raw_res = _call_gemini_api(prompt, gemini_api_key, json_mode=True)
    if not raw_res:
        return _fallback_autofill_vs_details(subject_a, subject_b, topic)

    try:
        clean_json = re.sub(r"^```(?:json)?\s*", "", raw_res.strip(), flags=re.MULTILINE)
        clean_json = re.sub(r"\s*```$", "", clean_json.strip())
        data = json.loads(clean_json)
        return {
            "subject_a_en": data.get("subject_a_en") or subject_a,
            "subject_b_en": data.get("subject_b_en") or subject_b,
            "motion_a_ko": data.get("motion_a_ko") or "동적 메커니즘 구동",
            "motion_a_en": data.get("motion_a_en") or "Active mechanical propulsion and dynamic physical actuation",
            "motion_b_ko": data.get("motion_b_ko") or "동시 물리 반응 작동",
            "motion_b_en": data.get("motion_b_en") or "Simultaneous mechanical physical actuation and reactive exhaust vent",
            "spec_label_a": data.get("spec_label_a") or "SPEC A: HIGH PERFORMANCE",
            "spec_label_b": data.get("spec_label_b") or "SPEC B: HIGH PERFORMANCE",
            "sfx_theme": data.get("sfx_theme") or "general",
        }
    except Exception as e:
        print(f"[autofill_vs_details_with_gemini] JSON parsing error: {e}")
        return _fallback_autofill_vs_details(subject_a, subject_b, topic)


def _fallback_autofill_vs_details(subject_a: str, subject_b: str, topic: str) -> dict:
    """API 키가 없거나 실패 시 기본 규칙 기반으로 안전하게 채워주는 폴백 함수."""
    sa = subject_a.strip() or "Subject Alpha"
    sb = subject_b.strip() or "Subject Beta"
    top = topic.strip() or "Performance and Physical Specification"

    # 키워드 기반 SFX 테마 추론
    combined = f"{sa} {sb} {top}".lower()
    if any(k in combined for k in ["전투기", "항공기", "fighter", "jet", "f-", "kf-", "su-", "비행기", "엔진"]):
        sfx_theme = "jet"
        m_a_ko = "쌍발 엔진 노즐 수축 및 애프터버너 점화"
        m_a_en = "Engine exhaust nozzles contracting and igniting explosive dual blue afterburner flames with supersonic shock diamonds"
        m_b_ko = "가변 노즐 개방 및 고압 분사 기동"
        m_b_en = "Variable exhaust nozzle opening wide and venting roaring orange combustion plume with thermal distortion"
        sp_a = "PRIMARY SPEC A | MAX THRUST & SPEED"
        sp_b = "PRIMARY SPEC B | HIGH AGILITY & PAYLOAD"
    elif any(k in combined for k in ["전차", "탱크", "tank", "k2", "장갑차", "자주포"]):
        sfx_theme = "tank"
        m_a_ko = "현수장치 자세 제어 및 주포 수평 조준"
        m_a_en = "Hydropneumatic suspension dynamically adjusting chassis posture and leveling gun barrel with hydraulic hiss"
        m_b_ko = "중장갑 포탑 고속 회전 및 배기가스 분출"
        m_b_en = "Heavy armored turret smoothly traversing with mechanical whir and diesel exhaust venting"
        sp_a = "WEIGHT 55t | 1,500 HP ENGINE"
        sp_b = "WEIGHT 48t | 1,130 HP ENGINE"
    elif any(k in combined for k in ["미사일", "로켓", "missile", "rocket", "현무", "탄도"]):
        sfx_theme = "missile"
        m_a_ko = "발사관 90도 수직 기립 및 고압가스 배출"
        m_a_en = "Heavy launch canister hydraulically elevating to 90 degrees vertical with pneumatic release"
        m_b_ko = "발사대 고정 지지대 전개 및 보호 커버 분리"
        m_b_en = "Heavy hydraulic stabilizer outriggers anchoring and protective cap jettisoning"
        sp_a = "PAYLOAD 8.0t | RANGE 800km"
        sp_b = "PAYLOAD 1.2t | RANGE 11,000km"
    elif any(k in combined for k in ["잠수함", "함정", "submarine", "ship", "원잠"]):
        sfx_theme = "naval"
        m_a_ko = "수직발사관(VLS) 해치 순차 개방"
        m_a_en = "Vertical launch system top hatches sliding open smoothly in sequence"
        m_b_ko = "추진 프로펠러 고속 회전 및 와류 발생"
        m_b_en = "Propulsion drive spinning rapidly creating hydrodynamic cavitation wake"
        sp_a = "DISPLACEMENT 3,750t | 6x VLS"
        sp_b = "DISPLACEMENT 10,200t | 40x VLS"
    else:
        sfx_theme = "general"
        m_a_ko = "핵심 구동 메커니즘 전개 및 출력 가동"
        m_a_en = "Primary mechanical actuation unfolding with dynamic mechanical movement and energy output"
        m_b_ko = "동시 대칭 메커니즘 반응 구동"
        m_b_en = "Secondary mechanical component actively engaging with simultaneous counter-action"
        sp_a = "METRIC A: ADVANCED CONFIGURATION"
        sp_b = "METRIC B: COMPACT CONFIGURATION"

    return {
        "subject_a_en": sa,
        "subject_b_en": sb,
        "motion_a_ko": m_a_ko,
        "motion_a_en": m_a_en,
        "motion_b_ko": m_b_ko,
        "motion_b_en": m_b_en,
        "spec_label_a": sp_a,
        "spec_label_b": sp_b,
        "sfx_theme": sfx_theme,
    }


def build_vs_clean_prompt(data: dict) -> str:
    """[고정 규칙 1 & 2]: 9:16 vertical 대칭 스케일 정렬 + 순수 무배경 화이트 사이클로라마 스튜디오 CLEAN 이미지 프롬프트 생성"""
    sa_en = data.get("subject_a_en") or data.get("subject_a") or "Subject A"
    sb_en = data.get("subject_b_en") or data.get("subject_b") or "Subject B"
    layout = data.get("layout", "stacked")

    if layout == "split":
        layout_desc = (
            f"Left-right split horizontal comparison composition. "
            f"On the LEFT side: {sa_en}. On the RIGHT side: {sb_en}. "
        )
    else:  # stacked (상/하 수직 배치 기본값 - 쇼츠 9:16 최적)
        layout_desc = (
            f"Top-bottom stacked vertical comparison composition. "
            f"In the UPPER half: {sa_en}. In the LOWER half: {sb_en}. "
        )

    clean_prompt = (
        f"Cinematic 9:16 vertical engineering comparison showcase. {layout_desc}"
        f"Both subjects are strictly rendered to accurate 1:1 true physical scale proportions, perfectly level, "
        f"facing slightly three-quarters toward camera in pristine ready state. "
        f"Isolated on a pure seamless white studio cyclorama background, soft natural contact shadows beneath each subject on the clean floor, "
        f"crisp studio rim lighting defining metallic contours and engineering silhouettes, ultra-sharp focus, photorealistic 8k render, uncropped composition, clean frame.\n\n"
        f"--no background elements, sky, clouds, horizon, ground texture, grass, mountains, landscape, outdoors, clutter, text, letters, numbers, typography, watermark, logo, labels, HUD, arrows"
    )
    return clean_prompt.strip()


def build_vs_info_prompt(clean_prompt: str, data: dict) -> str:
    """[고정 규칙 1 & 2 확장]: Step 1의 구도와 조명을 100% 보존한 상태에서 스펙 라벨 A/B와 중앙 'VS' 구분선 HUD가 결합된 INFO 이미지 프롬프트"""
    sa_en = data.get("subject_a_en") or data.get("subject_a") or "Subject A"
    sb_en = data.get("subject_b_en") or data.get("subject_b") or "Subject B"
    spec_a = data.get("spec_label_a") or "SPEC A: PERFORMANCE DATA"
    spec_b = data.get("spec_label_b") or "SPEC B: PERFORMANCE DATA"
    layout = data.get("layout", "stacked")

    if layout == "split":
        pos_desc = (
            f"- Divider: In the exact vertical center between them, a bold modern metallic 'VS' emblem divider line.\n"
            f"- Left HUD: Beside {sa_en}, a crisp minimalist holographic engineering callout box with sharp text '{spec_a}'.\n"
            f"- Right HUD: Beside {sb_en}, a crisp minimalist holographic engineering callout box with sharp text '{spec_b}'."
        )
    else:
        pos_desc = (
            f"- Divider: In the exact horizontal center dividing the upper and lower halves, a bold modern metallic 'VS' emblem graphic line.\n"
            f"- Upper HUD: Directly beside or below {sa_en}, a crisp minimalist engineering holographic callout box with clear text '{spec_a}'.\n"
            f"- Lower HUD: Directly beside or below {sb_en}, a crisp minimalist engineering holographic callout box with clear text '{spec_b}'."
        )

    info_prompt = (
        f"Exact identical camera angle, framing, scale, and lighting from Reference 1 (Step 1 CLEAN Start Frame) on a pure seamless white studio cyclorama background.\n"
        f"The identical {sa_en} and {sb_en} remain in the exact same positions, with precise 3D infographic specification overlays seamlessly integrated in space:\n"
        f"{pos_desc}\n"
        f"Minimalist engineering infographic styling, sharp clean typography, luminous cyan and amber technical telemetry accents, zero clutter, 8k resolution, uncropped."
    )
    return info_prompt.strip()


def build_vs_flow_video_prompt(data: dict) -> str:
    """[고정 규칙 3 & 4]: 1.5~3.0초 듀얼 동시 물리 모션 + 3.0~4.0초 스펙 라벨/VS 락인 + 네이티브 오디오(SFX) 포함 Google Flow(Veo) 전환 영상 프롬프트"""
    sa_en = data.get("subject_a_en") or data.get("subject_a") or "Subject A"
    sb_en = data.get("subject_b_en") or data.get("subject_b") or "Subject B"
    motion_a = data.get("motion_a_en") or "Active mechanical actuation"
    motion_b = data.get("motion_b_en") or "Simultaneous dynamic physical motion"
    spec_a = data.get("spec_label_a") or "SPEC A"
    spec_b = data.get("spec_label_b") or "SPEC B"
    sfx_theme = data.get("sfx_theme", "general")

    # 오디오 디자인 테마별 사운드 지시어
    if sfx_theme == "jet":
        sfx_0_15 = "Heavy low-frequency turbine idle hum, mechanical gyro whine, atmospheric studio drone."
        sfx_15_30 = "Sudden thunderous dual jet engine roar, afterburner ignition blast, explosive supersonic shockwave boom."
        sfx_30_40 = "Crisp digital tactical HUD lock-in ping (sharp double beep), metallic latch click, settling hum."
    elif sfx_theme == "tank":
        sfx_0_15 = "Deep idling heavy diesel engine vibration, pneumatic suspension pressurized hiss."
        sfx_15_30 = "High-pressure hydraulic suspension hiss, aggressive mechanical turret gear whine, heavy metal clanking."
        sfx_30_40 = "Sharp tactical targeting computer lock beep, heavy steel breach lock click."
    elif sfx_theme == "missile":
        sfx_0_15 = "Low mechanical hum, electronic countdown telemetry pinging."
        sfx_15_30 = "Massive hydraulic erection motor whine, explosive pneumatic cold-launch valve venting roar."
        sfx_30_40 = "Solid steel outrigger ground impact thud, electronic guidance lock confirmation tone."
    elif sfx_theme == "naval":
        sfx_0_15 = "Low ambient submarine sonar pulse, quiet electric motor whine."
        sfx_15_30 = "Heavy pneumatic VLS hatch sliding hiss, deep rushing cavitation water vortex wash."
        sfx_30_40 = "High-tech fire-control lock-in chirp, positive seal lock click."
    else:
        sfx_0_15 = "Subtle low mechanical ambient hum, clean studio idling tone."
        sfx_15_30 = "Simultaneous high-torque servo motor whining, sharp mechanical actuation sound, energetic mechanical burst."
        sfx_30_40 = "Crisp high-frequency UI confirmation chime, solid metallic mechanical lock-in click."

    video_prompt = (
        f"[0.0s-1.5s]: The scene opens exactly from Reference 1 (CLEAN Start Frame) on a pure seamless white studio cyclorama background. "
        f"Both {sa_en} and {sb_en} remain locked in symmetrical comparison alignment with subtle mechanical idling vibrations and micro-breathing motion. Camera locked off, vertical 9:16.\n\n"
        f"[1.5s-3.0s]: Simultaneous dual physical action erupts dynamically. "
        f"{sa_en} actively performs: {motion_a}. "
        f"At the exact same instant, {sb_en} actively performs: {motion_b}. "
        f"Dynamic mechanical action, exhaust, and particle effects stay tightly contained on the subjects without dirtying the pure white cyclorama background.\n\n"
        f"[3.0s-4.0s]: The dynamic movements settle smoothly and match Reference 2 (INFO End Frame) with absolute precision. "
        f"A prominent center 'VS' divider graphic and crisp engineering specification text labels ('{spec_a}' and '{spec_b}') lock firmly into place in 3D space with zero jitter, remaining completely static, razor-sharp, and readable until the end of the video.\n\n"
        f"Pure seamless white studio cyclorama background throughout, crisp studio rim lighting, 9:16 vertical ratio.\n\n"
        f"Audio / Sound Design (Native Audio):\n"
        f"- 0.0s-1.5s: {sfx_0_15}\n"
        f"- 1.5s-3.0s: {sfx_15_30}\n"
        f"- 3.0s-4.0s: {sfx_30_40}"
    )
    return video_prompt.strip()


def generate_vs_prompt_pipeline(data: dict) -> dict:
    """비교 대상 A/B 및 6개 핵심 변수를 전달받아 Step 1 CLEAN, Step 2 INFO, Step 3 Google Flow 전환 영상 프롬프트를 일괄 생성합니다."""
    step1_clean = build_vs_clean_prompt(data)
    step2_info = build_vs_info_prompt(step1_clean, data)
    step3_flow = build_vs_flow_video_prompt(data)

    sa_ko = data.get("subject_a_ko") or data.get("subject_a") or "대상 A"
    sb_ko = data.get("subject_b_ko") or data.get("subject_b") or "대상 B"
    topic = data.get("topic") or "스펙 비교"

    # 3단계 전체 일괄 복사용 마스터 텍스트
    master_copy_text = f"""================================================================================
⚔️ [유튜브 쇼츠 9:16 스펙 비교 VS 전용 프롬프트 패키지]
📌 비교 주제: {sa_ko} vs {sb_ko} ({topic})
================================================================================

[Step 1: CLEAN 이미지 (Start Frame)]
--------------------------------------------------------------------------------
{step1_clean}

[Step 2: INFO 이미지 (End Frame)]
--------------------------------------------------------------------------------
{step2_info}

[Step 3: Google Flow 전환 영상 (1.5-3.0s 동시 모션 & 3.0s HUD 락 & 네이티브 오디오)]
--------------------------------------------------------------------------------
{step3_flow}
================================================================================
"""

    return {
        "step1_clean": step1_clean,
        "step2_info": step2_info,
        "step3_flow": step3_flow,
        "master_copy_text": master_copy_text.strip(),
    }


# ════════════════════════════════════════════════════════════
# 🚀 [유튜브 쇼츠 업로드 풀패키지] 자동 생성 엔진 (한·영 동시 생성)
# ════════════════════════════════════════════════════════════
def _fallback_shorts_upload_package(topic: str, script: str) -> dict:
    """Gemini API 오프라인 또는 키 부재 시 대본 기반으로 즉시 완성하는 고품질 업로드 패키지 폴백"""
    t_clean = topic.strip() or "유튜브 쇼츠"
    first_line = ""
    for line in script.splitlines():
        line_s = line.strip()
        if line_s and not line_s.startswith(("[Scene", "[씬", "#", "Scene", "씬")):
            first_line = line_s[:50]
            break
    if not first_line:
        first_line = f"{t_clean}의 충격적인 진실"

    ko_titles = [
        f"외형은 똑같은데 '이것'이 없다? {t_clean}의 소름 돋는 비밀 #쇼츠",
        f"실제 마주치면 0초 컷 당하는 이유! {t_clean} 핵심 총정리 #Shorts",
        f"1분 만에 끝내는 {t_clean} 핵심 스펙과 작동 원리 #쇼츠",
    ]
    en_titles = [
        f"They Look The Same, But THIS Is Missing? {t_clean} #Shorts",
        f"Why It Decides Everything in 0 Seconds: {t_clean} #Shorts",
        f"The Brutal Truth About {t_clean} (Full Specs Explained) #Shorts",
    ]

    ko_desc = f"""📌 {t_clean} 핵심 포인트 1분 요약

{first_line}

[📌 영상 속 핵심 팩트체크]
• 대상/주제: {t_clean}
• 핵심 특징: 정밀 메커니즘 및 실제 작동 원리
• 시청 포인트: 실전 상황에서의 결정적 성능 차이

영상 시청해 주셔서 감사합니다! 유익하셨다면 구독과 좋아요 부탁드립니다!

#밀리터리 #K방산 #{t_clean.replace(' ', '')} #쇼츠 #Shorts #과학상식 #스펙비교"""

    en_desc = f"""📌 Quick 1-Minute Summary of {t_clean}

{first_line}

[📌 Key Fact-Check Summary]
• Subject: {t_clean}
• Key Capability: Advanced physical mechanism & specs
• Verdict: Critical operational performance breakdown

Thanks for watching! Don't forget to like and subscribe!

#Military #DefenseTech #{t_clean.replace(' ', '')} #Shorts #FactCheck #TechSpecs"""

    ko_hashtags = f"#밀리터리 #K방산 #{t_clean.replace(' ', '')} #쇼츠 #Shorts #무기백과 #방산기술"
    en_hashtags = f"#Military #DefenseTech #{t_clean.replace(' ', '')} #Shorts #TechSpecs #FactCheck"

    ko_tags_csv = f"{t_clean}, 밀리터리, 쇼츠, 유튜브 쇼츠, 방산기술, 무기체계, K방산, 팩트체크, 무기비교, 신무기, 최신기술, 국방, 밀리터리 쇼츠, Shorts"
    en_tags_csv = f"{t_clean}, Military, Shorts, YouTube Shorts, Defense Tech, Weapon Specs, Fact Check, Military Breakdown, Tech Review, Modern Defense"

    ko_pinned = f"""👇 여러분이 보시기에 이 기술에서 가장 중요한 핵심은 무엇인가요? 자유롭게 의견을 남겨주세요!

[📌 영상 속 팩트체크 요약]
1. 주제: {t_clean}
2. 핵심 메커니즘: 영상에서 다룬 고증 데이터 및 물리적 작동 원리 기반
3. 실전 의의: 기존 체계 대비 독보적 우위 및 실제 운용 가치 입증"""

    en_pinned = f"""👇 What do you think is the most decisive factor here? Share your thoughts below!

[📌 Key Fact-Check Summary]
1. Topic: {t_clean}
2. Key Mechanism: Based on verified operational and physical data
3. Tactical Impact: Proven superiority in real-world deployment"""

    ko_fact = f"""1. 주제: {t_clean}\n2. 핵심 메커니즘: 영상에서 다룬 고증 데이터 및 물리적 작동 원리 기반\n3. 실전 의의: 기존 체계 대비 독보적 우위 및 실제 운용 가치 입증"""
    en_fact = f"""1. Topic: {t_clean}\n2. Key Mechanism: Based on verified operational and physical data\n3. Tactical Impact: Proven superiority in real-world deployment"""

    return {
        "titles": ko_titles,
        "titles_en": en_titles,
        "description": ko_desc,
        "description_en": en_desc,
        "hashtags": ko_hashtags,
        "hashtags_en": en_hashtags,
        "tags_csv": ko_tags_csv,
        "tags_csv_en": en_tags_csv,
        "pinned_comment": ko_pinned,
        "pinned_comment_en": en_pinned,
        "fact_check": ko_fact,
        "fact_check_en": en_fact,
        "success": False,
    }


def generate_shorts_upload_package(
    topic: str = "",
    script_text: str = "",
    gemini_api_key: str = "",
) -> dict:
    """
    유튜브 쇼츠 업로드용 풀패키지(제목 3종, 설명란, 해시태그, 스튜디오 태그, 고정댓글 & 팩트체크)를
    한국어 및 글로벌 영어 2가지 언어 버전으로 동시 생성합니다.
    """
    topic_clean = topic.strip() or "유튜브 쇼츠"
    script_clean = script_text.strip()

    prompt = f"""당신은 유튜브 쇼츠 알고리즘 SEO 및 밀리터리/지식 교양 채널 업로드 전문 마케터입니다.
제공된 영상의 주제와 대본을 바탕으로, 유튜브 스튜디오 업로드 화면에 바로 복사-붙여넣기할 수 있는 [유튜브 쇼츠 업로드 풀패키지 5대 핵심 항목]을 생성하세요.

[영상 정보]
- 주제: {topic_clean}
- 대본 전문:
{script_clean[:1800] if script_clean else topic_clean}

[5대 필수 항목 생성 규칙 (한국어 및 글로벌 영어 동시 생성)]
1. [제목 추천 3종 (titles / titles_en)]:
   - 60자 이내, 모바일에서 잘리지 않고 시청자의 클릭을 유도하는 제목 3가지:
     * 1안 (호기심·결핍 자극형): "외형은 똑같은데 결정적 '이것'이 없다? {topic_clean} #쇼츠"
     * 2안 (충격 팩트·수치 환산형): "대당 150억인데 실전에서 0초 컷 당한 이유 #Shorts"
     * 3안 (직관적 검색 최적화형): "{topic_clean} 핵심 스펙과 작동 원리 1분 총정리 #쇼츠"
   - [titles_en]: 해외 시청자가 클릭할 네이티브 영문 제목 3개 (#Shorts 포함, 60자 이내).

2. [유튜브 설명란 (description / description_en)]:
   - 알고리즘 검색(SEO) 키워드가 자연스럽게 녹아든 2~3줄 요약문.
   - [📌 핵심 팩트 포인트]: 대본 속 가장 중요한 팩트/제원/수치 3~4줄 정리.
   - 시청 감사 인사 및 하단 필수 해시태그 5~7개 포함 완성형 텍스트.
   - [description_en]: 네이티브 영문 설명란 (요약문 + 팩트 불릿 + 영문 해시태그).

3. [해시태그 (hashtags / hashtags_en)]:
   - 설명란이나 제목에 바로 붙일 수 있는 # 태그 모음 7~10개 (예: #밀리터리 #K방산 #쇼츠 #Shorts ...).
   - [hashtags_en]: 영문 해시태그 7~10개 (예: #Military #DefenseTech #Shorts ...).

4. [유튜브 스튜디오 태그 (tags_csv / tags_csv_en)]:
   - 유튜브 업로드 창의 '태그' 란에 통째로 붙여넣으면 쉼표(,) 단위로 자동 분리되는 15~20개 키워드.
   - (예: 키워드1, 키워드2, 키워드3, ...)
   - [tags_csv_en]: 쉼표로 구분된 영문 검색 키워드 15~20개.

5. [고정 댓글 & 팩트체크 (pinned_comment / pinned_comment_en)]:
   - 영상 업로드 직후 첫 댓글로 달고 [댓글 고정]하여 시청자 참여를 유도하고 고증 논란을 방지하는 텍스트:
     * 1) 시청자 의견 유도 질문 1줄 (예: "👇 여러분이 보시기에 가장 결정적인 차이는 무엇인가요?")
     * 2) [📌 영상 속 팩트체크 요약]: 영상의 핵심 사실, 수치, 공식 제원 데이터 3~4줄 요약 (태클 방지용 근거).
   - [pinned_comment_en]: 네이티브 영문 시청자 토론 유도 질문 + 팩트체크 요약문.
   - [fact_check / fact_check_en]: 고정 댓글과 별개로 순수 팩트체크 3~4줄 요약 데이터.

반드시 다음 JSON 포맷으로만 응답하세요:
{{
  "titles": ["1안 제목", "2안 제목", "3안 제목"],
  "description": "설명란 전문 텍스트 (줄바꿈 포함)",
  "hashtags": "#태그1 #태그2 #태그3 ...",
  "tags_csv": "키워드1, 키워드2, 키워드3, ...",
  "pinned_comment": "고정 댓글 및 팩트체크 전문 텍스트",
  "fact_check": "핵심 팩트체크 근거 요약문 (3~4줄)",
  "titles_en": ["Option 1 Title (#Shorts)", "Option 2 Title (#Shorts)", "Option 3 Title (#Shorts)"],
  "description_en": "English Description Full Text",
  "hashtags_en": "#Tag1 #Tag2 #Tag3 ...",
  "tags_csv_en": "Keyword1, Keyword2, Keyword3, ...",
  "pinned_comment_en": "English Pinned Comment & Fact-Check Full Text",
  "fact_check_en": "English Fact-Check Summary (3-4 lines)"
}}
"""

    if not gemini_api_key:
        return _fallback_shorts_upload_package(topic_clean, script_clean)

    try:
        raw_res = _call_gemini_api(prompt, gemini_api_key, json_mode=True)
        if not raw_res:
            return _fallback_shorts_upload_package(topic_clean, script_clean)

        clean_json = re.sub(r"^```(?:json)?\s*", "", raw_res.strip(), flags=re.MULTILINE)
        clean_json = re.sub(r"\s*```$", "", clean_json.strip())
        data = json.loads(clean_json)
        data["success"] = True
        return data
    except Exception as e:
        print(f"[generate_shorts_upload_package] Error: {e}")
        return _fallback_shorts_upload_package(topic_clean, script_clean)



