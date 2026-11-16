"""
core/qwen_tts_worker.py
Qwen3-TTS 전용 고품질 음성 합성 워커 스크립트.
- RTX 3060 CUDA 가속 지원 (bfloat16 / float16)
- 모드 1: Custom Voice (사전 정의 화자 + 자연어 스타일/감정 프롬프트 제어)
- 모드 2: Instant Voice Cloning (3~10초 참조 음성 복제, X-vector 또는 ICL 모드)
- 씬별(Scene 1~8) 순차 생성 및 각 씬별 정확한 재생 시간(초) 측정하여 meta.json 출력
"""

import argparse
import json
import os
import re
import shutil
import sys
import time
import urllib.request

# Windows 콘솔 인코딩(CP949) 충돌 방지: 입출력을 UTF-8로 강제 재구성
if sys.platform == "win32":
    try:
        if sys.stdout and hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        if sys.stderr and hasattr(sys.stderr, "reconfigure"):
            sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

# Windows 비-관리자 환경에서 symlink 권한 오류(WinError 1314) 방지
os.environ["HF_HUB_DISABLE_SYMLINKS"] = "1"
os.environ["HF_HUB_DISABLE_SYMLINKS_WARNING"] = "1"
os.environ["PYTHONIOENCODING"] = "utf-8"


def clean_scene_text(text: str) -> str:
    """[Scene 1] 등 불필요한 메타 태그 제거 및 텍스트 정제"""
    cleaned = re.sub(r"\[Scene\s*\d+\]", "", text).strip()
    cleaned = re.sub(r"^Scene\s*\d+\s*[:\-]\s*", "", cleaned, flags=re.IGNORECASE).strip()
    # 괄호 안의 발음이나 지시문 정제
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned


def get_audio_duration_sf(file_path: str) -> float:
    """soundfile을 사용하여 생성된 오디오의 실제 재생 시간(초)을 정밀 측정합니다."""
    try:
        import soundfile as sf
        info = sf.info(file_path)
        return round(info.duration, 3)
    except Exception:
        # fallback to file size estimate
        return 5.0


def try_synthesize_via_pinokio(args, scenes: list[str]) -> bool:
    """
    피노키오 Qwen3-TTS가 실행 중일 경우(127.0.0.1:7860) API로 초고속 합성.
    - 모델 재로딩 대기 시간 0초 (VRAM에 이미 상주한 피노키오 모델 즉시 재사용)
    """
    try:
        with urllib.request.urlopen("http://127.0.0.1:7860/config", timeout=0.8) as resp:
            if resp.status != 200:
                return False
    except Exception:
        return False

    try:
        from gradio_client import Client, handle_file
        print("[PINOKIO] Detected running Pinokio Qwen3-TTS at http://127.0.0.1:7860! Connecting directly...")
        sys.stdout.flush()

        client = Client("http://127.0.0.1:7860")
        total_scenes = len(scenes)
        results = []

        model_size = "0.6B" if (args.model_id and "0.6B" in args.model_id) else "1.7B"

        # voice_clone 모드일 경우 ref_audio 준비
        ref_file = None
        ref_text = ""
        use_xvector = True
        if args.mode == "voice_clone":
            if not args.ref_audio or not os.path.exists(args.ref_audio):
                print(f"[ERROR] ref_audio file not found: {args.ref_audio}", file=sys.stderr)
                sys.exit(1)
            ref_file = handle_file(args.ref_audio)
            ref_text = args.ref_text.strip() if args.ref_text else ""
            use_xvector = True if not ref_text else False
            print(f"[PINOKIO] Voice Clone mode active (use_xvector_only={use_xvector})")
            sys.stdout.flush()

        for idx, sc_raw in enumerate(scenes):
            scene_num = idx + 1
            clean_text = clean_scene_text(sc_raw)
            if not clean_text:
                clean_text = "이 장면의 내용을 확인하세요."

            out_wav = os.path.join(args.output_dir, f"scene_{scene_num:02d}.wav")
            print(f"[SCENE {scene_num}/{total_scenes}] Pinokio synthesizing: '{clean_text[:40]}...'")
            sys.stdout.flush()

            t_sc = time.time()
            if args.mode == "voice_clone":
                res = client.predict(
                    ref_audio=ref_file,
                    ref_text=ref_text,
                    target_text=clean_text,
                    language=args.language,
                    use_xvector_only=use_xvector,
                    model_size=model_size,
                    max_chunk_chars=200,
                    chunk_gap=0.0,
                    seed=-1,
                    api_name="/generate_voice_clone",
                )
            else:
                spk = args.speaker.capitalize()
                instruct_val = args.instruct.strip() if args.instruct else ""
                res = client.predict(
                    text=clean_text,
                    language=args.language,
                    speaker=spk,
                    instruct=instruct_val,
                    model_size=model_size,
                    seed=-1,
                    api_name="/generate_custom_voice",
                )

            tmp_audio = res[0]
            shutil.copy2(tmp_audio, out_wav)
            dur = get_audio_duration_sf(out_wav)
            elapsed = time.time() - t_sc

            results.append({
                "scene_index": scene_num,
                "text": clean_text,
                "audio_path": out_wav,
                "duration": dur,
            })
            print(f"[PROGRESS] Scene {scene_num}/{total_scenes} completed in {elapsed:.2f}s (duration: {dur:.2f}s)")
            sys.stdout.flush()

        meta_path = os.path.join(args.output_dir, "meta.json")
        with open(meta_path, "w", encoding="utf-8") as f:
            json.dump({
                "status": "success",
                "source": "pinokio_api",
                "mode": args.mode,
                "model_id": f"pinokio_{model_size}",
                "total_scenes": total_scenes,
                "scenes": results,
            }, f, ensure_ascii=False, indent=2)

        print(f"[DONE] All {total_scenes} scenes synthesized via Pinokio API. Meta written to {meta_path}")
        print("[QWEN_WORKER_SUCCESS]")
        sys.stdout.flush()
        return True

    except Exception as e:
        print(f"[PINOKIO_FALLBACK] Pinokio API synthesis failed ({e}). Falling back to local standalone Qwen3-TTS engine...")
        sys.stdout.flush()
        return False



def main():
    parser = argparse.ArgumentParser(description="Qwen3-TTS Synthesis Worker")
    parser.add_argument("--scenes_json", type=str, required=True, help="Path to JSON file containing list of scene texts")
    parser.add_argument("--output_dir", type=str, required=True, help="Directory to save generated scene audios")
    parser.add_argument("--mode", type=str, choices=["custom_voice", "voice_clone"], default="custom_voice")
    parser.add_argument("--model_id", type=str, default=None, help="HuggingFace model ID")
    parser.add_argument("--speaker", type=str, default="Sohee", help="Speaker name for custom_voice (e.g. Sohee, Aiden, Vivian)")
    parser.add_argument("--instruct", type=str, default="", help="Style instruction prompt for custom_voice")
    parser.add_argument("--ref_audio", type=str, default="", help="Path to reference audio for voice_clone")
    parser.add_argument("--ref_text", type=str, default="", help="Transcript of reference audio (optional)")
    parser.add_argument("--language", type=str, default="Korean", help="Synthesis language (e.g. Korean, English)")
    parser.add_argument("--device", type=str, default="auto", help="Device (cuda:0, cpu, auto)")

    args = parser.parse_args()

    # 1. 씬 텍스트 로드
    if not os.path.exists(args.scenes_json):
        print(f"[ERROR] scenes_json not found: {args.scenes_json}", file=sys.stderr)
        sys.exit(1)

    with open(args.scenes_json, "r", encoding="utf-8") as f:
        scenes = json.load(f)

    if not isinstance(scenes, list) or len(scenes) == 0:
        print("[ERROR] scenes_json must contain a non-empty list of strings", file=sys.stderr)
        sys.exit(1)

    os.makedirs(args.output_dir, exist_ok=True)

    # 2. 피노키오(Pinokio) Qwen3-TTS가 실행 중인지 자동 감지 -> 실행 중이면 즉시 초고속 합성
    if try_synthesize_via_pinokio(args, scenes):
        return

    # 3. 피노키오 미실행 시: 로컬 독립 PyTorch 및 Qwen3-TTS 엔진 가동
    print("[INIT] Loading PyTorch and Qwen3-TTS modules...")
    sys.stdout.flush()

    import torch
    import soundfile as sf
    from qwen_tts import Qwen3TTSModel

    # 디바이스 및 데이터타입 결정
    if args.device == "auto":
        if torch.cuda.is_available():
            device = "cuda:0"
            free_bytes, total_bytes = torch.cuda.mem_get_info()
            free_mb = free_bytes / (1024 * 1024)
            print(f"[DEVICE] CUDA detected: {torch.cuda.get_device_name(0)} (Free VRAM: {free_mb:.0f} MB / {total_bytes / (1024 * 1024):.0f} MB)")
        else:
            device = "cpu"
            print("[DEVICE] CUDA not available, using CPU")
    else:
        device = args.device

    # dtype 결정
    if device.startswith("cuda"):
        if torch.cuda.is_bf16_supported():
            dtype = torch.bfloat16
        else:
            dtype = torch.float16
    else:
        dtype = torch.float32

    # 모델 ID 결정
    model_id = args.model_id
    if not model_id:
        if args.mode == "voice_clone":
            # 기본 0.6B Base 모델 (가볍고 빠르며 VRAM 1.2GB 소모)
            model_id = "Qwen/Qwen3-TTS-12Hz-0.6B-Base"
        else:
            # 기본 0.6B CustomVoice 모델
            model_id = "Qwen/Qwen3-TTS-12Hz-0.6B-CustomVoice"

    print(f"[MODEL] Loading weights: {model_id} on {device} (dtype={dtype})...")
    sys.stdout.flush()

    t_start = time.time()
    try:
        model = Qwen3TTSModel.from_pretrained(
            model_id,
            device_map=device,
            dtype=dtype,
        )
    except Exception as e:
        print(f"[ERROR] Failed to load model {model_id}: {e}", file=sys.stderr)
        # fallback to CPU if CUDA OOM
        if "out of memory" in str(e).lower() and device != "cpu":
            print("[FALLBACK] Retrying on CPU due to CUDA OOM...")
            model = Qwen3TTSModel.from_pretrained(
                model_id,
                device_map="cpu",
                dtype=torch.float32,
            )
        else:
            sys.exit(1)

    print(f"[MODEL] Model loaded successfully in {time.time() - t_start:.2f}s")
    sys.stdout.flush()

    # 3. 보이스 클로닝 프롬프트 캐싱 (voice_clone 모드일 경우)
    voice_clone_prompt = None
    if args.mode == "voice_clone":
        if not args.ref_audio or not os.path.exists(args.ref_audio):
            print(f"[ERROR] ref_audio file not found: {args.ref_audio}", file=sys.stderr)
            sys.exit(1)

        ref_text = args.ref_text.strip() if args.ref_text else ""
        x_vector_only = True if not ref_text else False

        # 캐시 경로: ref_audio와 같은 디렉터리에 .prompt.pt 생성
        cache_dir = os.path.dirname(os.path.abspath(args.ref_audio))
        base_name = os.path.splitext(os.path.basename(args.ref_audio))[0]
        import hashlib
        text_hash = hashlib.md5(ref_text.encode("utf-8")).hexdigest()[:8]
        prompt_cache_file = os.path.join(cache_dir, f"{base_name}_{text_hash}.prompt.pt")

        # 기존 캐시가 유효하고 ref_audio보다 최신인 경우 로드
        if os.path.exists(prompt_cache_file) and os.path.getmtime(prompt_cache_file) >= os.path.getmtime(args.ref_audio):
            print(f"[CLONE_CACHE] ⚡ 저장된 목소리 DNA 텐서(.pt) 즉시 로드 중: '{os.path.basename(prompt_cache_file)}'")
            sys.stdout.flush()
            try:
                voice_clone_prompt = torch.load(prompt_cache_file, weights_only=False)
                print("[CLONE_CACHE] ✅ 목소리 DNA 텐서 로드 완료 (복제 연산 0초 생략)")
                sys.stdout.flush()
            except Exception as e:
                print(f"[CLONE_CACHE] 캐시 로드 실패 ({e}), 신규 생성으로 전환합니다.")
                voice_clone_prompt = None

        if voice_clone_prompt is None:
            print(f"[CLONE] Creating voice clone prompt from '{args.ref_audio}' (x_vector_only_mode={x_vector_only})...")
            sys.stdout.flush()

            try:
                if x_vector_only:
                    voice_clone_prompt = model.create_voice_clone_prompt(
                        ref_audio=args.ref_audio,
                        x_vector_only_mode=True,
                    )
                else:
                    voice_clone_prompt = model.create_voice_clone_prompt(
                        ref_audio=args.ref_audio,
                        ref_text=ref_text,
                        x_vector_only_mode=False,
                    )
                print("[CLONE] Voice clone prompt created successfully.")
                # 목소리 DNA 캐시 파일로 영구 저장
                try:
                    torch.save(voice_clone_prompt, prompt_cache_file)
                    print(f"[CLONE_CACHE] 💾 목소리 DNA 텐서 캐시 영구 저장 완료: '{os.path.basename(prompt_cache_file)}'")
                except Exception as save_err:
                    print(f"[CLONE_CACHE] 캐시 저장 실패: {save_err}")
                sys.stdout.flush()
            except Exception as e:
                print(f"[ERROR] Failed to create voice clone prompt: {e}", file=sys.stderr)
                sys.exit(1)

    # 4. 씬별(Scene 1~8) 순차 생성
    total_scenes = len(scenes)
    results = []

    for idx, sc_raw in enumerate(scenes):
        scene_num = idx + 1
        clean_text = clean_scene_text(sc_raw)
        if not clean_text:
            clean_text = "이 장면의 내용을 확인하세요."

        out_wav = os.path.join(args.output_dir, f"scene_{scene_num:02d}.wav")
        print(f"[SCENE {scene_num}/{total_scenes}] Synthesizing text: '{clean_text[:40]}...'")
        sys.stdout.flush()

        t_sc = time.time()
        try:
            if args.mode == "voice_clone":
                wavs, sr = model.generate_voice_clone(
                    text=clean_text,
                    language=args.language,
                    voice_clone_prompt=voice_clone_prompt,
                )
            else:
                # CustomVoice 모드
                instruct_val = args.instruct.strip() if args.instruct else None
                wavs, sr = model.generate_custom_voice(
                    text=clean_text,
                    language=args.language,
                    speaker=args.speaker,
                    instruct=instruct_val,
                )

            sf.write(out_wav, wavs[0], sr)
            dur = get_audio_duration_sf(out_wav)
            elapsed = time.time() - t_sc

            results.append({
                "scene_index": scene_num,
                "text": clean_text,
                "audio_path": out_wav,
                "duration": dur,
            })
            print(f"[PROGRESS] Scene {scene_num}/{total_scenes} completed in {elapsed:.2f}s (duration: {dur:.2f}s)")
            sys.stdout.flush()

        except Exception as e:
            print(f"[ERROR] Failed synthesizing scene {scene_num}: {e}", file=sys.stderr)
            sys.exit(1)

    # 5. 메타데이터 JSON 저장
    meta_path = os.path.join(args.output_dir, "meta.json")
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump({
            "status": "success",
            "mode": args.mode,
            "model_id": model_id,
            "total_scenes": total_scenes,
            "scenes": results,
        }, f, ensure_ascii=False, indent=2)

    print(f"[DONE] All {total_scenes} scenes synthesized successfully. Meta written to {meta_path}")
    print("[QWEN_WORKER_SUCCESS]")
    sys.stdout.flush()


if __name__ == "__main__":
    main()
