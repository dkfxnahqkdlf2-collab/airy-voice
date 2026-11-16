# -*- coding: utf-8 -*-
"""
core.vs_all_in_one.studio_normalizer
[규격 정규화 엔진] 실물 고증 기준 소스(Reference Image)를 AI 배경 분리(rembg)하여
1080x1080 순백색 심리스 스튜디오 3D CAD 규격으로 자동 정규화하는 모듈.

- 배경 분리 (AI 누끼)
- 여백 및 피사체 바운딩박스 정밀 크롭
- 규격 캔버스 중앙 정렬 및 비율 통일
- 자연스러운 3D 스튜디오 소프트 접지 그림자(Ground Contact Shadow) 자동 합성
- 순백색(#FFFFFF) 스튜디오 버전과 투명 PNG 컷아웃 동시 생성
"""

import os
import math
from pathlib import Path
from typing import Dict, Any, Tuple, Optional
from PIL import Image, ImageFilter, ImageDraw, ImageOps


def normalize_to_studio_white_bg(
    input_path: str,
    output_path: str,
    target_size: Tuple[int, int] = (1080, 1080),
    max_subject_ratio: float = 0.86,
    add_ground_shadow: bool = True,
    bg_color: Tuple[int, int, int] = (255, 255, 255),
) -> Dict[str, Any]:
    """
    단일 이미지를 로드하여 배경을 분리하고, 순백색 1080x1080 스튜디오 규격으로 정규화합니다.
    """
    if not input_path or not os.path.exists(input_path):
        return {"success": False, "error": f"파일을 찾을 수 없습니다: {input_path}"}

    try:
        import rembg
    except ImportError:
        return {"success": False, "error": "rembg 라이브러리가 설치되지 않았습니다."}

    try:
        # 1. 원본 이미지 로드
        orig_img = Image.open(input_path).convert("RGBA")
        orig_w, orig_h = orig_img.size

        # 2. AI 배경 분리 실행
        cutout_rgba = rembg.remove(orig_img)

        # 3. 투명 영역 제외 피사체 바운딩 박스 정밀 추출
        bbox = cutout_rgba.getbbox()
        if bbox:
            cropped_subject = cutout_rgba.crop(bbox)
        else:
            cropped_subject = cutout_rgba

        sub_w, sub_h = cropped_subject.size
        canvas_w, canvas_h = target_size

        # 4. 목표 캔버스 대비 최적 크기로 리사이징 (가로 86%, 세로 78% 이내 비율 유지)
        max_w = int(canvas_w * max_subject_ratio)
        max_h = int(canvas_h * (max_subject_ratio * 0.90))

        scale = min(max_w / sub_w, max_h / sub_h)
        new_w = max(1, int(sub_w * scale))
        new_h = max(1, int(sub_h * scale))

        resized_subject = cropped_subject.resize((new_w, new_h), Image.Resampling.LANCZOS)

        # 5. 캔버스 중앙 배치 좌표 계산 (바닥 접지를 위해 약간 아래쪽 중심)
        pos_x = (canvas_w - new_w) // 2
        # 바닥에 안정적으로 안착하도록 y축은 중앙에서 3% 정도 아래로 미세 오프셋
        pos_y = (canvas_h - new_h) // 2 + int(canvas_h * 0.03)

        # 6. 투명 PNG 컷아웃 캔버스 생성 (2단계 썸네일 레이어용)
        cutout_canvas = Image.new("RGBA", (canvas_w, canvas_h), (0, 0, 0, 0))

        # 7. 소프트 접지 그림자(Ground Contact Shadow) 생성
        if add_ground_shadow:
            shadow_canvas = Image.new("RGBA", (canvas_w, canvas_h), (0, 0, 0, 0))
            shadow_draw = ImageDraw.Draw(shadow_canvas)

            # 피사체 바닥 너비의 80%, 높이 22~36px 타원 그림자 2중 레이어링
            shadow_w = int(new_w * 0.82)
            shadow_h = max(18, int(new_h * 0.08))
            shadow_x0 = (canvas_w - shadow_w) // 2
            shadow_y0 = pos_y + new_h - int(shadow_h * 0.45)
            shadow_x1 = shadow_x0 + shadow_w
            shadow_y1 = shadow_y0 + shadow_h

            # 깊은 코어 그림자
            shadow_draw.ellipse(
                [shadow_x0 + int(shadow_w * 0.1), shadow_y0, shadow_x1 - int(shadow_w * 0.1), shadow_y1],
                fill=(20, 25, 30, 160)
            )
            # 넓은 앰비언트 그림자
            shadow_draw.ellipse(
                [shadow_x0, shadow_y0 - 4, shadow_x1, shadow_y1 + 4],
                fill=(30, 35, 40, 90)
            )

            # 가우시안 블러로 부드러운 스튜디오 바닥 그림자 완성
            blur_radius = max(8, int(shadow_h * 0.4))
            shadow_canvas = shadow_canvas.filter(ImageFilter.GaussianBlur(blur_radius))

            # 투명 캔버스에 그림자 먼저 합성
            cutout_canvas.paste(shadow_canvas, (0, 0), shadow_canvas)

        # 투명 캔버스에 피사체 합성
        cutout_canvas.paste(resized_subject, (pos_x, pos_y), resized_subject)

        # 8. 순백색(#FFFFFF) 스튜디오 캔버스 생성 및 합성
        studio_white = Image.new("RGBA", (canvas_w, canvas_h), (*bg_color, 255))
        studio_white.paste(cutout_canvas, (0, 0), cutout_canvas)
        studio_white_rgb = studio_white.convert("RGB")

        # 9. 파일 저장
        os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
        studio_white_rgb.save(output_path, "PNG", quality=98)

        # 투명 컷아웃 PNG도 동일 경로에 `_cutout.png`로 저장
        cutout_path = str(Path(output_path).with_name(f"{Path(output_path).stem}_cutout.png"))
        cutout_canvas.save(cutout_path, "PNG")

        return {
            "success": True,
            "studio_img_path": output_path,
            "cutout_img_path": cutout_path,
            "width": canvas_w,
            "height": canvas_h,
            "scale": scale,
        }
    except Exception as e:
        return {"success": False, "error": f"정규화 실패: {str(e)}"}
