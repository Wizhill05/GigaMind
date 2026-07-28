import os
import math
import hashlib
import urllib.request
import json
from typing import List

VECTOR_DIM = 384

def _hash_token(token: str) -> int:
    return int(hashlib.md5(token.encode("utf-8")).hexdigest(), 16)

def generate_embedding(text: str) -> List[float]:
    # 1. Try OpenAI Embedding API if key is present
    openai_key = os.getenv("OPENAI_API_KEY")
    if openai_key:
        try:
            req = urllib.request.Request(
                "https://api.openai.com/v1/embeddings",
                data=json.dumps({
                    "model": "text-embedding-3-small",
                    "input": text,
                    "dimensions": VECTOR_DIM
                }).encode("utf-8"),
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {openai_key}"
                }
            )
            with urllib.request.urlopen(req, timeout=5) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                return data["data"][0]["embedding"]
        except Exception as e:
            print(f"OpenAI embedding call fallback: {e}")

    # 2. Fast, zero-memory deterministic normalized feature vector (Runs in 1ms, < 10MB RAM)
    vector = [0.0] * VECTOR_DIM
    normalized_text = text.lower().replace(",", " ").replace(".", " ").replace(";", " ")
    tokens = [t for t in normalized_text.split() if t]

    if not tokens:
        return vector

    for i, token in enumerate(tokens):
        idx = _hash_token(token) % VECTOR_DIM
        vector[idx] += 1.0
        if i < len(tokens) - 1:
            bigram = f"{token}_{tokens[i+1]}"
            idx2 = _hash_token(bigram) % VECTOR_DIM
            vector[idx2] += 0.5

    # L2 Normalization (unit vector)
    norm = math.sqrt(sum(x * x for x in vector)) or 1.0
    return [x / norm for x in vector]

def cosine_similarity(vec_a: List[float], vec_b: List[float]) -> float:
    if not vec_a or not vec_b or len(vec_a) != len(vec_b):
        return 0.0
    dot_product = sum(a * b for a, b in zip(vec_a, vec_b))
    norm_a = math.sqrt(sum(a * a for a in vec_a)) or 1.0
    norm_b = math.sqrt(sum(b * b for b in vec_b)) or 1.0
    return dot_product / (norm_a * norm_b)
