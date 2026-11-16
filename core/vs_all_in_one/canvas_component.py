# -*- coding: utf-8 -*-
"""
core.vs_all_in_one.canvas_component
9:16 HTML5 Canvas 실시간 렌더러 및 CLEAN/INFO 듀얼 내보내기 웹 컴포넌트
"""

import json
from typing import Dict, Any


def render_html5_canvas(
    canvas_state: Dict[str, Any],
    base64_a: str = "",
    base64_b: str = "",
    base64_bg: str = "",
    height: int = 700,
) -> str:
    """1080x1920 세로형 캔버스를 360x640 크기로 스케일링하여 브라우저에 실시간 렌더링하고,
    CLEAN.png 및 INFO.png를 1080x1920 무손실 해상도로 즉시 다운로드할 수 있는 완전한 HTML/JS 코드를 반환합니다."""

    state_json = json.dumps(canvas_state, ensure_ascii=False)

    html_code = f"""
    <!DOCTYPE html>
    <html lang="ko">
    <head>
    <meta charset="utf-8">
    <style>
        * {{ box-sizing: border-box; margin: 0; padding: 0; }}
        body {{
            background: #0f172a;
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Malgun Gothic", sans-serif;
            display: flex;
            flex-direction: column;
            align-items: center;
            justify-content: center;
            padding: 8px;
            color: #f8fafc;
        }}
        .canvas-wrapper {{
            position: relative;
            width: 360px;
            height: 640px;
            border-radius: 12px;
            overflow: hidden;
            box-shadow: 0 12px 35px rgba(0, 0, 0, 0.6), 0 0 0 1px rgba(255, 255, 255, 0.1);
            background: #ffffff;
        }}
        #vsCanvas {{
            width: 100%;
            height: 100%;
            display: block;
            cursor: crosshair;
        }}
        .canvas-toolbar {{
            margin-top: 10px;
            display: flex;
            gap: 8px;
            width: 360px;
            justify-content: center;
        }}
        .btn {{
            flex: 1;
            padding: 8px 12px;
            border-radius: 6px;
            font-size: 12px;
            font-weight: 700;
            border: none;
            cursor: pointer;
            transition: all 0.2s ease;
            display: inline-flex;
            align-items: center;
            justify-content: center;
            gap: 4px;
        }}
        .btn-clean {{
            background: linear-gradient(135deg, #059669 0%, #10b981 100%);
            color: white;
            box-shadow: 0 4px 12px rgba(16, 185, 129, 0.3);
        }}
        .btn-info {{
            background: linear-gradient(135deg, #2563eb 0%, #3b82f6 100%);
            color: white;
            box-shadow: 0 4px 12px rgba(37, 99, 235, 0.3);
        }}
        .btn-dual {{
            background: linear-gradient(135deg, #7c3aed 0%, #a855f7 100%);
            color: white;
            box-shadow: 0 4px 12px rgba(124, 58, 237, 0.35);
        }}
        .btn:hover {{
            transform: translateY(-1px);
            filter: brightness(1.1);
        }}
        .badge-live {{
            position: absolute;
            top: 10px;
            left: 10px;
            background: rgba(15, 23, 42, 0.85);
            color: #38bdf8;
            border: 1px solid rgba(56, 189, 248, 0.4);
            border-radius: 20px;
            padding: 2px 8px;
            font-size: 10px;
            font-weight: 700;
            pointer-events: none;
            z-index: 10;
        }}
    </style>
    </head>
    <body>

    <div class="canvas-wrapper">
        <span class="badge-live">📐 9:16 LIVE (1080×1920)</span>
        <!-- 실제 렌더링 해상도는 1080x1920 무손실 -->
        <canvas id="vsCanvas" width="1080" height="1920"></canvas>
    </div>

    <div class="canvas-toolbar">
        <button class="btn btn-clean" onclick="downloadImage(true)" title="텍스트/배지가 없는 순수 피사체 (Start Frame)">
            📥 CLEAN.png
        </button>
        <button class="btn btn-info" onclick="downloadImage(false)" title="스펙 라벨과 VS 배지가 포함된 완성본 (End Frame)">
            📥 INFO.png
        </button>
        <button class="btn btn-dual" onclick="downloadDualImages()" title="두 장을 1초 간격으로 연속 다운로드">
            ⚡ 듀얼 동시 저장
        </button>
    </div>

    <script>
    const canvas = document.getElementById("vsCanvas");
    const ctx = canvas.getContext("2d");

    const state = {state_json};
    const imgAData = "{base64_a}";
    const imgBData = "{base64_b}";
    const imgBgData = "{base64_bg}";

    const loadedImgA = new Image();
    const loadedImgB = new Image();
    const loadedImgBg = new Image();
    let imgALoaded = false;
    let imgBLoaded = false;
    let imgBgLoaded = false;

    if (imgBgData && imgBgData.length > 50) {{
        loadedImgBg.onload = () => {{ imgBgLoaded = true; drawCanvas(false); }};
        loadedImgBg.src = imgBgData;
    }}

    if (imgAData && imgAData.length > 50) {{
        loadedImgA.onload = () => {{ imgALoaded = true; drawCanvas(false); }};
        loadedImgA.src = imgAData;
    }} else {{
        imgALoaded = false;
    }}

    if (imgBData && imgBData.length > 50) {{
        loadedImgB.onload = () => {{ imgBLoaded = true; drawCanvas(false); }};
        loadedImgB.src = imgBData;
    }} else {{
        imgBLoaded = false;
    }}

    function drawCanvas(isCleanMode = false) {{
        ctx.clearRect(0, 0, 1080, 1920);

        if (state.use_facing_bg && imgBgLoaded) {{
            // 제미나이 1:1 맞짱 대치 9:16 통짜 샷을 배경으로 렌더링
            ctx.drawImage(loadedImgBg, 0, 0, 1080, 1920);
        }} else {{
            // 1. 순수 화이트 사이클로라마 스튜디오 배경 렌더링
            ctx.fillStyle = "#ffffff";
            ctx.fillRect(0, 0, 1080, 1920);

            // 미세 스튜디오 그라디언트 림 (상단 옅은 광원 & 하단 콘택트)
            const bgGrad = ctx.createRadialGradient(540, 960, 200, 540, 960, 1100);
            bgGrad.addColorStop(0, "#ffffff");
            bgGrad.addColorStop(0.85, "#f8fafc");
            bgGrad.addColorStop(1, "#f1f5f9");
            ctx.fillStyle = bgGrad;
            ctx.fillRect(0, 0, 1080, 1920);

            // 2. 피사체 A & B 렌더링 (그림자 포함)
            state.layers.forEach(layer => {{
                if (layer.id === "subject_a") {{
                    drawSubject(layer, loadedImgA, imgALoaded, "#38bdf8", "A: " + (layer.name || "Subject A"));
                }} else if (layer.id === "subject_b") {{
                    drawSubject(layer, loadedImgB, imgBLoaded, "#f97316", "B: " + (layer.name || "Subject B"));
                }}
            }});
        }}

        // CLEAN 모드일 때는 텍스트, HUD, VS 배지를 렌더링하지 않고 종료!
        if (isCleanMode) return;

        // 3. 중앙 VS 배지 렌더링
        const vsLayer = state.layers.find(l => l.id === "vs_badge");
        if (vsLayer && vsLayer.visible !== false) {{
            drawVsBadge(vsLayer);
        }}

        // 4. 후킹 헤드라인 타이틀 렌더링
        const titleLayer = state.layers.find(l => l.id === "hook_headline");
        if (titleLayer && titleLayer.visible !== false) {{
            drawHeadline(titleLayer);
        }}

        // 5. 스펙 HUD 태그 렌더링
        state.layers.forEach(layer => {{
            if (layer.type === "spec_hud" && layer.visible !== false) {{
                drawSpecHud(layer);
            }}
        }});
    }}

    function drawSubject(layer, imgObj, isLoaded, accentColor, fallbackText) {{
        ctx.save();
        ctx.translate(layer.x, layer.y);
        ctx.rotate((layer.rotation || 0) * Math.PI / 180);
        const scale = layer.scale || 1.0;
        if (layer.flip_x) {{
            ctx.scale(-1, 1);
        }}

        // 바닥 소프트 콘택트 그림자 (타원형)
        ctx.save();
        ctx.beginPath();
        ctx.ellipse(0, 160 * scale, 340 * scale, 45 * scale, 0, 0, Math.PI * 2);
        ctx.fillStyle = "rgba(0, 0, 0, 0.08)";
        ctx.filter = "blur(18px)";
        ctx.fill();
        ctx.restore();

        if (isLoaded) {{
            const w = imgObj.naturalWidth || 800;
            const h = imgObj.naturalHeight || 600;
            const targetW = 860 * scale;
            const targetH = (targetW / w) * h;
            ctx.drawImage(imgObj, -targetW / 2, -targetH / 2, targetW, targetH);
        }} else {{
            // 이미지가 아직 없을 때의 세련된 와이어프레임 박스
            ctx.fillStyle = "rgba(241, 245, 249, 0.9)";
            ctx.strokeStyle = accentColor;
            ctx.lineWidth = 4;
            const boxW = 820 * scale;
            const boxH = 460 * scale;
            ctx.strokeRect(-boxW / 2, -boxH / 2, boxW, boxH);
            ctx.fillRect(-boxW / 2, -boxH / 2, boxW, boxH);

            ctx.fillStyle = "#1e293b";
            ctx.font = "bold 44px sans-serif";
            ctx.textAlign = "center";
            ctx.textBaseline = "middle";
            ctx.fillText(fallbackText, 0, -20);
            ctx.font = "28px sans-serif";
            ctx.fillStyle = "#64748b";
            ctx.fillText("1단계에서 프레임을 캡처하여 배정하세요", 0, 35);
        }}
        ctx.restore();
    }}

    function drawVsBadge(layer) {{
        ctx.save();
        ctx.translate(layer.x, layer.y);
        const sz = layer.size || 130;

        // 중앙 다크 메탈릭 원형 백플레이트
        ctx.beginPath();
        ctx.arc(0, 0, sz * 0.85, 0, Math.PI * 2);
        ctx.fillStyle = "linear-gradient(135deg, #1e1b4b, #0f172a)";
        ctx.fillStyle = "#0f172a";
        ctx.shadowColor = "rgba(239, 68, 68, 0.6)";
        ctx.shadowBlur = 35;
        ctx.fill();

        // 외곽선 레드 네온 링
        ctx.lineWidth = 8;
        ctx.strokeStyle = "#ef4444";
        ctx.stroke();

        // VS 텍스트
        ctx.shadowColor = "rgba(255, 255, 255, 0.8)";
        ctx.shadowBlur = 10;
        ctx.fillStyle = "#ffffff";
        ctx.font = `italic 900 ${{sz * 0.9}}px sans-serif`;
        ctx.textAlign = "center";
        ctx.textBaseline = "middle";
        ctx.fillText("VS", 0, 2);
        ctx.restore();
    }}

    function drawHeadline(layer) {{
        ctx.save();
        ctx.font = `900 ${{layer.font_size || 76}}px sans-serif`;
        ctx.textAlign = "center";
        ctx.textBaseline = "middle";

        // 두꺼운 블랙 스트로크
        ctx.lineJoin = "round";
        ctx.lineWidth = layer.stroke_width || 12;
        ctx.strokeStyle = layer.stroke_color || "#000000";
        ctx.strokeText(layer.text, layer.x, layer.y);

        // 볼드 옐로우/화이트 채우기
        ctx.fillStyle = layer.color || "#FACC15";
        ctx.fillText(layer.text, layer.x, layer.y);
        ctx.restore();
    }}

    function drawSpecHud(layer) {{
        ctx.save();
        const text = layer.text || "";
        ctx.font = `800 ${{layer.font_size || 36}}px monospace, sans-serif`;
        ctx.textAlign = "center";
        ctx.textBaseline = "middle";

        const textMetrics = ctx.measureText(text);
        const padX = 28;
        const padY = 14;
        const boxW = textMetrics.width + padX * 2;
        const boxH = (layer.font_size || 36) + padY * 2;

        ctx.translate(layer.x, layer.y);

        // 테크니컬 HUD 반투명 배경
        ctx.fillStyle = layer.bg_color || "rgba(15, 23, 42, 0.85)";
        ctx.strokeStyle = layer.border_color || layer.color || "#38bdf8";
        ctx.lineWidth = 3;

        // 챔퍼(사선 깎기) 테크 스타일 박스
        ctx.beginPath();
        const r = 8;
        ctx.roundRect(-boxW / 2, -boxH / 2, boxW, boxH, r);
        ctx.fill();
        ctx.stroke();

        // 텍스트 출력
        ctx.fillStyle = "#ffffff";
        ctx.fillText(text, 0, 1);
        ctx.restore();
    }}

    function downloadImage(isClean) {{
        drawCanvas(isClean);
        const dataUrl = canvas.toDataURL("image/png");
        const a = document.createElement("a");
        a.href = dataUrl;
        a.download = isClean ? "CLEAN.png" : "INFO.png";
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        // 다운로드 후 화면은 정상 INFO 모드로 복원
        setTimeout(() => {{ drawCanvas(false); }}, 100);
    }}

    function downloadDualImages() {{
        downloadImage(true);
        setTimeout(() => {{
            downloadImage(false);
        }}, 600);
    }}

    // 초기 렌더링
    drawCanvas(false);
    </script>
    </body>
    </html>
    """
    return html_code


def export_canvas_to_files(
    canvas_state: Dict[str, Any],
    img_a_path: str = "",
    img_b_path: str = "",
    bg_path: str = "",
    exports_dir: str = "",
) -> Dict[str, str]:
    """1080x1920 해상도로 CLEAN.png 및 INFO.png를 생성하여 지정된 exports 폴더에 직접 저장합니다."""
    import os
    from PIL import Image, ImageDraw, ImageFont

    if not exports_dir:
        return {}
    os.makedirs(exports_dir, exist_ok=True)

    use_facing = canvas_state.get("use_facing_bg", False) and bg_path and os.path.exists(bg_path)

    if use_facing:
        # 제미나이 1:1 맞짱 대치 컷을 배경으로 1080x1920 리사이즈
        with Image.open(bg_path) as b_img:
            clean_img = b_img.convert("RGBA").resize((1080, 1920), Image.Resampling.LANCZOS)
    else:
        # 1. CLEAN 이미지 생성 (1080x1920 순백색 배경)
        clean_img = Image.new("RGBA", (1080, 1920), (255, 255, 255, 255))
        layers = canvas_state.get("layers", [])

        def paste_layer_subject(target_img, layer, img_path):
            if not img_path or not os.path.exists(img_path):
                return
            try:
                with Image.open(img_path) as src:
                    src_rgba = src.convert("RGBA")
                    if layer.get("flip_x", False):
                        src_rgba = src_rgba.transpose(Image.Transpose.FLIP_LEFT_RIGHT)
                    scale = float(layer.get("scale", 1.0))
                    rot = float(layer.get("rotation", 0))
                    orig_w, orig_h = src_rgba.size

                    target_w = int(860 * scale)
                    target_h = int((target_w / max(1, orig_w)) * orig_h)
                    resized = src_rgba.resize((max(10, target_w), max(10, target_h)), Image.Resampling.LANCZOS)

                    if rot != 0:
                        resized = resized.rotate(rot, expand=True, resample=Image.Resampling.BICUBIC)

                    rw, rh = resized.size
                    center_x = int(layer.get("x", 540))
                    center_y = int(layer.get("y", 960))
                    px = center_x - rw // 2
                    py = center_y - rh // 2

                    target_img.paste(resized, (px, py), resized)
            except Exception as e:
                print(f"[export_canvas_to_files] paste error: {e}")

        # CLEAN 캔버스에 A, B 피사체 합성
        for l in layers:
            if l.get("id") == "subject_a":
                paste_layer_subject(clean_img, l, img_a_path)
            elif l.get("id") == "subject_b":
                paste_layer_subject(clean_img, l, img_b_path)

    clean_file = os.path.join(exports_dir, "CLEAN.png")
    clean_img.save(clean_file, format="PNG")

    # 2. INFO 이미지 생성 (CLEAN 복사본 위에 VS 배지, 타이틀, HUD 드로잉)
    info_img = clean_img.copy()
    draw_info = ImageDraw.Draw(info_img)
    layers = canvas_state.get("layers", [])

    font_bold = "C:/Windows/Fonts/malgunbd.ttf"
    font_regular = "C:/Windows/Fonts/malgun.ttf"

    def get_font(size: int, bold: bool = True):
        path = font_bold if bold and os.path.exists(font_bold) else (font_regular if os.path.exists(font_regular) else None)
        if path:
            return ImageFont.truetype(path, size)
        return ImageFont.load_default()

    # 중앙 VS 배지
    vs_layer = next((l for l in layers if l.get("id") == "vs_badge" and l.get("visible") != False), None)
    if vs_layer:
        vx = int(vs_layer.get("x", 540))
        vy = int(vs_layer.get("y", 960))
        sz = int(vs_layer.get("size", 130))
        r = int(sz * 0.85)
        # 배지 원형
        draw_info.ellipse([vx - r, vy - r, vx + r, vy + r], fill=(15, 23, 42, 255), outline=(239, 68, 68, 255), width=8)
        # VS 텍스트
        vs_f = get_font(int(sz * 0.8), bold=True)
        draw_info.text((vx, vy), "VS", fill=(255, 255, 255, 255), font=vs_f, anchor="mm")

    # 헤드라인 타이틀
    title_layer = next((l for l in layers if l.get("id") == "hook_headline" and l.get("visible") != False), None)
    if title_layer:
        tx = int(title_layer.get("x", 540))
        ty = int(title_layer.get("y", 220))
        t_text = title_layer.get("text", "")
        f_sz = int(title_layer.get("font_size", 76))
        t_f = get_font(f_sz, bold=True)
        # 검은 외곽선 드로잉
        stroke_w = int(title_layer.get("stroke_width", 10))
        for dx in range(-stroke_w, stroke_w + 1):
            for dy in range(-stroke_w, stroke_w + 1):
                if dx * dx + dy * dy <= stroke_w * stroke_w:
                    draw_info.text((tx + dx, ty + dy), t_text, fill=(0, 0, 0, 255), font=t_f, anchor="mm")
        # 메인 텍스트 (옐로우)
        draw_info.text((tx, ty), t_text, fill=(250, 204, 21, 255), font=t_f, anchor="mm")

    # 스펙 HUD
    for l in layers:
        if l.get("type") == "spec_hud" and l.get("visible") != False:
            hx = int(l.get("x", 540))
            hy = int(l.get("y", 500))
            htext = l.get("text", "")
            hf_sz = int(l.get("font_size", 36))
            hud_font = get_font(hf_sz, bold=True)
            bbox = draw_info.textbbox((hx, hy), htext, font=hud_font, anchor="mm")
            pad_x = 24
            pad_y = 12
            box = [bbox[0] - pad_x, bbox[1] - pad_y, bbox[2] + pad_x, bbox[3] + pad_y]
            draw_info.rounded_rectangle(box, radius=8, fill=(15, 23, 42, 230), outline=(56, 189, 248, 255), width=3)
            draw_info.text((hx, hy), htext, fill=(255, 255, 255, 255), font=hud_font, anchor="mm")

    info_file = os.path.join(exports_dir, "INFO.png")
    info_img.save(info_file, format="PNG")

    return {"clean_path": clean_file, "info_path": info_file}

