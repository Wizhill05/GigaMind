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
    # 1. Google Gemini Embeddings API (FREE 1,500 requests/min via Google AI Studio key)
    gemini_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
    if gemini_key:
        try:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/text-embedding-004:embedContent?key={gemini_key}"
            req = urllib.request.Request(
                url,
                data=json.dumps({
                    "model": "models/text-embedding-004",
                    "content": {"parts": [{"text": text}]}
                }).encode("utf-8"),
                headers={"Content-Type": "application/json"}
            )
            with urllib.request.urlopen(req, timeout=5) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                values = data["embedding"]["values"]
                # Truncate/slice or project to 384 dims for consistency if needed
                return [float(x) for x in values[:VECTOR_DIM]]
        except Exception as e:
            print(f"Gemini SaaS Embedding API fallback: {e}")

    # 2. HuggingFace Free Cloud Inference API (sentence-transformers/all-MiniLM-L6-v2)
    hf_token = os.getenv("HF_TOKEN") or os.getenv("HUGGINGFACE_API_KEY")
    if hf_token:
        try:
            url = "https://api-inference.huggingface.co/pipeline/feature-extraction/sentence-transformers/all-MiniLM-L6-v2"
            req = urllib.request.Request(
                url,
                data=json.dumps({"inputs": text}).encode("utf-8"),
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {hf_token}"
                }
            )
            with urllib.request.urlopen(req, timeout=5) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                if isinstance(data, list) and isinstance(data[0], float):
                    return [float(x) for x in data[:VECTOR_DIM]]
                elif isinstance(data, list) and isinstance(data[0], list):
                    return [float(x) for x in data[0][:VECTOR_DIM]]
        except Exception as e:
            print(f"HuggingFace SaaS Embedding API fallback: {e}")

    # 3. OpenAI Embedding API (text-embedding-3-small)
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
                return [float(x) for x in data["data"][0]["embedding"]]
        except Exception as e:
            print(f"OpenAI SaaS Embedding API fallback: {e}")

    # 4. Zero-memory deterministic normalized feature vector (Runs in 1ms, < 10MB RAM)
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
