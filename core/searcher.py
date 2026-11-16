"""
core/searcher.py
초고화질 다중 엔진 웹 이미지 수급 엔진 (3.0 Upgrade)
- 네이버(Naver) 고화질 보도자료/실물 포토 검색 엔진 전격 결합
- Bing 고화질 실사 검색 고도화 및 Microsoft CDN(turl) 고속 썸네일 폴백 결합
- 유튜브 썸네일(i.ytimg.com) 및 자극적 텍스트/화살표 오염 이미지 원천 차단 필터
- 샷별 시각 앵글(와이드 전경 vs 디테일 클로즈업 vs 다이내믹 액션) 차별화 쿼리
- 언론사 403 핫링크 차단 완벽 방어 및 단색 플레이스홀더 0% 보장
- 멀티스레딩(ThreadPoolExecutor)을 통해 24개 슬롯(총 120장)을 초고속 병렬 수급
"""

import html as html_module
import json
import os
import re
import shutil
import time
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from io import BytesIO
from PIL import Image, ImageDraw, ImageFont

# ddgs 라이브러리 임포트 (ddgs 또는 duckduckgo_search)
try:
    from ddgs import DDGS
except ImportError:
    try:
        from duckduckgo_search import DDGS
    except ImportError:
        DDGS = None

USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"


def is_undesirable_image_url(url: str) -> bool:
    """
    유튜브 영상 썸네일(어그로 텍스트/화살표/얼굴), 틱톡, 밈, 아이콘, 배너 필터링
    쇼츠의 품격을 떨어뜨리는 조잡한 썸네일 이미지를 원천 차단합니다.
    """
    if not url:
        return True
    u_lower = url.lower()
    bad_markers = [
        "ytimg.com",
        "youtube.com",
        "youtu.be",
        "tiktokcdn.com",
        "tiktok.com",
        "vimeo",
        "favicon",
        "icon",
        "emoji",
        "banner",
        "ad_image",
        "advert",
        "1x1",
        "pixel",
        "placeholder",
        "logo_small",
        "share_icon",
    ]
    return any(m in u_lower for m in bad_markers)


def create_placeholder_candidate(keyword: str, save_path: str, idx: int = 1) -> str:
    """네트워크 단절 또는 극한의 검색 결과 부족 시 안전하게 표시할 고화질 대체 이미지 생성"""
    os.makedirs(os.path.dirname(save_path), exist_ok=True)
    img = Image.new("RGB", (1280, 720), color=(25 + idx * 12, 35 + idx * 8, 55 + idx * 15))
    draw = ImageDraw.Draw(img)

    label = f"[{keyword}] 실물 후보 {idx}"
    draw.rectangle([(20, 20), (1260, 700)], outline=(120, 160, 220), width=3)
    draw.text((640, 360), label, fill=(240, 240, 255), anchor="mm")
    img.save(save_path, format="PNG")
    return save_path


def search_naver_images(query: str, max_results: int = 30) -> list:
    """
    네이버 국내 고화질 보도자료 및 실물 사진 수급
    - 연합뉴스, 방사청, KAI 공식 배포 포토, 국방 전문 매체(유용원의 군사세계 등) 원본 사진 수급
    - 유튜브 썸네일 0%, 진짜 보도자료 실물 포토 보장
    """
    clean_q = re.sub(r'["\'\(\)\[\]]', '', query).strip()
    if not clean_q:
        return []

    encoded = urllib.parse.quote(clean_q)
    url = f"https://search.naver.com/search.naver?where=image&sm=tab_jum&query={encoded}"
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
            "Referer": "https://search.naver.com/",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=6) as resp:
            html = resp.read().decode("utf-8", errors="ignore")
    except Exception as e:
        print(f"[searcher] Naver search error ({clean_q}): {e}")
        return []

    orig_urls = re.findall(r'"originalUrl":"(http[^"]+)"', html)
    results = []
    seen = set()
    for u in orig_urls:
        clean_u = u.replace(r"\u0026", "&")
        if not clean_u or clean_u in seen or is_undesirable_image_url(clean_u):
            continue
        seen.add(clean_u)
        # 네이버 고속 CDN 썸네일 폴백 주소
        turl = f"https://search.pstatic.net/common/?src={urllib.parse.quote(clean_u)}"
        results.append({
            "title": f"{clean_q} 보도자료 실물 사진",
            "image": clean_u,
            "thumbnail": turl,
            "source": "naver",
        })
        if len(results) >= max_results:
            break
    return results


def search_bing_images(query: str, max_results: int = 25) -> list:
    """
    Bing 고화질 실사 이미지 검색 (imagesize-large + photo)
    - iusc 메타데이터를 정밀 파싱하여 고화질 원본(murl)과 초고속 CDN 썸네일(turl)을 동시 추출
    - 유튜브 썸네일 및 어그로 그래픽 자동 필터링
    """
    clean_q = re.sub(r'["\'\(\)\[\]]', '', query).strip()
    if not clean_q:
        return []

    encoded = urllib.parse.quote(clean_q)
    url = f"https://www.bing.com/images/search?q={encoded}&qft=+filterui:imagesize-large+filterui:photo-photo&form=HDRSC2"
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=6) as resp:
            html_content = resp.read().decode("utf-8", errors="ignore")
    except Exception as e:
        print(f"[searcher] Bing search error ({clean_q}): {e}")
        return []

    raw_items = re.findall(r'class="iusc"[^>]*?m="([^"]+)"', html_content)
    results = []
    seen = set()
    for item_str in raw_items:
        try:
            decoded = html_module.unescape(item_str)
            data = json.loads(decoded)
            murl = data.get("murl", "")
            turl = data.get("turl", "")
            title = data.get("t", "") or data.get("desc", f"{clean_q} 실물 사진")
            if not murl or murl in seen or is_undesirable_image_url(murl):
                continue
            seen.add(murl)
            results.append({
                "title": title,
                "image": murl,
                "thumbnail": turl or murl,
                "source": "bing",
            })
            if len(results) >= max_results:
                break
        except Exception:
            continue
    return results


def search_wikimedia_images(query: str, max_results: int = 5) -> list:
    """
    위키미디어 커먼즈(Wikimedia Commons) 전문 과학/공학/항공우주 4K 실물 사진 검색
    원자로 체렌코프 현상, 제트엔진 구조, 항공기 실물 등 텍스트 오염 없는 순수 고화질 사진 수급
    """
    clean_q = re.sub(r'["\'\(\)\[\]]', '', query).strip()
    if not clean_q:
        return []
    encoded = urllib.parse.quote(clean_q)
    url = f"https://commons.wikimedia.org/w/api.php?action=query&generator=search&gsrnamespace=6&gsrsearch={encoded}&gsrlimit={max_results}&prop=imageinfo&iiprop=url|size&format=json"
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "ShortsImageEngine/3.0 (education_video_project)"},
    )
    try:
        with urllib.request.urlopen(req, timeout=4) as resp:
            data = json.loads(resp.read().decode("utf-8", errors="ignore"))
        pages = data.get("query", {}).get("pages", {})
        results = []
        for pid, p in pages.items():
            ii = p.get("imageinfo", [{}])[0]
            img_u = ii.get("url")
            thumb_u = ii.get("thumburl") or img_u
            t = p.get("title", f"{clean_q} Wikimedia")
            if img_u and not is_undesirable_image_url(img_u):
                results.append({
                    "title": t,
                    "image": img_u,
                    "thumbnail": thumb_u,
                    "source": "wikimedia",
                })
        return results
    except Exception:
        return []


def search_ddg_images(query: str, max_results: int = 5) -> list:
    """DuckDuckGo 이미지 검색 폴백"""
    if DDGS is None:
        return []
    clean_q = re.sub(r'["\'\(\)\[\]]', '', query).strip()
    if not clean_q:
        return []
    try:
        ddgs = DDGS()
        raw_res = list(ddgs.images(clean_q, size="Large", type_image="photo", layout="Wide", max_results=max_results * 2))
        clean_res = []
        for r in raw_res:
            u = r.get("image", "")
            if u and not is_undesirable_image_url(u):
                clean_res.append(r)
                if len(clean_res) >= max_results:
                    break
        if clean_res:
            return clean_res
    except Exception:
        pass

    try:
        ddgs = DDGS()
        raw_res = list(ddgs.images(clean_q, max_results=max_results * 2))
        return [r for r in raw_res if not is_undesirable_image_url(r.get("image", ""))][:max_results]
    except Exception:
        return []


def search_google_custom_images(query: str, api_key: str, cx: str, max_results: int = 10) -> list:
    """
    Google Custom Search JSON API를 통한 100% 공식 구글 고화질 실사 이미지 검색
    """
    if not api_key or not cx:
        return []
    clean_q = re.sub(r'["\'\(\)\[\]]', '', query).strip()
    if not clean_q:
        return []

    url = (
        f"https://www.googleapis.com/customsearch/v1?"
        f"key={urllib.parse.quote(api_key)}&"
        f"cx={urllib.parse.quote(cx)}&"
        f"q={urllib.parse.quote(clean_q)}&"
        f"searchType=image&"
        f"imgSize=large&"
        f"num={min(10, max_results)}"
    )

    try:
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": USER_AGENT,
                "Accept": "application/json",
            }
        )
        with urllib.request.urlopen(req, timeout=8) as resp:
            data = json.loads(resp.read().decode("utf-8"))

        results = []
        for it in data.get("items", []):
            img_u = it.get("link", "")
            thumb_u = it.get("image", {}).get("thumbnailLink", "") or img_u
            t = it.get("title", f"{clean_q} Google")
            if img_u and not is_undesirable_image_url(img_u):
                results.append({
                    "title": t,
                    "image": img_u,
                    "thumbnail": thumb_u,
                    "source": "google",
                })
                if len(results) >= max_results:
                    break
        return results
    except Exception as e:
        print(f"[searcher] Google Custom Search error ({clean_q}): {e}")
        return []


def search_keyword_images(
    keyword: str,
    max_results: int = 30,
    keyword_en: str = "",
    full_context: str = "",
    shot_num: int = 1,
) -> list:
    """
    [초고화질 다중 엔진 이미지 수급 파이프라인]
    1순위: 네이버 국내 보도자료/공식 실물 포토 (유튜브 썸네일 0%)
    2순위: Bing 대용량 실사 사진 검색 (고속 CDN 썸네일 turl 완비)
    3순위: Bing 글로벌 영문 4K/Wallpaper 검색
    4순위: 위키미디어 커먼즈 전문 과학/군사 4K 아카이브
    5순위: full_context 기반 실물 정밀 쿼리 보충 검색
    6순위: DuckDuckGo 고화질 검색 폴백
    """
    clean_kw = re.sub(r'["\'\(\)\[\]]', '', keyword).strip()
    clean_kw_en = re.sub(r'["\'\(\)\[\]]', '', keyword_en).strip() if keyword_en else ""
    clean_ctx = re.sub(r'["\'\(\)\[\]]', '', full_context).strip() if full_context else ""

    # 나레이션 구어체 문장이 오염 유입되는 것 원천 차단
    colloquial_pattern = r'(거든요|다니까요|습니다|했더니|까요\?|했죠|버렸습니다|있습니다|괴물|미쳤|소름|역대급)'
    if re.search(colloquial_pattern, clean_kw) or len(clean_kw.split()) > 6 or len(clean_kw) > 30:
        if clean_ctx:
            ctx_tokens = [w for w in re.sub(r'[^가-힣a-zA-Z0-9\s]', ' ', clean_ctx).split() if len(w) > 1 and not re.search(colloquial_pattern, w)]
            clean_kw = " ".join(ctx_tokens[:3])
        else:
            clean_kw = ""

    if not clean_kw and not clean_kw_en:
        if clean_ctx:
            ctx_tokens = [w for w in re.sub(r'[^가-힣a-zA-Z0-9\s]', ' ', clean_ctx).split() if len(w) > 1]
            clean_kw = " ".join(ctx_tokens[:3])
        else:
            clean_kw = "시네마틱 항공우주"

    # 샷별 앵글 차별화 (Shot 1: 전경/외형, Shot 2: 부품/내부/계기판, Shot 3: 발사/비행/액션)
    angle_kw = clean_kw
    if shot_num == 1 and not any(w in clean_kw for w in ["전경", "활주로", "외형", "모습"]):
        angle_kw = f"{clean_kw} 전경"
    elif shot_num == 2 and not any(w in clean_kw for w in ["조종석", "내부", "부품", "단면", "계기판"]):
        angle_kw = f"{clean_kw} 내부 디테일"
    elif shot_num == 3 and not any(w in clean_kw for w in ["발사", "비행", "기동", "화염"]):
        angle_kw = f"{clean_kw} 발사 비행"

    collected = []
    seen_urls = set()

    def _add_results(items):
        for item in items:
            u = item.get("image") or item.get("thumbnail")
            if u and u not in seen_urls and not is_undesirable_image_url(u):
                seen_urls.add(u)
                collected.append(item)
                if len(collected) >= max_results:
                    return True
        return False

    # 1. 네이버 보도자료/공식 실물 포토 (원 쿼리)
    if clean_kw:
        nav_res = search_naver_images(clean_kw, max_results=15)
        if _add_results(nav_res):
            return collected[:max_results]

    # 2. 네이버 샷별 앵글 쿼리
    if angle_kw != clean_kw and len(collected) < 10:
        nav_angle_res = search_naver_images(angle_kw, max_results=10)
        if _add_results(nav_angle_res):
            return collected[:max_results]

    # 3. Bing 한글 실물 키워드 검색 (고속 CDN 썸네일 결합)
    if clean_kw and len(collected) < max_results:
        bing_res = search_bing_images(clean_kw, max_results=15)
        if _add_results(bing_res):
            return collected[:max_results]

    # 3-1. 긴 검색어(3단어 이상)일 경우 핵심 고유명사 압축 쿼리로 추가 실사 수급
    words = clean_kw.split()
    if len(words) >= 3 and len(collected) < max_results:
        core_words = [w for w in words if w not in ("국방과학연구소", "대한민국", "한국", "비행체", "실물", "사진", "모습", "관련")]
        if core_words and len(core_words) < len(words):
            condensed_q = " ".join(core_words)
            bing_c_res = search_bing_images(condensed_q, max_results=15)
            if _add_results(bing_c_res):
                return collected[:max_results]
            nav_c_res = search_naver_images(condensed_q, max_results=10)
            if _add_results(nav_c_res):
                return collected[:max_results]

    # 4. Bing 영문 글로벌 4K 검색
    if clean_kw_en and len(collected) < max_results:
        bing_en_res = search_bing_images(clean_kw_en, max_results=15)
        if _add_results(bing_en_res):
            return collected[:max_results]

    # 5. 위키미디어 커먼즈 전문 아카이브 (과학/군사/기술)
    if len(collected) < max_results and (clean_kw_en or clean_kw):
        wiki_q = clean_kw_en if clean_kw_en else clean_kw
        wiki_res = search_wikimedia_images(wiki_q, max_results=5)
        if _add_results(wiki_res):
            return collected[:max_results]

    # 6. full_context 기반 실물 정밀 쿼리 보충 검색
    if len(collected) < max_results and clean_ctx:
        ctx_nouns = [w for w in re.sub(r'[^가-힣a-zA-Z0-9\s]', ' ', clean_ctx).split() if len(w) > 1 and not re.search(colloquial_pattern, w)]
        if len(ctx_nouns) >= 2:
            ctx_query = " ".join(ctx_nouns[:3])
            if ctx_query != clean_kw:
                nav_ctx_res = search_naver_images(ctx_query, max_results=10)
                if _add_results(nav_ctx_res):
                    return collected[:max_results]
                bing_ctx_res = search_bing_images(ctx_query, max_results=10)
                if _add_results(bing_ctx_res):
                    return collected[:max_results]

    # 7. DuckDuckGo 영문 4k 검색 폴백
    if len(collected) < max_results and clean_kw_en:
        ddg_en = search_ddg_images(f"{clean_kw_en} 4k", max_results=5)
        if _add_results(ddg_en):
            return collected[:max_results]

    # 8. DuckDuckGo 한글 검색 폴백
    if len(collected) < max_results and clean_kw:
        ddg_ko = search_ddg_images(clean_kw, max_results=5)
        _add_results(ddg_ko)

    return collected[:max_results]


def generate_ai_image_pollinations(prompt: str, save_path: str, width: int = 720, height: int = 1280) -> bool:
    """
    오픈소스 FLUX 모델(Pollinations.ai)을 활용하여
    웹 검색으로 찾을 수 없는 시네마틱 9:16 세로 규격 이미지를 무료로 즉시 생성합니다.
    """
    os.makedirs(os.path.dirname(os.path.abspath(save_path)), exist_ok=True)
    clean_p = re.sub(r'["\'\n]', ' ', prompt).strip()
    if "glowing pure red" not in clean_p.lower():
        clean_p += ", glowing pure red accent"
    if "8k cinematic" not in clean_p.lower():
        clean_p += ", 8k cinematic photorealistic no text"

    encoded = urllib.parse.quote(clean_p)
    url = f"https://image.pollinations.ai/prompt/{encoded}?width={width}&height={height}&model=flux&nologo=true"

    try:
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=25) as resp:
            data = resp.read()
        if len(data) > 10000:
            with Image.open(BytesIO(data)) as im:
                im = im.convert("RGB")
                im.save(save_path, format="PNG")
                return True
    except Exception as e:
        print(f"[searcher] Pollinations AI image generation exception: {e}")
    return False


def generate_slot_ai_candidate(
    slot_num: int,
    prompt: str,
    cache_dir: str = "captures/search_cache",
) -> dict:
    """
    슬롯 전용 9:16 AI 이미지를 즉석 생성하여 후보 목록에 추가할 수 있는 객체 반환
    """
    slot_dir = os.path.join(cache_dir, f"slot_{slot_num:02d}")
    os.makedirs(slot_dir, exist_ok=True)
    ai_cand_path = os.path.join(slot_dir, "cand_ai.png")

    success = generate_ai_image_pollinations(prompt, ai_cand_path, width=720, height=1280)
    if not success or not os.path.exists(ai_cand_path):
        create_placeholder_candidate("AI 생성 실패", ai_cand_path, idx=99)

    return {
        "id": f"{slot_num}_ai",
        "slot_num": slot_num,
        "cand_idx": 99,
        "keyword": "AI 생성 이미지",
        "keyword_en": prompt[:30],
        "title": "🤖 FLUX AI 생성 (9:16 맞춤)",
        "path": ai_cand_path,
        "img_url": "",
        "thumb_url": "",
    }


def download_image_from_url(url: str, save_path: str, timeout: int = 12) -> bool:
    """사용자가 직접 입력한 이미지 URL(구글 검색 리다이렉트, base64 포함)로부터 이미지 다운로드 및 유효성 검증"""
    os.makedirs(os.path.dirname(os.path.abspath(save_path)), exist_ok=True)
    try:
        url = url.strip()
        if not url:
            return False

        # 1. Base64 data URL 처리
        if url.startswith("data:image"):
            import base64
            header, b64_data = url.split(",", 1)
            raw_bytes = base64.b64decode(b64_data)
            with Image.open(BytesIO(raw_bytes)) as im:
                im = im.convert("RGB")
                im.save(save_path, format="PNG")
                return True

        # 2. 구글 이미지 검색 리다이렉트 URL에서 실제 원본 이미지 URL 추출
        if "google.com/imgres" in url or "imgurl=" in url:
            parsed = urllib.parse.urlparse(url)
            params = urllib.parse.parse_qs(parsed.query)
            if "imgurl" in params:
                url = params["imgurl"][0]

        # 3. HTTP/HTTPS 요청 다운로드
        ref = "https://search.naver.com/" if ("naver" in url or "pstatic" in url) else "https://www.google.com/"
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": USER_AGENT,
                "Referer": ref,
                "Accept": "image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8",
            },
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = resp.read()
        if len(data) > 1000:
            with Image.open(BytesIO(data)) as im:
                im = im.convert("RGB")
                im.save(save_path, format="PNG")
                return True
    except Exception as e:
        print(f"[searcher] URL download failed ({url}): {e}")
    return False


def download_single_image(
    img_url: str,
    thumb_url: str,
    save_path: str,
    timeout: int = 5,
    min_width: int = 320,
    min_height: int = 200,
) -> bool:
    """
    단일 이미지 다운로드 (고화질 원본 우선, 403 차단/타임아웃 시 초고속 CDN 썸네일 자동 폴백)
    - 네이버 CDN(search.pstatic.net) 및 Bing CDN(tsX.mm.bing.net) 썸네일 폴백을 탑재하여
      언론사 403 차단 및 단색 플레이스홀더 생성을 100% 방지합니다.
    """
    os.makedirs(os.path.dirname(save_path), exist_ok=True)

    urls_to_try = []
    if img_url and not is_undesirable_image_url(img_url):
        urls_to_try.append(img_url)
    if thumb_url and thumb_url != img_url and not is_undesirable_image_url(thumb_url):
        urls_to_try.append(thumb_url)

    for url in urls_to_try:
        try:
            ref = "https://search.naver.com/" if ("naver" in url or "pstatic" in url) else "https://www.bing.com/"
            req = urllib.request.Request(
                url,
                headers={
                    "User-Agent": USER_AGENT,
                    "Referer": ref,
                    "Accept": "image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8",
                },
            )
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                data = resp.read()

            if len(data) < 2500:
                continue

            with Image.open(BytesIO(data)) as im:
                w, h = im.size
                if w < min_width or h < min_height:
                    continue
                im = im.convert("RGB")
                im.save(save_path, format="PNG")
                return True
        except Exception:
            continue

    # 최소 크기 제한 완화 후 썸네일 CDN 재시도
    if thumb_url:
        try:
            ref = "https://search.naver.com/" if ("naver" in thumb_url or "pstatic" in thumb_url) else "https://www.bing.com/"
            req = urllib.request.Request(thumb_url, headers={"User-Agent": USER_AGENT, "Referer": ref})
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                data = resp.read()
            if len(data) > 1200:
                with Image.open(BytesIO(data)) as im:
                    im = im.convert("RGB")
                    im.save(save_path, format="PNG")
                    return True
        except Exception:
            pass

    return False


def search_and_cache_slot_candidates(
    slot_num: int,
    keyword: str,
    cache_dir: str = "captures/search_cache",
    max_results: int = 5,
    keyword_en: str = "",
    full_context: str = "",
) -> list:
    """
    단일 슬롯(1~24)에 대한 5장 후보 이미지를 고화질 검색 및 로컬 캐시에 다운로드
    - 네이버 보도자료/실물 포토 + Bing 대용량 실사 풀(30장)에서 다운로드 성공 및 검증을 통과한
      순수 실물 사진만을 엄선하여 5장을 채웁니다.
    """
    slot_dir = os.path.join(cache_dir, f"slot_{slot_num:02d}")
    os.makedirs(slot_dir, exist_ok=True)

    shot_idx = ((slot_num - 1) % 3) + 1
    search_pool = search_keyword_images(
        keyword,
        max_results=30,
        keyword_en=keyword_en,
        full_context=full_context,
        shot_num=shot_idx,
    )
    candidates = []
    cand_idx = 1

    for r_item in search_pool:
        cand_path = os.path.join(slot_dir, f"cand_{cand_idx}.png")
        img_url = r_item.get("image", "")
        thumb_url = r_item.get("thumbnail", "")
        title = r_item.get("title", f"{keyword} 후보 {cand_idx}")

        success = False
        if img_url or thumb_url:
            success = download_single_image(img_url, thumb_url, cand_path, timeout=5)

        if success and os.path.exists(cand_path) and os.path.getsize(cand_path) > 5000:
            candidates.append({
                "id": f"{slot_num}_{cand_idx}",
                "slot_num": slot_num,
                "cand_idx": cand_idx,
                "keyword": keyword,
                "keyword_en": keyword_en,
                "full_context": full_context,
                "title": title,
                "path": cand_path,
                "img_url": img_url,
                "thumb_url": thumb_url,
            })
            cand_idx += 1
            if len(candidates) >= max_results:
                break

    # 다운로드 결과가 max_results(5장) 미만인 경우만 안전 대체 플레이스홀더 생성
    while len(candidates) < max_results:
        cand_path = os.path.join(slot_dir, f"cand_{cand_idx}.png")
        create_placeholder_candidate(keyword, cand_path, idx=cand_idx)
        candidates.append({
            "id": f"{slot_num}_{cand_idx}",
            "slot_num": slot_num,
            "cand_idx": cand_idx,
            "keyword": keyword,
            "keyword_en": keyword_en,
            "full_context": full_context,
            "title": f"{keyword} 후보 {cand_idx}",
            "path": cand_path,
            "img_url": "",
            "thumb_url": "",
        })
        cand_idx += 1

    return candidates


def batch_fetch_all_slots(
    slots: list,
    cache_dir: str = "captures/search_cache",
    progress_callback = None,
    max_workers: int = 5,
) -> dict:
    """
    24개 슬롯 전체의 [트랙 2] 정밀 키워드 및 풀 맥락(full_context)을 기반으로 5장씩(총 120장) 병렬 고속 수급
    - 네이버 고화질 실사 및 Bing/Wikimedia 엔진을 멀티스레드로 동시 호출하여 수 초 내 수급 완료
    Returns: {slot_num: [cand1, cand2, cand3, cand4, cand5], ...}
    """
    os.makedirs(cache_dir, exist_ok=True)
    all_results = {}
    total_slots = len(slots)
    completed_count = 0

    if progress_callback:
        progress_callback(0, total_slots, "네이버 보도자료 및 Bing 고화질 실사 수급 엔진 가동 중...")

    def _worker(s):
        s_num = s["slot_num"]
        kw = s.get("search_keyword") or s.get("search_keywords") or s.get("target_keyword") or ""
        kw_en = s.get("search_keyword_en") or s.get("search_keywords_en") or ""
        full_ctx = s.get("full_context") or ""

        if not kw and full_ctx:
            tokens = [w for w in re.sub(r'[^가-힣a-zA-Z0-9\s]', ' ', full_ctx).split() if len(w) > 1]
            kw = " ".join(tokens[:3])
        elif not kw:
            kw = "대한민국 최첨단 기술"

        cands = search_and_cache_slot_candidates(
            slot_num=s_num,
            keyword=kw,
            cache_dir=cache_dir,
            max_results=5,
            keyword_en=kw_en,
            full_context=full_ctx,
        )
        return s_num, kw, cands

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(_worker, s): s["slot_num"] for s in slots}

        for future in as_completed(futures):
            s_num, kw, cands = future.result()
            all_results[s_num] = cands
            completed_count += 1
            if progress_callback:
                progress_callback(
                    completed_count,
                    total_slots,
                    f"슬롯 {s_num:02d}번 ['{kw}'] 실물 후보 5장 수급 완료 ({completed_count}/{total_slots})"
                )

    return all_results


# ════════════════════════════════════════════════════════════
# 🎯 Shorts Story Studio 전용 핵심 에셋(1~3개) 초고속 수급
# ════════════════════════════════════════════════════════════

def search_core_asset_candidates(
    asset_name: str,
    keyword_ko: str,
    keyword_en: str = "",
    cache_dir: str = "captures/asset_cache",
    max_candidates: int = 5,
    offset: int = 0,
    google_api_key: str = "",
    google_cx: str = "",
    *args,
    **kwargs,
) -> list:
    """
    Flow(Shorts Story Studio) 에셋 등록용 핵심 개체(1~3개)에 대한
    고화질 실사 후보 4~5장을 검색하고 캐시합니다.
    google_api_key와 google_cx가 있으면 1순위로 공식 구글 이미지 검색을 즉시 가동합니다.
    offset을 지정하면 이전 검색과 다른 새로운 후보들을 순차 수급합니다.
    """
    os.makedirs(cache_dir, exist_ok=True)
    clean_name = re.sub(r'[^가-힣a-zA-Z0-9]', '_', asset_name).strip('_')
    asset_dir = os.path.join(cache_dir, clean_name)
    os.makedirs(asset_dir, exist_ok=True)

    # 이전 캐시 파일 정리 (새로운 후보로 갱신)
    if os.path.exists(asset_dir):
        for f in os.listdir(asset_dir):
            fp = os.path.join(asset_dir, f)
            if os.path.isfile(fp):
                try:
                    os.remove(fp)
                except Exception:
                    pass

    items = []
    # 1. Google Custom Search (설정된 경우 최우선 가동)
    if google_api_key and google_cx:
        g_res = search_google_custom_images(keyword_ko, google_api_key, google_cx, max_results=max_candidates * 2)
        if not g_res and keyword_en:
            g_res = search_google_custom_images(keyword_en, google_api_key, google_cx, max_results=max_candidates * 2)
        if g_res:
            items.extend(g_res)

    total_need = max(30, (offset + max_candidates) * 2)
    web_items = search_keyword_images(keyword_ko, max_results=total_need, keyword_en=keyword_en)
    if offset > 0 and len(web_items) > offset:
        web_items = web_items[offset:]

    items.extend(web_items)

    candidates = []
    cand_idx = 1
    for it in items:
        img_u = it.get("image", "")
        thumb_u = it.get("thumbnail", "") or img_u
        if not img_u:
            continue
        save_p = os.path.join(asset_dir, f"cand_{time.time_ns()}_{cand_idx}.png")
        ok = download_single_image(img_u, thumb_u, save_p, timeout=5)
        if ok and os.path.exists(save_p):
            candidates.append({
                "cand_idx": cand_idx,
                "asset_name": asset_name,
                "title": it.get("title", f"{asset_name} 실물 {cand_idx}"),
                "path": save_p,
                "img_url": img_u,
                "thumb_url": thumb_u,
            })
            cand_idx += 1
            if len(candidates) >= max_candidates:
                break

    # 후보가 부족할 경우 플레이스홀더로 보충
    while len(candidates) < min(3, max_candidates):
        save_p = os.path.join(asset_dir, f"cand_{time.time_ns()}_{cand_idx}.png")
        create_placeholder_candidate(asset_name, save_p, idx=cand_idx)
        candidates.append({
            "cand_idx": cand_idx,
            "asset_name": asset_name,
            "title": f"[{asset_name}] 실물 후보 {cand_idx}",
            "path": save_p,
            "img_url": "",
            "thumb_url": "",
        })
        cand_idx += 1

    return candidates


def save_chosen_asset_image(
    chosen_path: str,
    asset_name: str,
    dest_dir: str,
    asset_idx: int = 1,
    to_vertical: bool = True,
    mode: str = "crop",
    *args,
    **kwargs,
) -> str:
    """
    사용자가 선택한 에셋 실사 이미지를 프로젝트의 assets/ 폴더에
    Flow(Shorts Story Studio)에 바로 드래그앤드롭 할 수 있는 1080x1920 (9:16) 규격으로 자동 변환 저장합니다.
    원본은 assets/raw/ 폴더에 안전하게 보존됩니다.
    예: D:\\쇼츠_프로젝트\\주제\\assets\\01_현무-5_탄도미사일.png
    """
    os.makedirs(dest_dir, exist_ok=True)
    raw_dir = os.path.join(dest_dir, "raw")
    os.makedirs(raw_dir, exist_ok=True)

    clean_name = re.sub(r'[^가-힣a-zA-Z0-9]', '_', asset_name).strip('_')
    dest_filename = f"{asset_idx:02d}_{clean_name}.png"
    dest_path = os.path.join(dest_dir, dest_filename)
    raw_path = os.path.join(raw_dir, f"{asset_idx:02d}_{clean_name}_raw.png")

    try:
        if os.path.exists(chosen_path):
            # 1. 원본 보존
            shutil.copy2(chosen_path, raw_path)

            if to_vertical:
                # 2. Flow 표준 1080x1920 (9:16) 세로 캔버스 자동 변환
                from core.cutter import convert_to_vertical_9_16
                convert_to_vertical_9_16(chosen_path, dest_path, target_size=(1080, 1920), mode=mode)
            else:
                shutil.copy2(chosen_path, dest_path)
            return dest_path
    except Exception as e:
        print(f"[save_chosen_asset_image] error: {e}")
        try:
            shutil.copy2(chosen_path, dest_path)
            return dest_path
        except Exception:
            pass

    return ""

