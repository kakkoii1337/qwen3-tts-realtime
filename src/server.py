"""
Qwen3-TTS Realtime API Server
==============================
FastAPI service for voice design and real-time speech synthesis using
Alibaba Cloud Qwen3-TTS Voice Design API.

Endpoints:
  POST /voice/design  { "voice_prompt": "...", "preview_text": "...", "language": "en" }
                      -> { "voice": "...", "preview_audio": "..." }
  GET  /voice         -> { "voice": "..." }
  POST /tts           { "text": "...", "language": "en" }
                      -> audio/wav (streaming)
  GET  /health        -> { "status": "ok", "model": "..." }

Usage:
  1. First create a custom voice:
     curl -X POST http://localhost:8000/voice/design \
       -H "Content-Type: application/json" \
       -d '{"voice_prompt": "A young, lively female voice with a fast pace", "preview_text": "Hello everyone.", "language": "en"}'
  
  2. Then synthesize speech:
     curl -X POST http://localhost:8000/tts \
       -H "Content-Type: application/json" \
       -d '{"text": "Hello world!", "language": "en"}' --output audio.wav

  Or run the server:
    python server.py
    # or
    uvicorn server:app --host 0.0.0.0 --port 8000

Notes:
  - Requests are serialised by model_lock.
    Remove the lock if you want concurrent WebSocket sessions.
  - Audio is generated sentence-by-sentence: each sentence opens a commit
    on the same WebSocket connection, waits for response.done, then the
    next sentence is committed — first sentence plays while the next is
    being generated, keeping inter-sentence gaps at natural boundaries.
  - RMS normalisation is applied per-sentence.
"""

import asyncio
import base64
import json
import os
import re
import struct
import time as _time
from contextlib import asynccontextmanager
from typing import AsyncGenerator, Optional

import numpy as np
import requests
import websockets
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
import uvicorn

load_dotenv()

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
API_KEY = os.getenv("DASHSCOPE_API_KEY", "")
WS_BASE_URL = os.getenv(
    "DASHSCOPE_WS_URL",
    "wss://dashscope-intl.aliyuncs.com/api-ws/v1/realtime",
)
HTTP_BASE_URL = os.getenv(
    "DASHSCOPE_HTTP_URL",
    "https://dashscope-intl.aliyuncs.com/api/v1",
)
MODEL_ID = "qwen3-tts-vd-realtime-2026-01-15"
VOICE_DESIGN_MODEL = "qwen-voice-design"
DEFAULT_VOICE = None  # Must be set via voice design
SAMPLE_RATE = 24000  # fixed by API (PCM_24000HZ_MONO_16BIT)
CHUNK_SIZE = 4096  # bytes per HTTP chunk
TARGET_RMS = 0.15  # per-sentence RMS normalisation target

# ---------------------------------------------------------------------------
# Language code mapping
# Maps api.py language strings → Alibaba Cloud language_type values.
# ---------------------------------------------------------------------------
LANG_MAP: dict[str, str] = {
    "English": "en",
    "en": "en",
    "Chinese": "zh",
    "zh": "zh",
    "Japanese": "ja",
    "ja": "ja",
    "Korean": "ko",
    "ko": "ko",
    "French": "fr",
    "fr": "fr",
    "German": "de",
    "de": "de",
    "Spanish": "es",
    "es": "es",
    "Italian": "it",
    "it": "it",
    "Portuguese": "pt",
    "pt": "pt",
    "Russian": "ru",
    "ru": "ru",
}

# ---------------------------------------------------------------------------
# Global state
# ---------------------------------------------------------------------------
model_lock = asyncio.Lock()  # serialise synthesis — mirrors api.py
custom_voice: Optional[str] = None  # Voice created via voice design

# ---------------------------------------------------------------------------
# WAV helpers  (identical to api.py)
# ---------------------------------------------------------------------------


def streaming_wav_header(
    sample_rate: int = SAMPLE_RATE, channels: int = 1, bits: int = 16
) -> bytes:
    """WAV header with 0xFFFFFFFF data size for streaming (length unknown)."""
    byte_rate = sample_rate * channels * bits // 8
    block_align = channels * bits // 8
    return struct.pack(
        "<4sI4s4sIHHIIHH4sI",
        b"RIFF",
        0xFFFFFFFF,
        b"WAVE",
        b"fmt ",
        16,
        1,  # PCM
        channels,
        sample_rate,
        byte_rate,
        block_align,
        bits,
        b"data",
        0xFFFFFFFF,
    )


def to_int16(audio: np.ndarray) -> bytes:
    """Convert float32 [-1, 1] numpy array to int16 PCM bytes."""
    return (np.clip(audio, -1.0, 1.0) * 32767).astype(np.int16).tobytes()


# ---------------------------------------------------------------------------
# Sentence splitting  (identical to api.py)
# ---------------------------------------------------------------------------

_SENT_SPLIT = re.compile(r"(?<=[.!?])\s+")


def _split_sentences(text: str) -> list[str]:
    """Split text at sentence boundaries (.  !  ?) into non-empty chunks."""
    parts = _SENT_SPLIT.split(text.strip())
    return [p.strip() for p in parts if p.strip()]


# ---------------------------------------------------------------------------
# Lifespan
# ---------------------------------------------------------------------------


@asynccontextmanager
async def lifespan(app: FastAPI):
    if not API_KEY:
        print(
            "[startup] WARNING: DASHSCOPE_API_KEY not set in .env — /tts will return 503"
        )
    else:
        print(f"[startup] API key loaded. Model: {MODEL_ID}")
    print("[startup] Ready! Listening on http://0.0.0.0:8000")
    yield
    print("[shutdown] Bye.")


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

app = FastAPI(title="Qwen3-TTS Realtime API", version="1.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------


class VoiceDesignRequest(BaseModel):
    voice_prompt: str
    preview_text: str
    preferred_name: Optional[str] = None
    language: str = "en"


class VoiceDesignResponse(BaseModel):
    voice: str
    preview_audio: str  # base64 encoded audio


class TTSRequest(BaseModel):
    text: str
    language: str = "en"
    speaker: Optional[str] = None
    instruct: Optional[str] = None


# ---------------------------------------------------------------------------
# Audio generator
# ---------------------------------------------------------------------------


async def audio_stream(
    text: str, language: str, voice: Optional[str] = None
) -> AsyncGenerator[bytes, None]:
    """
    Sentence-by-sentence synthesis via the Realtime WebSocket API.

    One WebSocket connection is opened per request.  Each sentence is
    appended and committed sequentially; audio is collected until
    response.done, then RMS-normalised before being yielded to the HTTP
    client.  This mirrors the sentence-by-sentence logic in api.py exactly.
    """
    sentences = _split_sentences(text)
    if not sentences:
        sentences = [text]

    lang_code = LANG_MAP.get(language, "en")
    ws_url = f"{WS_BASE_URL}?model={MODEL_ID}"
    headers = {"Authorization": f"Bearer {API_KEY}"}

    use_voice = voice or custom_voice

    yield streaming_wav_header()

    async with model_lock:
        async with websockets.connect(ws_url, additional_headers=headers) as ws:
            # --- Configure session once for this request ---
            await ws.send(
                json.dumps(
                    {
                        "type": "session.update",
                        "session": {
                            "mode": "commit",
                            "voice": use_voice,
                            "language_type": lang_code,
                            "response_format": "pcm",
                            "sample_rate": SAMPLE_RATE,
                        },
                    }
                )
            )

            # Wait for session.updated confirmation before sending text
            async for raw_msg in ws:
                event = json.loads(raw_msg)
                if event.get("type") in ("session.updated", "session.created"):
                    break
                if event.get("type") == "error":
                    raise RuntimeError(f"Session error: {event}")

            # --- Process sentences one by one ---
            for i, sentence in enumerate(sentences):
                t_start = _time.monotonic()
                first_chunk = True
                pcm_chunks: list[bytes] = []

                # Commit this sentence
                await ws.send(
                    json.dumps(
                        {
                            "type": "input_text_buffer.append",
                            "text": sentence,
                        }
                    )
                )
                await ws.send(json.dumps({"type": "input_text_buffer.commit"}))

                # Collect audio
                async for raw_msg in ws:
                    event = json.loads(raw_msg)
                    etype = event.get("type", "")

                    if etype == "response.audio.delta":
                        chunk = base64.b64decode(event.get("delta", ""))
                        if chunk:
                            if first_chunk:
                                print(
                                    f"[ws] sentence {i + 1} TTFA: "
                                    f"{_time.monotonic() - t_start:.3f}s",
                                    flush=True,
                                )
                                first_chunk = False
                            pcm_chunks.append(chunk)

                    elif etype in ("response.done", "session.finished"):
                        break

                    elif etype == "error":
                        raise RuntimeError(f"API error on sentence {i + 1}: {event}")

                if not pcm_chunks:
                    continue

                # RMS normalise per sentence
                raw = b"".join(pcm_chunks)
                samples = (
                    np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32767.0
                )
                rms = np.sqrt(np.mean(samples**2))
                if rms > 1e-6:
                    samples = samples * (TARGET_RMS / rms)
                normalized = np.clip(samples, -1.0, 1.0) * 32767
                normalized = normalized.astype(np.int16).tobytes()

                print(
                    f"[stream] sentence {i + 1}/{len(sentences)}: "
                    f"{len(sentence)} chars, rms={rms:.4f}",
                    flush=True,
                )

                for j in range(0, len(normalized), CHUNK_SIZE):
                    yield normalized[j : j + CHUNK_SIZE]


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@app.post("/voice/design")
async def design_voice(request: VoiceDesignRequest):
    """Create a custom voice using voice design."""
    if not API_KEY:
        raise HTTPException(status_code=503, detail="DASHSCOPE_API_KEY not configured")

    import uuid

    preferred_name = request.preferred_name or f"voice_{uuid.uuid4().hex[:8]}"

    url = f"{HTTP_BASE_URL}/services/audio/tts/customization"
    headers = {
        "Authorization": f"Bearer {API_KEY}",
        "Content-Type": "application/json",
    }
    data = {
        "model": VOICE_DESIGN_MODEL,
        "input": {
            "action": "create",
            "target_model": MODEL_ID,
            "voice_prompt": request.voice_prompt,
            "preview_text": request.preview_text,
            "preferred_name": preferred_name,
            "language": request.language,
        },
        "parameters": {
            "sample_rate": SAMPLE_RATE,
            "response_format": "wav",
        },
    }

    response = requests.post(url, headers=headers, json=data, timeout=60)
    if response.status_code != 200:
        raise HTTPException(status_code=response.status_code, detail=response.text)

    result = response.json()
    voice_name = result["output"]["voice"]
    preview_audio = result["output"]["preview_audio"]["data"]

    global custom_voice
    custom_voice = voice_name

    return {
        "voice": voice_name,
        "preview_audio": preview_audio,
    }


def create_voice_design(voice_prompt: str, preview_text: str, language: str) -> str:
    """Create a custom voice and return the voice name."""
    url = f"{HTTP_BASE_URL}/services/audio/tts/customization"
    headers = {
        "Authorization": f"Bearer {API_KEY}",
        "Content-Type": "application/json",
    }
    import uuid

    voice_name = f"voice_{uuid.uuid4().hex[:8]}"
    data = {
        "model": VOICE_DESIGN_MODEL,
        "input": {
            "action": "create",
            "target_model": MODEL_ID,
            "voice_prompt": voice_prompt,
            "preview_text": preview_text,
            "preferred_name": voice_name,
            "language": language,
        },
        "parameters": {
            "sample_rate": SAMPLE_RATE,
            "response_format": "wav",
        },
    }

    response = requests.post(url, headers=headers, json=data, timeout=60)
    if response.status_code != 200:
        raise RuntimeError(f"Voice design failed: {response.text}")

    result = response.json()
    return result["output"]["voice"]


@app.post("/tts")
async def tts(request: TTSRequest):
    """Synthesize speech. If instruct is provided, creates a voice design on-the-fly."""
    if not API_KEY:
        raise HTTPException(status_code=503, detail="DASHSCOPE_API_KEY not configured")

    voice = None

    if request.instruct:
        print(f"[tts] Creating voice from instruct: {request.instruct[:50]}...")
        voice = create_voice_design(
            voice_prompt=request.instruct,
            preview_text=request.text[:100] if request.text else "Hello",
            language=LANG_MAP.get(request.language, "en"),
        )
        print(f"[tts] Created voice: {voice}")
        global custom_voice
        custom_voice = voice
    else:
        voice = custom_voice

    if not voice:
        raise HTTPException(
            status_code=400,
            detail="No custom voice set. Call /voice/design first or provide instruct parameter.",
        )

    return StreamingResponse(
        audio_stream(request.text, request.language, voice),
        media_type="audio/wav",
        headers={"Cache-Control": "no-cache"},
    )


@app.get("/voice")
async def get_voice():
    """Get the current custom voice name."""
    return {"voice": custom_voice}


@app.get("/health")
async def health():
    return {
        "status": "ok" if API_KEY else "no_api_key",
        "model": MODEL_ID,
        "voice_design_model": VOICE_DESIGN_MODEL,
    }


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
