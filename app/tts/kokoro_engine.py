import os
import io
import re
import hashlib
from pathlib import Path
from typing import Dict, Any, List, Optional
import soundfile as sf

# Try importing Kokoro; will be lazy loaded on demand
try:
    from kokoro_onnx import Kokoro
except ImportError:
    Kokoro = None


CURATED_VOICES = [
    {"id": "af_sarah", "name": "Sarah", "accent": "US Female", "style": "Clear Studio (Default)", "gender": "female"},
    {"id": "af_bella", "name": "Bella", "accent": "US Female", "style": "Warm & Engaging", "gender": "female"},
    {"id": "af_nicole", "name": "Nicole", "accent": "US Female", "style": "Direct & Precise", "gender": "female"},
    {"id": "af_sky", "name": "Sky", "accent": "US Female", "style": "Dynamic & Bright", "gender": "female"},
    {"id": "am_adam", "name": "Adam", "accent": "US Male", "style": "Deep & Grounded", "gender": "male"},
    {"id": "am_michael", "name": "Michael", "accent": "US Male", "style": "Authoritative & Clear", "gender": "male"},
    {"id": "am_echo", "name": "Echo", "accent": "US Male", "style": "Resonant & Calm", "gender": "male"},
    {"id": "bf_emma", "name": "Emma", "accent": "UK Female", "style": "Academic & Articulate", "gender": "female"},
    {"id": "bf_isabella", "name": "Isabella", "accent": "UK Female", "style": "Crisp & Refined", "gender": "female"},
    {"id": "bm_george", "name": "George", "accent": "UK Male", "style": "Scholarly & Poised", "gender": "male"},
    {"id": "bm_lewis", "name": "Lewis", "accent": "UK Male", "style": "Narrative & Deep", "gender": "male"},
]


class KokoroTTSEngine:
    """High-fidelity neural text-to-speech engine using kokoro-onnx and soundfile."""

    def __init__(
        self,
        model_path: Optional[str] = None,
        voices_path: Optional[str] = None,
        cache_size: int = 50,
    ):
        base_dir = Path(__file__).resolve().parent.parent.parent
        self.model_path = Path(model_path) if model_path else base_dir / "data" / "models" / "kokoro" / "kokoro-v1.0.onnx"
        self.voices_path = Path(voices_path) if voices_path else base_dir / "data" / "models" / "kokoro" / "voices-v1.0.bin"
        self._kokoro = None
        self._available_voices: List[str] = []
        self._cache: Dict[str, bytes] = {}
        self._cache_keys: List[str] = []
        self.cache_size = cache_size

    def is_available(self) -> bool:
        """Check if kokoro-onnx library is installed."""
        return Kokoro is not None

    def download_models_if_needed(self):
        """Automatically download Kokoro ONNX model and voices if not present."""
        if self.model_path.exists() and self.voices_path.exists():
            return

        self.model_path.parent.mkdir(parents=True, exist_ok=True)
        import urllib.request

        ONNX_URL = "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/kokoro-v1.0.onnx"
        VOICES_URL = "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/voices-v1.0.bin"

        if not self.voices_path.exists():
            print(f"[KokoroTTS] Downloading voices file to {self.voices_path}...")
            urllib.request.urlretrieve(VOICES_URL, str(self.voices_path))
            print("[KokoroTTS] Voices file downloaded.")

        if not self.model_path.exists():
            print(f"[KokoroTTS] Downloading model weights to {self.model_path} (~310MB)...")
            urllib.request.urlretrieve(ONNX_URL, str(self.model_path))
            print("[KokoroTTS] Model weights downloaded.")

    def _ensure_loaded(self):
        """Lazy-load the Kokoro ONNX session."""
        if self._kokoro is not None:
            return

        if Kokoro is None:
            raise RuntimeError("kokoro-onnx is not installed in the python environment.")

        self.download_models_if_needed()

        self._kokoro = Kokoro(
            model_path=str(self.model_path),
            voices_path=str(self.voices_path),
        )
        try:
            self._available_voices = self._kokoro.get_voices()
        except Exception:
            self._available_voices = [v["id"] for v in CURATED_VOICES]

    def list_voices(self) -> List[Dict[str, Any]]:
        """Return curated voice metadata for client selection."""
        known_ids = set(self._available_voices) if self._kokoro else {v["id"] for v in CURATED_VOICES}
        voices = []
        for cv in CURATED_VOICES:
            if not known_ids or cv["id"] in known_ids:
                voices.append({**cv, "available": True})
        return voices

    @staticmethod
    def clean_text_for_speech(text: str) -> str:
        """Strip academic markdown formatting and citations so speech flows naturally."""
        if not text:
            return ""

        # 1. Remove code blocks
        t = re.sub(r'```[\s\S]*?```', ' ', text)
        t = re.sub(r'`([^`]+)`', r'\1', t)

        # 2. Remove markdown links [title](url) -> title
        t = re.sub(r'\[([^\]]+)\]\([^)]+\)', r'\1', t)

        # 3. Remove numeric citations [1], [2], [1, 2] and doc references [doc_...]
        t = re.sub(r'\[(?:doc_[a-zA-Z0-9_\-\.]+|\d+(?:\s*,\s*\d+)*)\]', '', t)

        # 4. Remove headings markers (###, ##, #)
        t = re.sub(r'^#{1,6}\s+', '', t, flags=re.MULTILINE)

        # 5. Remove bold, italic, strikethrough formatting
        t = re.sub(r'[*_~]{1,3}([^*_~]+)[*_~]{1,3}', r'\1', t)

        # 6. Convert bullet points and numbered lists to sentence pauses
        t = re.sub(r'^\s*[-*•]\s+', '. ', t, flags=re.MULTILINE)
        t = re.sub(r'^\s*\d+\.\s+', '. ', t, flags=re.MULTILINE)

        # 7. Clean table markdown pipes
        t = re.sub(r'\|', ' ', t)

        # 8. Clean trailing punctuation artifacts like ': .' or '.. '
        t = re.sub(r':\s*\.', ':', t)
        t = re.sub(r'\.{2,}', '.', t)
        t = re.sub(r'\s+([,.:;?!])', r'\1', t)

        # 9. Clean excess whitespace
        t = re.sub(r'\s+', ' ', t).strip()
        return t

    def _get_cache_key(self, text: str, voice: str, speed: float) -> str:
        h = hashlib.sha256(f"{text}|{voice}|{speed:.2f}".encode("utf-8")).hexdigest()
        return h

    def synthesize_wav(
        self,
        text: str,
        voice: str = "af_sarah",
        speed: float = 1.0,
        lang: str = "en-us",
    ) -> bytes:
        """Synthesize spoken audio from text and return standard WAV binary bytes."""
        clean_text = self.clean_text_for_speech(text)
        if not clean_text:
            raise ValueError("No speakable text provided.")

        # Ensure speed is in reasonable bounds
        speed = max(0.5, min(2.0, float(speed)))

        # Fallback to default voice if requested voice is invalid
        if not voice:
            voice = "af_sarah"

        # Check in-memory cache
        cache_key = self._get_cache_key(clean_text, voice, speed)
        if cache_key in self._cache:
            return self._cache[cache_key]

        # Lazy load model
        self._ensure_loaded()

        # Handle voices that specify language
        if voice.startswith("b"):  # British
            lang = "en-gb"
        elif voice.startswith("a"):  # American
            lang = "en-us"

        try:
            samples, sample_rate = self._kokoro.create(
                clean_text,
                voice=voice,
                speed=speed,
                lang=lang,
                sentence_pause=0.25,
                clause_pause=0.1,
            )
        except Exception as e:
            # If specified voice failed, retry with af_sarah as safe fallback
            if voice != "af_sarah":
                samples, sample_rate = self._kokoro.create(
                    clean_text,
                    voice="af_sarah",
                    speed=speed,
                    lang="en-us",
                    sentence_pause=0.25,
                    clause_pause=0.1,
                )
            else:
                raise e

        # Encode samples to WAV in memory
        buffer = io.BytesIO()
        sf.write(buffer, samples, sample_rate, format="WAV")
        wav_bytes = buffer.getvalue()

        # Update LRU cache
        if len(self._cache_keys) >= self.cache_size:
            oldest_key = self._cache_keys.pop(0)
            self._cache.pop(oldest_key, None)

        self._cache[cache_key] = wav_bytes
        self._cache_keys.append(cache_key)

        return wav_bytes


# Global singleton instance
tts_engine = KokoroTTSEngine()
