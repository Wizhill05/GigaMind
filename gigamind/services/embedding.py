import os
import time
import threading
import urllib.request
import urllib.error
import json
import base64
import math
from typing import List, Optional, Dict, Any
from dotenv import load_dotenv

load_dotenv()

DEFAULT_DIM = int(os.getenv("EMBEDDING_DIM", "768"))
MODEL_NAME = os.getenv("GEMINI_EMBEDDING_MODEL", "models/gemini-embedding-2")


def _get_api_keys() -> List[str]:
    """
    Extracts all configured Gemini / Google API keys from environment variables.
    Supports comma-separated, semicolon-separated, or single keys.
    e.g. GEMINI_API_KEY="key1,key2,key3" or GEMINI_API_KEYS="key1,key2"
    """
    raw_keys = (
        os.getenv("GEMINI_API_KEYS")
        or os.getenv("GEMINI_API_KEY")
        or os.getenv("GOOGLE_API_KEYS")
        or os.getenv("GOOGLE_API_KEY")
        or ""
    )
    keys: List[str] = []
    for part in raw_keys.replace(";", ",").replace("\n", ",").split(","):
        cleaned = part.strip().strip('"').strip("'")
        if cleaned and cleaned not in keys:
            keys.append(cleaned)
    return keys


class EmbeddingInputError(ValueError):
    """The caller supplied unsupported or invalid embedding input."""


class EmbeddingUnavailable(RuntimeError):
    """The embedding provider could not return a usable vector."""


class GeminiKeyPool:
    """
    Thread-safe Round-Robin API Key Pool with automated cooldown tracking
    and instant failover across multiple Gemini API keys.
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._index = 0
        self._cooldowns: Dict[str, float] = {}

    def get_next_key(self) -> str:
        keys = _get_api_keys()
        if not keys:
            raise EmbeddingUnavailable(
                "GEMINI_API_KEY environment variable is required. "
                'You can provide multiple comma-separated keys (e.g. GEMINI_API_KEY="key1,key2,key3").'
            )

        now = time.time()
        with self._lock:
            # 1. Round-robin search for an active key not on cooldown
            for _ in range(len(keys)):
                key = keys[self._index % len(keys)]
                self._index += 1
                cooldown_until = self._cooldowns.get(key, 0)
                if now >= cooldown_until:
                    return key

            # 2. If all keys are on cooldown, select the one that expires soonest
            earliest_key = min(keys, key=lambda k: self._cooldowns.get(k, 0))
            return earliest_key

    def mark_rate_limited(self, key: str, retry_delay: float = 3.5):
        with self._lock:
            self._cooldowns[key] = time.time() + max(retry_delay, 3.0)

    def get_pool_status(self) -> Dict[str, Any]:
        keys = _get_api_keys()
        now = time.time()
        with self._lock:
            return {
                "total_keys": len(keys),
                "active_keys": sum(1 for k in keys if now >= self._cooldowns.get(k, 0)),
                "cooling_down_keys": sum(
                    1 for k in keys if now < self._cooldowns.get(k, 0)
                ),
            }


key_pool = GeminiKeyPool()


MAX_TEXT_BYTES = 8192
MAX_RESPONSE_BYTES = 250_000


def _binary_part(inline_bytes, image_base64, mime_type):
    from gigamind.services.parser import binary_mime, MAX_INLINE_BYTES

    if inline_bytes is not None and image_base64 is not None:
        raise EmbeddingInputError("Provide only one binary input")
    if image_base64 is not None:
        if (
            not isinstance(image_base64, str)
            or len(image_base64) > ((MAX_INLINE_BYTES + 2) // 3) * 4
        ):
            raise EmbeddingInputError("Invalid or oversized base64 input")
        try:
            inline_bytes = base64.b64decode(image_base64, validate=True)
        except (ValueError, TypeError):
            raise EmbeddingInputError("Invalid base64 input") from None
    if inline_bytes is None:
        return None
    if (
        not isinstance(inline_bytes, bytes)
        or not inline_bytes
        or len(inline_bytes) > MAX_INLINE_BYTES
    ):
        raise EmbeddingInputError("Invalid or oversized binary input")
    detected = binary_mime(inline_bytes)
    if detected is None or (mime_type is not None and mime_type != detected):
        raise EmbeddingInputError("Unsupported or mismatched embedding MIME type")
    if image_base64 is not None and not detected.startswith("image/"):
        raise EmbeddingInputError("Image input must be PNG or JPEG")
    if detected == "application/pdf":
        import io
        import pypdf

        try:
            reader = pypdf.PdfReader(io.BytesIO(inline_bytes))
            valid = not reader.is_encrypted and 1 <= len(reader.pages) <= 6
        except Exception:
            valid = False
        if not valid:
            raise EmbeddingInputError(
                "PDF embedding input must contain one to six unencrypted pages"
            )
    return {
        "inline_data": {
            "mime_type": detected,
            "data": base64.b64encode(inline_bytes).decode("ascii"),
        }
    }


def validate_embedding_vector(values):
    """Accept only finite, nonzero vectors of the configured dimension."""
    try:
        valid = (
            isinstance(values, list)
            and len(values) == DEFAULT_DIM
            and DEFAULT_DIM > 0
            and all(
                isinstance(value, (int, float))
                and not isinstance(value, bool)
                and math.isfinite(value)
                for value in values
            )
            and any(value != 0 for value in values)
        )
    except OverflowError:
        valid = False
    if not valid:
        raise EmbeddingUnavailable("Gemini embedding returned an invalid response")
    return [float(value) for value in values]


def _response_vector(data):
    try:
        values = data["embedding"]["values"]
    except (KeyError, TypeError):
        raise EmbeddingUnavailable(
            "Gemini embedding returned an invalid response"
        ) from None
    return validate_embedding_vector(values)


def generate_embedding(
    text: Optional[str] = None,
    inline_bytes: Optional[bytes] = None,
    image_base64: Optional[str] = None,
    mime_type: Optional[str] = None,
) -> List[float]:
    """Submit bounded content and accept only complete, finite provider vectors."""
    parts = []
    if text is not None:
        if (
            not isinstance(text, str)
            or not text.strip()
            or len(text.encode("utf-8")) > MAX_TEXT_BYTES
        ):
            raise EmbeddingInputError(
                "Embedding text is empty or exceeds the application byte limit"
            )
        parts.append({"text": text})
    binary = _binary_part(inline_bytes, image_base64, mime_type)
    if binary is not None:
        parts.append(binary)
    if not parts:
        raise EmbeddingInputError("Embedding input is empty")
    keys = _get_api_keys()
    if not keys:
        raise EmbeddingUnavailable("GEMINI_API_KEY environment variable is required.")
    payload = {
        "model": MODEL_NAME,
        "content": {"parts": parts},
        "output_dimensionality": DEFAULT_DIM,
    }
    max_attempts = max(len(keys) * 2, 4)
    for attempt in range(max_attempts):
        active_key = key_pool.get_next_key()
        # Credentials are headers, never part of a URL or exception message.
        req = urllib.request.Request(
            f"https://generativelanguage.googleapis.com/v1beta/{MODEL_NAME}:embedContent",
            data=json.dumps(payload, allow_nan=False).encode("utf-8"),
            headers={"Content-Type": "application/json", "x-goog-api-key": active_key},
        )
        try:
            with urllib.request.urlopen(req, timeout=20) as response:
                raw = response.read(MAX_RESPONSE_BYTES + 1)
            if len(raw) > MAX_RESPONSE_BYTES:
                raise ValueError("Embedding response exceeds limit")
            return _response_vector(json.loads(raw))
        except urllib.error.HTTPError as exc:
            code = exc.code
            exc.close()
            alternate_key = code == 403 and len(keys) > 1
            if code != 429 and not alternate_key and not 500 <= code <= 599:
                raise EmbeddingUnavailable(
                    f"Gemini embedding request failed (HTTP {code})"
                ) from None
            if alternate_key and attempt == max_attempts - 1:
                raise EmbeddingUnavailable(
                    "Gemini embedding request failed (HTTP 403)"
                ) from None
            if code == 429 or alternate_key:
                key_pool.mark_rate_limited(active_key)
            if attempt < max_attempts - 1 and len(keys) == 1:
                time.sleep(min(2**attempt, 5))
        except (ValueError, TypeError, OverflowError, UnicodeError):
            # Malformed successful responses are not useful retry candidates.
            raise EmbeddingUnavailable(
                "Gemini embedding returned an invalid response"
            ) from None
        except (urllib.error.URLError, OSError):
            if attempt < max_attempts - 1:
                time.sleep(min(2**attempt, 5))
    raise EmbeddingUnavailable("Gemini embedding request failed after retries")


def cosine_similarity(vec_a: List[float], vec_b: List[float]) -> float:
    if not vec_a or not vec_b or len(vec_a) != len(vec_b):
        return 0.0
    dot_product = sum(a * b for a, b in zip(vec_a, vec_b))
    norm_a = sum(a * a for a in vec_a) ** 0.5
    norm_b = sum(b * b for b in vec_b) ** 0.5
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot_product / (norm_a * norm_b)
