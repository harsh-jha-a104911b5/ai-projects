"""Text chunker: tiktoken sliding window with sentence-boundary snapping.

Strategy: 512-token window, 64-token overlap, walk back ≤ 30 tokens to the nearest
sentence boundary (.!?\n) to avoid mid-sentence cuts.
"""

from __future__ import annotations

import re

import tiktoken

ENCODING_NAME = "cl100k_base"  # matches text-embedding-3-small
CHUNK_TOKENS = 512
OVERLAP_TOKENS = 64
SNAP_TOLERANCE_TOKENS = 30

_SENTENCE_END = re.compile(r"[.!?\n]")

_enc: tiktoken.Encoding | None = None


def _encoding() -> tiktoken.Encoding:
    global _enc
    if _enc is None:
        _enc = tiktoken.get_encoding(ENCODING_NAME)
    return _enc


def _snap_to_sentence_end(text: str, enc: tiktoken.Encoding, tolerance: int) -> str:
    """Trim text back to the last sentence boundary within `tolerance` tokens of the end."""
    tokens = enc.encode(text)
    if len(tokens) <= tolerance:
        return text

    # Decode the last `tolerance` tokens and look for a sentence boundary
    tail_tokens = tokens[-tolerance:]
    tail_text = enc.decode(tail_tokens)
    matches = list(_SENTENCE_END.finditer(tail_text))
    if not matches:
        return text  # no boundary found; keep as-is

    last_match = matches[-1]
    # Character position in tail_text where we'll cut
    cut_pos = last_match.start() + 1
    trimmed_tail = tail_text[:cut_pos]
    # Recount tokens for the trimmed tail to get accurate overlap
    trimmed_tail_tokens = enc.encode(trimmed_tail)
    kept_tokens = tokens[: len(tokens) - len(tail_tokens)] + trimmed_tail_tokens
    return enc.decode(kept_tokens)


def chunk_text(
    text: str,
    *,
    chunk_tokens: int = CHUNK_TOKENS,
    overlap_tokens: int = OVERLAP_TOKENS,
    snap_tolerance: int = SNAP_TOLERANCE_TOKENS,
) -> list[str]:
    """Split text into overlapping chunks. Returns list of chunk strings."""
    enc = _encoding()
    all_tokens = enc.encode(text)
    total = len(all_tokens)

    if total == 0:
        return []

    chunks: list[str] = []
    pos = 0

    while pos < total:
        end = min(pos + chunk_tokens, total)
        candidate_text = enc.decode(all_tokens[pos:end])

        # Snap to sentence boundary only when we're not at the end of the document
        if end < total:
            candidate_text = _snap_to_sentence_end(candidate_text, enc, snap_tolerance)

        candidate_text = candidate_text.strip()
        if candidate_text:
            chunks.append(candidate_text)

        # Advance by at least (chunk_tokens - overlap_tokens) to prevent micro-chunks
        # when the overlap window is larger than a short document.
        actual_tokens = len(enc.encode(candidate_text))
        advance = max(actual_tokens - overlap_tokens, chunk_tokens - overlap_tokens, 1)
        pos += advance

    return chunks
