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

A FastAPI server that mirrors **[qwen3-tts-api](https://github.com/kakkoii1337/qwen3-tts-api)** exactly in its HTTP interface, but replaces the local Qwen3-TTS model with the **Alibaba Cloud Qwen3-TTS Realtime WebSocket API** — no GPU required, no model download.

- **Upstream model:** [Qwen3-TTS Realtime (Alibaba Cloud)](https://www.alibabacloud.com/help/en/model-studio/qwen-tts-realtime)
- **Paper:** [Qwen3-TTS Technical Report](https://huggingface.co/papers/2601.15621)
- **Related repo (local GPU):** [qwen3-tts-api](https://github.com/kakkoii1337/qwen3-tts-api)

---

## How it differs from qwen3-tts-api

| | qwen3-tts-api | qwen3-tts-realtime |
|---|---|---|
| **Model execution** | Local GPU (CUDA) | Alibaba Cloud WebSocket API |
| **Model download** | ~3–4 GB on first run | None |
| **GPU required** | Yes (CUDA 12.4) | No |
| **HTTP interface** | `POST /tts`, `GET /health` | Identical |
| **Streaming** | `stream_generate_pcm` → HTTP WAV | WebSocket `response.audio.delta` → HTTP WAV |
| **Sentence splitting** | Per-sentence commit | Per-sentence WebSocket commit |
| **RMS normalisation** | Yes | Yes (identical) |
| **Test scripts** | `test/speak.ps1` etc. | **Same files, unchanged** |

---

## Repository Layout

```
qwen3-tts-realtime/
├── src/
│   └── server.py      FastAPI server (entry point)
├── test/
│   ├── speak.ps1               PowerShell CLI client (identical to qwen3-tts-api)
│   ├── test_custom_voice.ps1   Shakespeare demo — named speakers
│   └── test_voice_design.ps1   Shakespeare demo — instruct only
├── .env                        API key (not committed)
├── .env.example                Template for .env
└── README.md
```

---

## Prerequisites

| Tool | Purpose | Install |
|---|---|---|
| **uv** | Python package manager | `winget install astral-sh.uv` |
| **ffmpeg** (includes ffplay) | Audio playback / file conversion | `winget install Gyan.FFmpeg` |
| **Alibaba Cloud account** | DashScope API key | [Singapore console](https://dashscope-intl.console.aliyun.com/) |

> No CUDA, no local model weights — the cloud API handles everything.

---

## Setup

### Step 1 — API Key

Copy `.env.example` to `.env` and insert your DashScope API key:

```bash
cp .env.example .env
# edit .env: DASHSCOPE_API_KEY=sk-...
```

### Step 2 — Python Environment

```bash
# Create venv
uv venv

# Activate (Git Bash)
source .venv/Scripts/activate

# Install dependencies
uv pip install fastapi uvicorn[standard] pydantic websockets python-dotenv numpy
```

### Step 3 — Run the Server

```bash
python src/server.py
# or
uvicorn server:app --host 0.0.0.0 --port 8000 --app-dir src
```

---

## API Reference

Identical to qwen3-tts-api:

| Method | Path | Body | Response |
|---|---|---|---|
| `POST` | `/tts` | `{"text": "...", "language": "English", "speaker": "Aiden", "instruct": "..."}` | `audio/wav` |
| `GET` | `/health` | — | `{"status": "ok", "model": "..."}` |

- `speaker` is resolved through `SPEAKER_MAP` in `server.py` to an Alibaba Cloud voice name
- `instruct` maps to the WebSocket session `instructions` field
- `language` maps to the `language_type` field (`English` → `en`, etc.)

### Example (curl)

```bash
curl -X POST http://localhost:8000/tts \
  -H "Content-Type: application/json" \
  -d '{"text": "Hello, world!", "instruct": "speak warmly and clearly"}' \
  --output output.wav
```

---

## CLI Client (`test/speak.ps1`)

With the server running, use `speak.ps1` from **PowerShell** — identical to qwen3-tts-api:

```powershell
# Play immediately
.\test\speak.ps1 "Hello, world!"
.\test\speak.ps1 "Hello, world!" -Instruct "speak with excitement and energy"

# Save to file
.\test\speak.ps1 "Hello, world!" -n output.mp3
```

---

## Speaker Mapping

The `SPEAKER_MAP` table in `src/server.py` translates qwen3-tts-api speaker names to Alibaba Cloud preset voice names:

```python
SPEAKER_MAP = {
    "Aiden":    "Ethan",
    "Ryan":     "Ethan",
    "Dylan":    "Dylan",
    "Vivian":   "Serena",
    "Serena":   "Serena",
    "Sohee":    "Cherry",
    ...
}
```

Update this table to your preferred pairings. If a speaker name is not in the map, `DEFAULT_SPEAKER` (`Cherry`) is used.

---

## Architecture: WebSocket Bridge

Each `POST /tts` request:

1. Opens one WebSocket to `wss://dashscope-intl.aliyuncs.com/api-ws/v1/realtime?model=qwen3-tts-instruct-flash-realtime`
2. Sends `session.update` (voice, language, instruct)
3. For each sentence (split at `.`, `!`, `?`):
   - Sends `input_text_buffer.append` + `input_text_buffer.commit`
   - Collects `response.audio.delta` chunks until `response.done`
   - RMS-normalises the sentence PCM
   - Yields PCM to the HTTP streaming response
4. Closes WebSocket

This exactly mirrors the sentence-by-sentence `stream_generate_pcm` loop in `qwen3-tts-api/src/api.py`.

---

## Environment Variables

| Variable | Required | Description |
|---|---|---|
| `DASHSCOPE_API_KEY` | **Yes** | DashScope API key |
| `DASHSCOPE_WS_URL` | No | Override WebSocket endpoint (default: Singapore region) |

**Beijing region** (if your key is from the mainland console):
```env
DASHSCOPE_WS_URL=wss://dashscope.aliyuncs.com/api-ws/v1/realtime
```

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
