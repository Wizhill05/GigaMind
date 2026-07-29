import os
import math
import re
import json
import urllib.request
from typing import List, Dict, Any, Optional

def _token_interaction_score(query: str, text: str, vector_score: float = 0.0) -> float:
    """
    Built-in high-performance token-interaction cross-scoring algorithm.
    Evaluates deep text match via term frequency, n-gram overlap, query density, and vector score.
    """
    q_clean = (query or "").lower().strip()
    t_clean = (text or "").lower().strip()

    if not q_clean or not t_clean:
        return vector_score

    # Tokenization
    q_words = [w for w in re.findall(r'\w+', q_clean) if len(w) > 1]
    t_words = [w for w in re.findall(r'\w+', t_clean) if len(w) > 1]

    if not q_words or not t_words:
        return vector_score

    # 1. Exact Phrase & Substring Match
    phrase_score = 0.0
    if q_clean in t_clean:
        phrase_score = 1.0
    elif len(q_words) > 1:
        # Check consecutive 2-word ngrams
        q_bigrams = [f"{q_words[i]} {q_words[i+1]}" for i in range(len(q_words)-1)]
        hits = sum(1 for bg in q_bigrams if bg in t_clean)
        phrase_score = hits / max(1, len(q_bigrams))

    # 2. Term Frequency & Density
    unique_q = set(q_words)
    hit_count = 0
    tf_sum = 0
    t_word_count = len(t_words)

    for word in unique_q:
        c = t_words.count(word)
        if c > 0:
            hit_count += 1
            # Diminishing returns on term frequency
            tf_sum += (1.0 + math.log(c))

    term_overlap = hit_count / len(unique_q)
    tf_density = min(1.0, tf_sum / (len(unique_q) * 1.5))

    # 3. Position Proximity
    first_occurrences = []
    for word in unique_q:
        if word in t_clean:
            first_occurrences.append(t_clean.find(word))

    proximity_score = 0.0
    if first_occurrences:
        min_pos = min(first_occurrences)
        # Higher score if query terms land in the first 200 characters
        proximity_score = max(0.0, 1.0 - (min_pos / 300.0))

    # 4. Final Hybrid Rerank Fusion
    lexical_score = (phrase_score * 0.35) + (term_overlap * 0.35) + (tf_density * 0.15) + (proximity_score * 0.15)
    rerank_score = (vector_score * 0.40) + (lexical_score * 0.60)

    return round(min(1.0, max(0.0, rerank_score)), 4)


def _rerank_via_voyage_api(query: str, documents: List[str], api_key: str) -> Optional[List[float]]:
    try:
        url = "https://api.voyageai.com/v1/rerank"
        payload = {
            "model": "rerank-2",
            "query": query,
            "documents": documents,
            "top_k": len(documents)
        }
        data = json.dumps(payload).encode('utf-8')
        req = urllib.request.Request(url, data=data, headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}"
        })
        with urllib.request.urlopen(req, timeout=5) as response:
            res_data = json.loads(response.read().decode('utf-8'))
            scores = [0.0] * len(documents)
            for item in res_data.get("data", []):
                idx = item.get("index")
                scores[idx] = float(item.get("relevance_score", 0.0))
            return scores
    except Exception:
        return None


def _rerank_via_cohere_api(query: str, documents: List[str], api_key: str) -> Optional[List[float]]:
    try:
        url = "https://api.cohere.com/v2/rerank"
        payload = {
            "model": "rerank-v3.5",
            "query": query,
            "documents": documents,
            "top_n": len(documents)
        }
        data = json.dumps(payload).encode('utf-8')
        req = urllib.request.Request(url, data=data, headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}"
        })
        with urllib.request.urlopen(req, timeout=5) as response:
            res_data = json.loads(response.read().decode('utf-8'))
            scores = [0.0] * len(documents)
            for item in res_data.get("results", []):
                idx = item.get("index")
                scores[idx] = float(item.get("relevance_score", 0.0))
            return scores
    except Exception:
        return None


def rerank_candidates(
    query: str,
    candidates: List[Dict[str, Any]],
    top_n: int = 5
) -> List[Dict[str, Any]]:
    """
    Re-scores and re-ranks candidate search items using a Cross-Encoder pipeline.

    Supports Voyage/Cohere API reranking if API keys exist, or falls back to
    GigaMind's local token-interaction cross-encoder engine.
    """
    if not candidates:
        return []

    documents = [c.get("content", "") for c in candidates]
    voyage_key = os.getenv("VOYAGE_API_KEY")
    cohere_key = os.getenv("COHERE_API_KEY")

    api_scores: Optional[List[float]] = None

    if voyage_key:
        api_scores = _rerank_via_voyage_api(query, documents, voyage_key)
    elif cohere_key:
        api_scores = _rerank_via_cohere_api(query, documents, cohere_key)

    reranked = []
    for idx, cand in enumerate(candidates):
        item = dict(cand)
        v_score = float(item.get("score", 0.0))
        item["vector_score"] = v_score

        if api_scores and idx < len(api_scores):
            r_score = round(api_scores[idx], 4)
        else:
            r_score = _token_interaction_score(query, item.get("content", ""), v_score)

        item["rerank_score"] = r_score
        item["score"] = r_score
        reranked.append(item)

    reranked.sort(key=lambda x: x["score"], reverse=True)
    return reranked[:top_n]
