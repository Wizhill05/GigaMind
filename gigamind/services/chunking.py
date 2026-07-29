from typing import List, Dict, Any, Optional

def chunk_text(
    text: str,
    chunk_size: int = 500,
    chunk_overlap: int = 100,
    min_threshold: int = 600
) -> List[Dict[str, Any]]:
    """
    Recursively splits text into dense, semantic chunks with sliding window overlaps.

    If text length is below min_threshold, returns a single chunk containing the original text.
    Otherwise, uses hierarchical separators (\n\n, \n, sentence ends, words) to produce
    chunks of approximate size chunk_size with chunk_overlap characters preserved across boundaries.
    """
    cleaned_text = (text or "").strip()
    if not cleaned_text:
        return []

    if len(cleaned_text) <= min_threshold:
        return [{
            "content": cleaned_text,
            "chunk_index": 0,
            "total_chunks": 1,
            "start_char": 0,
            "end_char": len(cleaned_text)
        }]

    separators = ["\n\n", "\n", ". ", "? ", "! ", "; ", " ", ""]

    def _split_text(input_str: str, seps: List[str]) -> List[str]:
        if not input_str:
            return []
        if not seps:
            return list(input_str)

        sep = seps[0]
        next_seps = seps[1:]

        if sep == "":
            return list(input_str)

        splits = input_str.split(sep)
        final_pieces = []
        for i, piece in enumerate(splits):
            if not piece:
                continue
            # Re-attach separator to piece except last if applicable
            attached = piece + (sep if i < len(splits) - 1 else "")
            if len(attached) <= chunk_size:
                final_pieces.append(attached)
            else:
                # Recursively split with remaining separators
                sub_splits = _split_text(attached, next_seps)
                final_pieces.extend(sub_splits)
        return final_pieces

    atomic_pieces = _split_text(cleaned_text, separators)

    raw_chunks: List[str] = []
    current_chunk = ""

    for piece in atomic_pieces:
        if len(current_chunk) + len(piece) <= chunk_size:
            current_chunk += piece
        else:
            if current_chunk.strip():
                raw_chunks.append(current_chunk.strip())

            # Carry over chunk_overlap characters for sliding window context
            overlap_prefix = ""
            if chunk_overlap > 0 and len(current_chunk) > chunk_overlap:
                overlap_prefix = current_chunk[-chunk_overlap:]
                # Try to align overlap to start at word boundary
                space_idx = overlap_prefix.find(" ")
                if space_idx != -1 and space_idx < len(overlap_prefix) - 1:
                    overlap_prefix = overlap_prefix[space_idx + 1:]

            current_chunk = overlap_prefix + piece

    if current_chunk.strip():
        raw_chunks.append(current_chunk.strip())

    total = len(raw_chunks)
    result: List[Dict[str, Any]] = []

    current_search_idx = 0
    for idx, c_text in enumerate(raw_chunks):
        start_char = cleaned_text.find(c_text[:30], current_search_idx)
        if start_char == -1:
            start_char = current_search_idx
        end_char = start_char + len(c_text)
        current_search_idx = max(start_char, current_search_idx)

        result.append({
            "content": c_text,
            "chunk_index": idx,
            "total_chunks": total,
            "start_char": start_char,
            "end_char": end_char
        })

    return result
