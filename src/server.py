"""
Qwen3-TTS Realtime API Server
==============================
FastAPI service that mirrors qwen3-tts-api/src/api.py in interface and logic,
but replaces local Qwen3TTSModel calls with the Alibaba Cloud Qwen3-TTS
Realtime WebSocket API.

Endpoints:
  POST /tts     { "text": "...", "language": "English", "speaker": "Aiden", "instruct": "..." }
                -> audio/wav  (streaming)
  GET  /health  -> { "status": "ok", "model": "..." }

Usage:
  python server.py
  # or
  uvicorn server:app --host 0.0.0.0 --port 8000

Notes:
  - speaker is resolved through SPEAKER_MAP to an Alibaba Cloud voice name.
  - instruct maps to the session `instructions` field (instruct model only).
  - Requests are serialised by model_lock, mirroring api.py behaviour.
    Remove the lock if you want concurrent WebSocket sessions.
  - Audio is generated sentence-by-sentence: each sentence opens a commit
    on the same WebSocket connection, waits for response.done, then the
    next sentence is committed — first sentence plays while the next is
    being generated, keeping inter-sentence gaps at natural boundaries.
  - RMS normalisation is applied per-sentence, identical to api.py.

Available Alibaba Cloud voices (preset):
  Cherry, Ethan, Serena, Dylan, ...
  Update SPEAKER_MAP below to match your preferred pairings.
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
API_KEY     = os.getenv("DASHSCOPE_API_KEY", "")
WS_BASE_URL = os.getenv(
    "DASHSCOPE_WS_URL",
    "wss://dashscope-intl.aliyuncs.com/api-ws/v1/realtime",
)
MODEL_ID         = "qwen3-tts-instruct-flash-realtime"
DEFAULT_SPEAKER  = "Cherry"
DEFAULT_INSTRUCT = "A clear, neutral, professional voice"
SAMPLE_RATE      = 24000       # fixed by API (PCM_24000HZ_MONO_16BIT)
CHUNK_SIZE       = 4096        # bytes per HTTP chunk
TARGET_RMS       = 0.15        # per-sentence RMS normalisation target

# ---------------------------------------------------------------------------
# Speaker mapping
# Maps qwen3-tts-api named speakers → Alibaba Cloud preset voice names.
# Update this table to match your preferred voice pairings.
# Run  GET /voices  (future) or consult Alibaba Cloud docs for the full list.
# ---------------------------------------------------------------------------
SPEAKER_MAP: dict[str, str] = {
    # English
    "Aiden":    "Ethan",
    "Ryan":     "Ethan",
    # Chinese
    "Dylan":    "Dylan",
    "Eric":     "Ethan",
    "Vivian":   "Serena",
    "Serena":   "Serena",
    "Uncle_Fu": "Dylan",
    # Japanese
    "Ono_Anna": "Cherry",
    # Korean
    "Sohee":    "Cherry",
}

# ---------------------------------------------------------------------------
# Language code mapping
# Maps api.py language strings → Alibaba Cloud language_type values.
# ---------------------------------------------------------------------------
LANG_MAP: dict[str, str] = {
    "English":    "en",
    "Chinese":    "zh",
    "Japanese":   "ja",
    "Korean":     "ko",
    "French":     "fr",
    "German":     "de",
    "Spanish":    "es",
    "Italian":    "it",
    "Portuguese": "pt",
    "Russian":    "ru",
    "Auto":       "Auto",
}

# ---------------------------------------------------------------------------
# Global state
# ---------------------------------------------------------------------------
model_lock = asyncio.Lock()   # serialise synthesis — mirrors api.py

# ---------------------------------------------------------------------------
# WAV helpers  (identical to api.py)
# ---------------------------------------------------------------------------


def streaming_wav_header(
    sample_rate: int = SAMPLE_RATE, channels: int = 1, bits: int = 16
) -> bytes:
    """WAV header with 0xFFFFFFFF data size for streaming (length unknown)."""
    byte_rate   = sample_rate * channels * bits // 8
    block_align = channels * bits // 8
    return struct.pack(
        "<4sI4s4sIHHIIHH4sI",
        b"RIFF", 0xFFFFFFFF,
        b"WAVE",
        b"fmt ", 16,
        1,           # PCM
        channels,
        sample_rate,
        byte_rate,
        block_align,
        bits,
        b"data", 0xFFFFFFFF,
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
        print("[startup] WARNING: DASHSCOPE_API_KEY not set in .env — /tts will return 503")
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
# Schema  (identical to api.py)
# ---------------------------------------------------------------------------


class TTSRequest(BaseModel):
    text: str
    language: str = "English"
    speaker: Optional[str] = None
    instruct: Optional[str] = None


# ---------------------------------------------------------------------------
# Audio generator
# ---------------------------------------------------------------------------


async def audio_stream(
    text: str, language: str, voice: str, instruct: str
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
    ws_url    = f"{WS_BASE_URL}?model={MODEL_ID}"
    headers   = {"Authorization": f"Bearer {API_KEY}"}

    yield streaming_wav_header()

    async with model_lock:
        async with websockets.connect(ws_url, additional_headers=headers) as ws:

            # --- Configure session once for this request ---
            await ws.send(json.dumps({
                "type": "session.update",
                "session": {
                    "mode":            "commit",
                    "voice":           voice,
                    "language_type":   lang_code,
                    "response_format": "pcm",
                    "sample_rate":     SAMPLE_RATE,
                    "instructions":    instruct,
                },
            }))

            # Wait for session.updated confirmation before sending text
            async for raw_msg in ws:
                event = json.loads(raw_msg)
                if event.get("type") in ("session.updated", "session.created"):
                    break
                if event.get("type") == "error":
                    raise RuntimeError(f"Session error: {event}")

            # --- Process sentences one by one ---
            for i, sentence in enumerate(sentences):
                t_start     = _time.monotonic()
                first_chunk = True
                pcm_chunks: list[bytes] = []

                # Commit this sentence
                await ws.send(json.dumps({
                    "type": "input_text_buffer.append",
                    "text": sentence,
                }))
                await ws.send(json.dumps({"type": "input_text_buffer.commit"}))

                # Collect audio until response.done
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

                    elif etype == "response.done":
                        break   # this sentence is complete

                    elif etype == "session.finished":
                        break   # session ended

                    elif etype == "error":
                        raise RuntimeError(f"API error on sentence {i + 1}: {event}")

                    # else: ignore session.updated, heartbeat, etc.

                if not pcm_chunks:
                    continue

                # RMS normalise per sentence — identical to api.py
                raw     = b"".join(pcm_chunks)
                samples = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32767.0
                rms     = np.sqrt(np.mean(samples ** 2))
                if rms > 1e-6:
                    samples = samples * (TARGET_RMS / rms)
                normalized = (np.clip(samples, -1.0, 1.0) * 32767).astype(np.int16).tobytes()

                print(
                    f"[stream] sentence {i + 1}/{len(sentences)}: "
                    f"{len(sentence)} chars, rms={rms:.4f}",
                    flush=True,
                )

                for j in range(0, len(normalized), CHUNK_SIZE):
                    yield normalized[j : j + CHUNK_SIZE]


# ---------------------------------------------------------------------------
# Endpoints  (identical interface to api.py)
# ---------------------------------------------------------------------------


@app.post("/tts")
async def tts(request: TTSRequest):
    if not API_KEY:
        raise HTTPException(status_code=503, detail="DASHSCOPE_API_KEY not configured")

    # Resolve speaker → cloud voice name; fall back to DEFAULT_SPEAKER
    voice    = SPEAKER_MAP.get(request.speaker or "", DEFAULT_SPEAKER) if request.speaker else DEFAULT_SPEAKER
    instruct = request.instruct or DEFAULT_INSTRUCT

    return StreamingResponse(
        audio_stream(request.text, request.language, voice, instruct),
        media_type="audio/wav",
        headers={"Cache-Control": "no-cache"},
    )


@app.get("/health")
async def health():
    return {
        "status": "ok" if API_KEY else "no_api_key",
        "model":  MODEL_ID,
    }


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
