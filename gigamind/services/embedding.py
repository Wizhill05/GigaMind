import os
import time
import urllib.request
import urllib.error
import json
import base64
from typing import List, Optional
from dotenv import load_dotenv

load_dotenv()
DEFAULT_DIM = int(os.getenv("EMBEDDING_DIM", "768"))
MODEL_NAME = os.getenv("GEMINI_EMBEDDING_MODEL", "models/gemini-embedding-2")


def generate_embedding(
    text: Optional[str] = None,
    inline_bytes: Optional[bytes] = None,
    image_base64: Optional[str] = None,
    mime_type: Optional[str] = None
) -> List[float]:
    """
    Exclusively generates multimodal vector embeddings using Google Gemini Embedding 2 (models/gemini-embedding-2).
    Strictly zero fallback models.
    Supports direct PDF binaries, images (PNG/JPG/WEBP), diagrams, documents, and code.
    """
    gemini_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
    if not gemini_key:
        raise RuntimeError("GEMINI_API_KEY / GOOGLE_API_KEY environment variable is required for Gemini Embedding 2.")

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

    url = f"https://generativelanguage.googleapis.com/v1beta/{MODEL_NAME}:embedContent?key={gemini_key}"
    last_error = None

    # Retry up to 4 times on transient rate limits with Google's recommended retryDelay
    for attempt in range(4):
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
            if http_err.code == 429 and attempt < 3:
                sleep_time = 3.5 * (attempt + 1)
                try:
                    err_json = json.loads(err_body)
                    for detail in err_json.get("error", {}).get("details", []):
                        if "retryDelay" in detail:
                            delay_str = detail["retryDelay"].replace("s", "")
                            sleep_time = max(float(delay_str) + 0.5, 3.5)
                except Exception:
                    pass
                time.sleep(sleep_time)
                continue
            raise RuntimeError(f"Gemini Embedding 2 API Error (HTTP {http_err.code}): {err_body or http_err}") from http_err
        except Exception as e:
            last_error = e
            if attempt < 3:
                time.sleep(2.0 * (attempt + 1))
                continue
            raise RuntimeError(f"Gemini Embedding 2 connection error: {e}") from e

    raise RuntimeError(f"Gemini Embedding 2 failed after 4 attempts: {last_error}")


def cosine_similarity(vec_a: List[float], vec_b: List[float]) -> float:
    if not vec_a or not vec_b or len(vec_a) != len(vec_b):
        return 0.0
    dot_product = sum(a * b for a, b in zip(vec_a, vec_b))
    norm_a = sum(a * a for a in vec_a) ** 0.5
    norm_b = sum(b * b for b in vec_b) ** 0.5
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot_product / (norm_a * norm_b)
