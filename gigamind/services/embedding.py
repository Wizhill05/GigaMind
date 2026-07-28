import math
import hashlib
from typing import List

VECTOR_DIM = 384
_model = None

def get_sentence_transformer_model():
    global _model
    if _model is None:
        try:
            from sentence_transformers import SentenceTransformer
            _model = SentenceTransformer("all-MiniLM-L6-v2")
        except Exception as e:
            print(f"SentenceTransformers not loaded: {e}. Using deterministic local feature vectorizer.")
            _model = False
    return _model

def _hash_token(token: str) -> int:
    return int(hashlib.md5(token.encode("utf-8")).hexdigest(), 16)

def generate_embedding(text: str) -> List[float]:
    model = get_sentence_transformer_model()
    if model:
        try:
            embedding = model.encode(text, convert_to_numpy=True).tolist()
            return [float(x) for x in embedding]
        except Exception as e:
            print(f"Transformer model encoding failed: {e}")

    # Zero-dependency deterministic feature vector fallback
    vector = [0.0] * VECTOR_DIM
    normalized_text = text.lower().replace(",", " ").replace(".", " ")
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

    # L2 normalize
    norm = math.sqrt(sum(x * x for x in vector)) or 1.0
    return [x / norm for x in vector]

def cosine_similarity(vec_a: List[float], vec_b: List[float]) -> float:
    if not vec_a or not vec_b or len(vec_a) != len(vec_b):
        return 0.0
    dot_product = sum(a * b for a, b in zip(vec_a, vec_b))
    norm_a = math.sqrt(sum(a * a for a in vec_a)) or 1.0
    norm_b = math.sqrt(sum(b * b for b in vec_b)) or 1.0
    return dot_product / (norm_a * norm_b)
