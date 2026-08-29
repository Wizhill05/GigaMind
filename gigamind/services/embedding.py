import os
import time
import threading
import urllib.request
import urllib.error
import json
import base64
from typing import List, Optional, Dict
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
            raise RuntimeError(
                "GEMINI_API_KEY environment variable is required. "
                "You can provide multiple comma-separated keys (e.g. GEMINI_API_KEY=\"key1,key2,key3\")."
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
                "cooling_down_keys": sum(1 for k in keys if now < self._cooldowns.get(k, 0))
            }


key_pool = GeminiKeyPool()


def generate_embedding(
    text: Optional[str] = None,
    inline_bytes: Optional[bytes] = None,
    image_base64: Optional[str] = None,
    mime_type: Optional[str] = None
) -> List[float]:
    """
    Exclusively generates multimodal vector embeddings using Google Gemini Embedding 2 (models/gemini-embedding-2).
    Uses a thread-safe round-robin API key rotation pool with automated failover.
    Supports direct PDF binaries, images (PNG/JPG/WEBP), diagrams, documents, and code.
    """
    keys = _get_api_keys()
    if not keys:
        raise RuntimeError("GEMINI_API_KEY environment variable is required.")

    parts = []
    if text:
        parts.append({"text": text})
    if inline_bytes:
        b64_data = base64.b64encode(inline_bytes).decode("utf-8")
        parts.append({
            "inline_data": {
                "mime_type": mime_type or "application/pdf",
                "data": b64_data
            }
        })
    elif image_base64:
        parts.append({
            "inline_data": {
                "mime_type": mime_type or "image/png",
                "data": image_base64
            }
        })

    if not parts:
        parts.append({"text": text or ""})

    payload = {
        "model": MODEL_NAME,
        "content": {"parts": parts},
        "output_dimensionality": DEFAULT_DIM
    }

    max_attempts = max(len(keys) * 2, 4)
    last_error = None

    for attempt in range(max_attempts):
        active_key = key_pool.get_next_key()
        url = f"https://generativelanguage.googleapis.com/v1beta/{MODEL_NAME}:embedContent?key={active_key}"

        try:
            req = urllib.request.Request(
                url,
                data=json.dumps(payload).encode("utf-8"),
                headers={"Content-Type": "application/json"}
            )
            with urllib.request.urlopen(req, timeout=20) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                values = data["embedding"]["values"]
                return [float(x) for x in values[:DEFAULT_DIM]]
        except urllib.error.HTTPError as http_err:
            last_error = http_err
            err_body = ""
            try:
                err_body = http_err.read().decode("utf-8")
            except Exception:
                pass

            # Quota exhausted / Rate limit hit on this specific key
            if http_err.code in (429, 403):
                sleep_time = 3.5
                try:
                    err_json = json.loads(err_body)
                    for detail in err_json.get("error", {}).get("details", []):
                        if "retryDelay" in detail:
                            delay_str = detail["retryDelay"].replace("s", "")
                            sleep_time = max(float(delay_str) + 0.5, 3.5)
                except Exception:
                    pass

                key_pool.mark_rate_limited(active_key, retry_delay=sleep_time)

                # If multiple keys are configured, rotate immediately without sleeping
                if len(keys) > 1 and attempt < max_attempts - 1:
                    continue
                else:
                    time.sleep(min(sleep_time, 5.0))
                    continue

            raise RuntimeError(f"Gemini Embedding 2 API Error (HTTP {http_err.code}): {err_body or http_err}") from http_err
        except Exception as e:
            last_error = e
            if attempt < max_attempts - 1:
                time.sleep(1.0)
                continue
            raise RuntimeError(f"Gemini Embedding 2 connection error: {e}") from e

    raise RuntimeError(f"Gemini Embedding 2 failed after {max_attempts} attempts across {len(keys)} API key(s): {last_error}")


def cosine_similarity(vec_a: List[float], vec_b: List[float]) -> float:
    if not vec_a or not vec_b or len(vec_a) != len(vec_b):
        return 0.0
    dot_product = sum(a * b for a, b in zip(vec_a, vec_b))
    norm_a = sum(a * a for a in vec_a) ** 0.5
    norm_b = sum(b * b for b in vec_b) ** 0.5
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot_product / (norm_a * norm_b)
