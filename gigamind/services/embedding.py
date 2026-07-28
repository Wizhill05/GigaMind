import os
import math
import hashlib
import urllib.request
import json
from typing import List, Optional

DEFAULT_DIM = 768

def _hash_token(token: str) -> int:
    return int(hashlib.md5(token.encode("utf-8")).hexdigest(), 16)

def generate_embedding(text: str, image_base64: Optional[str] = None, mime_type: str = "image/png") -> List[float]:
    """
    Generate Vector Embedding using Google Gemini Embedding 2 (models/gemini-embedding-2).
    Supports Multimodal input (text, code, images, documents).
    """
    # 1. Google Gemini Embedding 2 API (models/gemini-embedding-2)
    gemini_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
    if gemini_key:
        # Try gemini-embedding-2 model endpoint first
        gemini_models = ["models/gemini-embedding-2", "models/text-embedding-004"]

        for model_name in gemini_models:
            try:
                url = f"https://generativelanguage.googleapis.com/v1beta/{model_name}:embedContent?key={gemini_key}"

                parts = []
                if text:
                    parts.append({"text": text})
                if image_base64:
                    parts.append({
                        "inline_data": {
                            "mime_type": mime_type,
                            "data": image_base64
                        }
                    })

                req = urllib.request.Request(
                    url,
                    data=json.dumps({
                        "model": model_name,
                        "content": {"parts": parts}
                    }).encode("utf-8"),
                    headers={"Content-Type": "application/json"}
                )
                with urllib.request.urlopen(req, timeout=5) as resp:
                    data = json.loads(resp.read().decode("utf-8"))
                    values = data["embedding"]["values"]
                    return [float(x) for x in values[:DEFAULT_DIM]]
            except Exception as e:
                print(f"Gemini API model {model_name} note: {e}")

    # 2. Voyage AI (voyage-3-lite)
    voyage_key = os.getenv("VOYAGE_API_KEY")
    if voyage_key and text:
        try:
            req = urllib.request.Request(
                "https://api.voyageai.com/v1/embeddings",
                data=json.dumps({
                    "model": "voyage-3-lite",
                    "input": [text]
                }).encode("utf-8"),
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {voyage_key}"
                }
            )
            with urllib.request.urlopen(req, timeout=5) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                return [float(x) for x in data["data"][0]["embedding"][:DEFAULT_DIM]]
        except Exception as e:
            print(f"Voyage AI embedding fallback: {e}")

    # 3. OpenAI Embedding API (text-embedding-3-small)
    openai_key = os.getenv("OPENAI_API_KEY")
    if openai_key and text:
        try:
            req = urllib.request.Request(
                "https://api.openai.com/v1/embeddings",
                data=json.dumps({
                    "model": "text-embedding-3-small",
                    "input": text,
                    "dimensions": DEFAULT_DIM
                }).encode("utf-8"),
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {openai_key}"
                }
            )
            with urllib.request.urlopen(req, timeout=5) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                return [float(x) for x in data["data"][0]["embedding"]]
        except Exception as e:
            print(f"OpenAI embedding fallback: {e}")

    # 4. Zero-memory deterministic normalized feature vector (<10MB RAM, 1ms execution)
    vector = [0.0] * DEFAULT_DIM
    normalized_text = (text or "").lower().replace(",", " ").replace(".", " ").replace(";", " ")
    tokens = [t for t in normalized_text.split() if t]

    if not tokens:
        return vector

    for i, token in enumerate(tokens):
        idx = _hash_token(token) % DEFAULT_DIM
        vector[idx] += 1.0
        if i < len(tokens) - 1:
            bigram = f"{token}_{tokens[i+1]}"
            idx2 = _hash_token(bigram) % DEFAULT_DIM
            vector[idx2] += 0.5

    norm = math.sqrt(sum(x * x for x in vector)) or 1.0
    return [x / norm for x in vector]

def cosine_similarity(vec_a: List[float], vec_b: List[float]) -> float:
    if not vec_a or not vec_b or len(vec_a) != len(vec_b):
        return 0.0
    dot_product = sum(a * b for a, b in zip(vec_a, vec_b))
    norm_a = math.sqrt(sum(a * a for a in vec_a)) or 1.0
    norm_b = math.sqrt(sum(b * b for b in vec_b)) or 1.0
    return dot_product / (norm_a * norm_b)
