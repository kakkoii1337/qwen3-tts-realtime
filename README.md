---
license: apache-2.0
pipeline_tag: text-to-speech
tags:
    - audio
    - tts
    - speech
    - streaming
    - realtime
---

---

# qwen3-tts-realtime

A real-time streaming TTS server using the **Qwen3-TTS base model**, delivering low-latency audio with time-to-first-audio (TTFA) of ~822 ms — compared to ~12,000 ms for the VoiceDesign model.

- **Upstream model:** [Qwen/Qwen3-TTS](https://huggingface.co/Qwen/Qwen3-TTS)
- **Paper:** [Qwen3-TTS Technical Report](https://huggingface.co/papers/2601.15621)
- **Official GitHub:** [QwenLM/Qwen3-TTS](https://github.com/QwenLM/Qwen3-TTS)
- **Related repo (VoiceDesign / non-streaming):** [qwen3-tts-api](https://github.com/kakkoii1337/qwen3-tts-api)

---

## Why realtime?

| Config                                | RTF   | TTFA        |
| ------------------------------------- | ----- | ----------- |
| VoiceDesign (qwen3-tts-api), no flash-attn | ~2.4  | ~12,280 ms |
| VoiceDesign (qwen3-tts-api), flash-attn    | ~2.1  | ~12,280 ms |
| **Base model streaming (this repo)**  | ~2.49 | **~822 ms** |

The base model streams audio chunks as they are generated, giving near-instant first audio. The trade-off vs VoiceDesign: no natural language emotion/style control via `instruct`.

> RTF > 1.0 means slower than real-time. `torch.compile` (which can push TTFA to ~208 ms) requires Triton — Linux only, not available on Windows.

---

## Prerequisites

| Tool                           | Purpose                          | Install                                                                                                                        |
| ------------------------------ | -------------------------------- | ------------------------------------------------------------------------------------------------------------------------------ |
| **uv**                         | Python package manager           | `winget install astral-sh.uv`                                                                                                  |
| **ffmpeg** (includes ffplay)   | Audio playback / file conversion | `winget install Gyan.FFmpeg`                                                                                                   |
| **CUDA Toolkit 12.4**          | GPU acceleration                 | [NVIDIA CUDA 12.4 download](https://developer.nvidia.com/cuda-12-4-1-download-archive) → Windows → x86_64 → 11 → exe (local)   |

> After installing ffmpeg, open a **new terminal** for it to appear on PATH.

---

## Setup

### Step 1 — Python Environment

```bash
# Create venv
uv venv

# Activate (Git Bash)
source .venv/Scripts/activate

# Install core packages
uv pip install fastapi uvicorn[standard] pydantic qwen-tts numpy

# Reinstall torch with CUDA 12.4 (qwen-tts pulls in a CPU-only build by default)
uv pip install torch torchaudio --index-url https://download.pytorch.org/whl/cu124 --reinstall
```

> **Why cu124?** The `cu121` index has no Python 3.13 wheels for Windows. Always use `cu124`.

### Step 2 — Configuration

Copy `.env.example` to `.env` and fill in any required values:

```bash
cp .env.example .env
```

### Step 3 — Run the Server

```bash
python src/server.py
# or
uvicorn server:app --host 0.0.0.0 --port 8000 --app-dir src
```

On first start the server downloads the Qwen3-TTS base model to the HuggingFace cache (~3–4 GB, cached after first run).

---

## Gotchas

- **Python 3.13 + CUDA on Windows**: always use `cu124` index, never `cu121`
- `torch.compile` (Triton) is Linux-only
- After any install that touches torch, reinstall with `--reinstall --index-url .../cu124`

---

## Citation

```bibtex
@article{Qwen3-TTS,
  title={Qwen3-TTS Technical Report},
  author={Hangrui Hu and Xinfa Zhu and Ting He and Dake Guo and Bin Zhang and Xiong Wang and Zhifang Guo and Ziyue Jiang and Hongkun Hao and Zishan Guo and Xinyu Zhang and Pei Zhang and Baosong Yang and Jin Xu and Jingren Zhou and Junyang Lin},
  journal={arXiv preprint arXiv:2601.15621},
  year={2026}
}
```
