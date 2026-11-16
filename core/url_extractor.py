"""
URL 및 유튜브 영상 콘텐츠/자막 자동 추출기
- 유튜브 URL 또는 일반 웹페이지 URL을 감지하여 제목, 본문/자막, 핵심 설명을 추출합니다.
- Gemini 젬스 대본 생성기에 실제 팩트 기반 컨텍스트를 공급합니다.
"""

import functools
import os
import re
import json
import urllib.request
import urllib.parse
from typing import Dict, Optional, Tuple


def is_url(text: str) -> bool:
    """주어진 텍스트가 웹 URL인지 여부를 판별합니다."""
    t = text.strip()
    if re.match(r"^https?://", t, re.IGNORECASE):
        return True
    if "youtube.com/" in t.lower() or "youtu.be/" in t.lower():
        return True
    return False


def is_youtube_url(text: str) -> bool:
    """유튜브 URL 또는 유튜브 11자리 비디오 ID인지 판별합니다."""
    t = text.strip()
    if "youtube.com" in t.lower() or "youtu.be" in t.lower():
        return True
    # 단독 11자리 알파벳/숫자/대시/언더바 ID 형식
    if re.match(r"^[a-zA-Z0-9_-]{11}$", t):
        return True
    return False


def extract_youtube_video_id(url_or_id: str) -> str:
    """다양한 유튜브 URL 형태에서 11자리 비디오 ID를 추출합니다."""
    t = url_or_id.strip()
    if re.match(r"^[a-zA-Z0-9_-]{11}$", t):
        return t
    patterns = [
        r"(?:v=|/v/|youtu\.be/|/embed/|/shorts/)([a-zA-Z0-9_-]{11})",
        r"(?:[?&]v=)([a-zA-Z0-9_-]{11})",
    ]
    for p in patterns:
        m = re.search(p, t)
        if m:
            return m.group(1)
    return ""


def _fetch_youtube_transcript(video_id: str) -> Tuple[str, str]:
    """
    youtube_transcript_api를 사용하여 한국어 또는 영어 자막(스크립트)을 가져옵니다.
    반환: (자막텍스트, 사용된언어코드)
    """
    if not video_id:
        return "", ""
    try:
        from youtube_transcript_api import YouTubeTranscriptApi
        api = YouTubeTranscriptApi()

        # 1. 지원 자막 목록 탐색
        transcript_list = api.list(video_id)
        best_t = None
        # 한국어 우선 -> 영어 -> 기타 첫 번째
        for code in ["ko", "ko-KR", "en", "en-US", "en-GB"]:
            try:
                best_t = transcript_list.find_transcript([code])
                if best_t:
                    break
            except Exception:
                continue

        if not best_t:
            # 첫 번째 사용 가능한 자막
            for t in transcript_list:
                best_t = t
                break

        if best_t:
            fetched = best_t.fetch()
            # snippets 결합
            text_parts = []
            for s in fetched.snippets:
                t_str = getattr(s, "text", "") if hasattr(s, "text") else str(s)
                t_str = t_str.strip()
                if t_str and t_str != "\n":
                    text_parts.append(t_str)
            full_text = " ".join(text_parts)
            # 너무 길면 쇼츠 대본 참조용으로 앞 3500자까지 슬라이스
            if len(full_text) > 3500:
                full_text = full_text[:3500] + "..."
            return full_text, getattr(best_t, "language_code", "unknown")
    except Exception as e:
        print(f"[_fetch_youtube_transcript] 자막 조회 실패 ({video_id}): {e}")

    return "", ""


def _fetch_youtube_metadata_ytdlp(url: str) -> Dict:
    """yt-dlp를 사용하여 유튜브 영상의 메타데이터(제목, 설명, 태그)를 가져옵니다."""
    info_dict = {"title": "", "description": "", "uploader": "", "tags": []}
    try:
        import yt_dlp
        ydl_opts = {
            "skip_download": True,
            "quiet": True,
            "no_warnings": True,
            "noplaylist": True,
        }
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            data = ydl.extract_info(url, download=False)
            if data:
                info_dict["title"] = (data.get("title") or "").strip()
                info_dict["description"] = (data.get("description") or "").strip()
                info_dict["uploader"] = (data.get("uploader") or data.get("channel") or "").strip()
                info_dict["tags"] = data.get("tags") or []
    except Exception as e:
        print(f"[_fetch_youtube_metadata_ytdlp] 메타데이터 조회 실패: {e}")

    return info_dict


def _fetch_youtube_metadata_fallback(video_id: str, url: str) -> Dict:
    """yt-dlp 실패 시 oEmbed API 및 웹페이지 스크래핑으로 제목/정보 조회"""
    info = {"title": "", "description": "", "uploader": ""}
    # 1. oEmbed 시도
    target_url = f"https://www.youtube.com/watch?v={video_id}" if video_id else url
    oembed_url = f"https://www.youtube.com/oembed?url={urllib.parse.quote(target_url)}&format=json"
    try:
        req = urllib.request.Request(oembed_url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=4) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            info["title"] = (data.get("title") or "").strip()
            info["uploader"] = (data.get("author_name") or "").strip()
    except Exception:
        pass

    # 2. 웹페이지 title 태그 시도
    if not info["title"]:
        try:
            req = urllib.request.Request(target_url, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"})
            with urllib.request.urlopen(req, timeout=4) as resp:
                html = resp.read().decode("utf-8", errors="ignore")
                m_title = re.search(r"<title>(.*?)</title>", html, re.IGNORECASE)
                if m_title:
                    raw_t = m_title.group(1).replace("- YouTube", "").replace("– YouTube", "").strip()
                    if raw_t:
                        info["title"] = raw_t
                m_desc = re.search(r'<meta\s+name="description"\s+content="([^"]*)"', html, re.IGNORECASE)
                if m_desc:
                    info["description"] = m_desc.group(1).strip()
        except Exception:
            pass

    return info


@functools.lru_cache(maxsize=64)
def extract_youtube_content(url_or_id: str) -> Dict:
    """
    유튜브 URL 또는 ID로부터 영상 제목, 설명, 자막(스크립트)을 종합 추출합니다.
    """
    video_id = extract_youtube_video_id(url_or_id)
    canonical_url = f"https://www.youtube.com/watch?v={video_id}" if video_id else url_or_id

    # 1. 메타데이터 조회 (yt-dlp 우선, fallback 보완)
    meta = _fetch_youtube_metadata_ytdlp(canonical_url)
    if not meta.get("title"):
        fb_meta = _fetch_youtube_metadata_fallback(video_id, canonical_url)
        if fb_meta.get("title"):
            meta.update({k: v for k, v in fb_meta.items() if v})

    # 2. 자막(스크립트) 조회
    transcript, lang = _fetch_youtube_transcript(video_id)

    raw_title = meta.get("title") or ""
    desc = meta.get("description") or ""
    uploader = meta.get("uploader") or ""

    has_content = bool(raw_title or transcript or desc)

    if not has_content:
        return {
            "success": False,
            "is_url": True,
            "is_youtube": True,
            "video_id": video_id,
            "canonical_url": canonical_url,
            "title": "",
            "uploader": "",
            "description": "",
            "transcript": "",
            "transcript_lang": "",
            "summary_text": "",
            "error": "해당 유튜브 영상에 접근할 수 없습니다 (유튜브에서 삭제되었거나 비공개, 재생 불가 처리된 영상).",
        }

    title = raw_title or (f"유튜브 영상 [{video_id}]" if video_id else "유튜브 영상")
    desc = meta.get("description") or ""
    uploader = meta.get("uploader") or ""

    # 설명란 정리 (너무 길면 앞 1500자)
    clean_desc = desc[:1500] + ("..." if len(desc) > 1500 else "")

    # AI 전달용 컨텍스트 조합
    summary_parts = []
    summary_parts.append(f"📌 [영상 원본 제목]: {title}")
    if uploader:
        summary_parts.append(f"👤 [채널/출처]: {uploader}")
    if clean_desc:
        summary_parts.append(f"📝 [영상 상세 설명 및 핵심 내용]:\n{clean_desc}")
    if transcript:
        summary_parts.append(f"🎙️ [영상 실제 자막(나레이션) 전문 ({lang})]:\n{transcript}")

    full_context = "\n\n".join(summary_parts)

    return {
        "success": True,
        "is_url": True,
        "is_youtube": True,
        "video_id": video_id,
        "canonical_url": canonical_url,
        "title": title,
        "uploader": uploader,
        "description": clean_desc,
        "transcript": transcript,
        "transcript_lang": lang,
        "summary_text": full_context,
    }


@functools.lru_cache(maxsize=64)
def extract_webpage_content(url: str) -> Dict:
    """
    일반 웹페이지 URL에서 제목과 본문 텍스트를 추출합니다.
    """
    try:
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            },
        )
        with urllib.request.urlopen(req, timeout=6) as resp:
            html = resp.read().decode("utf-8", errors="ignore")

        # 제목 추출
        m_title = re.search(r"<title>(.*?)</title>", html, re.IGNORECASE | re.DOTALL)
        title = m_title.group(1).strip() if m_title else "웹페이지 기사/자료"

        # 메타 설명
        m_desc = re.search(r'<meta\s+name=["\']description["\']\s+content=["\']([^"\']*)["\']', html, re.IGNORECASE)
        desc = m_desc.group(1).strip() if m_desc else ""

        # 본문 텍스트 추출 (스크립트/스타일 태그 제거 후 문단 추출)
        clean_html = re.sub(r"<(script|style|svg|noscript)[^>]*>.*?</\1>", "", html, flags=re.IGNORECASE | re.DOTALL)
        clean_text = re.sub(r"<[^>]+>", " ", clean_html)
        clean_text = re.sub(r"\s+", " ", clean_text).strip()

        # 앞 2500자 추출
        main_body = clean_text[:2500]

        summary_parts = [
            f"📌 [웹페이지 제목]: {title}",
        ]
        if desc:
            summary_parts.append(f"📝 [요약 설명]: {desc}")
        if main_body:
            summary_parts.append(f"📖 [웹페이지 본문 내용]:\n{main_body}")

        full_context = "\n\n".join(summary_parts)

        return {
            "success": True,
            "is_url": True,
            "is_youtube": False,
            "video_id": "",
            "canonical_url": url,
            "title": title,
            "uploader": "",
            "description": desc,
            "transcript": "",
            "transcript_lang": "",
            "summary_text": full_context,
        }
    except Exception as e:
        print(f"[extract_webpage_content] 웹페이지 추출 실패: {e}")
        return {
            "success": False,
            "is_url": True,
            "is_youtube": False,
            "video_id": "",
            "canonical_url": url,
            "title": "",
            "uploader": "",
            "description": "",
            "transcript": "",
            "transcript_lang": "",
            "summary_text": "",
            "error": str(e),
        }


def extract_url_or_topic_context(text: str) -> Dict:
    """
    사용자 입력 텍스트를 판별하여:
    - 유튜브 URL이면 유튜브 제목, 설명, 자막 추출
    - 일반 URL이면 웹페이지 제목, 본문 추출
    - 일반 키워드면 is_url=False 반환
    """
    clean_t = text.strip()
    if not is_url(clean_t):
        return {
            "success": True,
            "is_url": False,
            "is_youtube": False,
            "title": clean_t,
            "summary_text": clean_t,
        }

    if is_youtube_url(clean_t):
        return extract_youtube_content(clean_t)
    else:
        return extract_webpage_content(clean_t)
