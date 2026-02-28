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
import hashlib
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
VOICE_DIR = os.path.join(
    os.path.dirname(os.path.dirname(__file__)), "voices"
)  # ../voices/

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
voice_cache: dict[str, str] = {}  # Cache instruct -> voice_name (in-memory)


def _get_voice_dir() -> str:
    """Ensure voice directory exists and return path."""
    if not os.path.exists(VOICE_DIR):
        os.makedirs(VOICE_DIR)
    return VOICE_DIR


def _hash_instruct(instruct: str) -> str:
    """Generate hash for instruct string."""
    return hashlib.sha256(instruct.encode()).hexdigest()[:16]


def _get_voice_file_path(instruct: str) -> str:
    """Get file path for voices cache."""
    return os.path.join(_get_voice_dir(), "voices.json")


def load_voice_from_disk(instruct: str) -> Optional[str]:
    """Load voice name from disk cache if exists."""
    voice_file = _get_voice_file_path(instruct)
    if os.path.exists(voice_file):
        try:
            with open(voice_file, "r") as f:
                data = json.load(f)
            # Match by instruct
            for entry in data.get("voices", []):
                if entry.get("instruct") == instruct:
                    print(
                        f"[voice] Loaded from disk: {entry.get('voice_name')}",
                        flush=True,
                    )
                    return entry.get("voice_name")
        except Exception as e:
            print(f"[voice] Failed to load voice from disk: {e}", flush=True)
    return None


def save_voice_to_disk(instruct: str, voice_name: str) -> None:
    """Save voice name to disk cache."""
    voice_file = _get_voice_file_path(instruct)
    try:
        # Load existing data
        if os.path.exists(voice_file):
            with open(voice_file, "r") as f:
                data = json.load(f)
        else:
            data = {"voices": []}

        # Check if instruct already exists
        for entry in data["voices"]:
            if entry.get("instruct") == instruct:
                entry["voice_name"] = voice_name
                break
        else:
            # Add new entry
            data["voices"].append({"instruct": instruct, "voice_name": voice_name})

        with open(voice_file, "w") as f:
            json.dump(data, f, indent=2)
        print(f"[voice] Saved to disk: {voice_name}", flush=True)
    except Exception as e:
        print(f"[voice] Failed to save voice to disk: {e}", flush=True)


def load_all_voices_from_disk() -> dict[str, str]:
    """Load all cached voices from disk on startup."""
    cache = {}
    voice_file = os.path.join(_get_voice_dir(), "voices.json")
    if os.path.exists(voice_file):
        try:
            with open(voice_file, "r") as f:
                data = json.load(f)
            for entry in data.get("voices", []):
                instruct = entry.get("instruct", "")
                voice_name = entry.get("voice_name", "")
                if instruct and voice_name:
                    cache[instruct[:200]] = voice_name
        except Exception as e:
            print(f"[voice] Failed to load voices from disk: {e}", flush=True)
    print(f"[voice] Loaded {len(cache)} voices from disk", flush=True)
    return cache


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
    global voice_cache
    if not API_KEY:
        print(
            "[startup] WARNING: DASHSCOPE_API_KEY not set in .env — /tts will return 503"
        )
    else:
        print(f"[startup] API key loaded. Model: {MODEL_ID}")
        voice_cache = load_all_voices_from_disk()
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
    Full-text synthesis via the Realtime WebSocket API.

    Sends entire text in one commit for consistent tone,
    then normalizes the complete audio once at the end.
    """
    print(f"[audio_stream] START: voice={voice}, text_len={len(text)}", flush=True)

    lang_code = LANG_MAP.get(language, "en")
    ws_url = f"{WS_BASE_URL}?model={MODEL_ID}"
    headers = {"Authorization": f"Bearer {API_KEY}"}

    use_voice = voice or custom_voice

    async with model_lock:
        async with websockets.connect(ws_url, additional_headers=headers) as ws:
            # Configure session
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

            # Wait for session confirmation
            session_ok = False
            async for raw_msg in ws:
                event = json.loads(raw_msg)
                etype = event.get("type", "")
                if etype in ("session.updated", "session.created"):
                    session_ok = True
                    break
                if etype == "error":
                    error_detail = event.get("error", {}).get("message", str(event))
                    print(f"[ws] session error: {error_detail}", flush=True)
                    raise RuntimeError(f"Session error: {error_detail}")

            if not session_ok:
                raise RuntimeError("Failed to establish session")

            # Send entire text in one commit
            t_start = _time.monotonic()
            await ws.send(
                json.dumps(
                    {
                        "type": "input_text_buffer.append",
                        "text": text,
                    }
                )
            )
            await ws.send(json.dumps({"type": "input_text_buffer.commit"}))

            # Collect all audio chunks
            pcm_chunks: list[bytes] = []
            first_chunk = True
            async for raw_msg in ws:
                event = json.loads(raw_msg)
                etype = event.get("type", "")

                if etype == "response.audio.delta":
                    chunk = base64.b64decode(event.get("delta", ""))
                    if chunk:
                        if first_chunk:
                            print(
                                f"[ws] TTFA: {_time.monotonic() - t_start:.3f}s",
                                flush=True,
                            )
                            first_chunk = False
                        pcm_chunks.append(chunk)

                elif etype in ("response.done", "session.finished"):
                    break

                elif etype == "error":
                    print(f"[audio_stream] WS ERROR: {event}", flush=True)
                    raise RuntimeError(f"API error: {event}")

            if not pcm_chunks:
                return

            # Normalize entire audio once
            raw = b"".join(pcm_chunks)
            samples = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32767.0
            rms = np.sqrt(np.mean(samples**2))
            if rms > 1e-6:
                samples = samples * (TARGET_RMS / rms)
            normalized = np.clip(samples, -1.0, 1.0) * 32767
            normalized = normalized.astype(np.int16).tobytes()

            print(
                f"[stream] {len(text)} chars, rms={rms:.4f}",
                flush=True,
            )

            # Yield header then audio
            yield streaming_wav_header()
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
    print(f"[voice_create] START: prompt={voice_prompt[:50]}...", flush=True)
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
        error_msg = (
            f"Voice design failed: {response.status_code} - {response.text[:500]}"
        )
        print(f"[voice_create] ERROR: {error_msg}", flush=True)
        raise RuntimeError(error_msg)

    result = response.json()
    voice = result["output"]["voice"]
    print(f"[voice_create] SUCCESS: voice={voice}", flush=True)
    return voice


@app.post("/tts")
async def tts(request: TTSRequest):
    """Synthesize speech. If instruct is provided, creates a voice design on-the-fly."""
    if not API_KEY:
        raise HTTPException(status_code=503, detail="DASHSCOPE_API_KEY not configured")

    voice = None

    if request.instruct:
        # Check in-memory cache first
        cache_key = request.instruct[:200]  # Truncate for cache key
        if cache_key in voice_cache:
            print(f"[tts] Using in-memory cached voice: {voice_cache[cache_key]}")
            voice = voice_cache[cache_key]
        else:
            # Check disk cache
            voice = load_voice_from_disk(request.instruct)
            if voice:
                voice_cache[cache_key] = voice
                print(f"[tts] Using disk cached voice: {voice}")
            else:
                # Create new voice
                print(f"[tts] Creating voice from instruct: {request.instruct[:50]}...")
                try:
                    voice = create_voice_design(
                        voice_prompt=request.instruct,
                        preview_text=request.text[:100] if request.text else "Hello",
                        language=LANG_MAP.get(request.language, "en"),
                    )
                    print(f"[tts] Created voice: {voice}")
                    voice_cache[cache_key] = voice
                    save_voice_to_disk(request.instruct, voice)
                except Exception as e:
                    print(f"[tts] Voice creation failed: {e}")
                    # Try to use existing voice if creation fails
                    voice = custom_voice
                    if not voice:
                        raise HTTPException(
                            status_code=500,
                            detail=f"Voice creation failed: {str(e)[:100]}",
                        )
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
    return {"voice": custom_voice, "cached_voices": len(voice_cache)}


@app.post("/voice/clear-cache")
async def clear_voice_cache():
    """Clear the voice cache."""
    global voice_cache
    voice_cache = {}
    return {"status": "cache cleared"}


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
