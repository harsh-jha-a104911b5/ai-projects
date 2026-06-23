"""Unit tests for the text chunker. No I/O."""

from __future__ import annotations

import pytest
import tiktoken

from rag.chunker import ENCODING_NAME, chunk_text


def _token_count(text: str) -> int:
    enc = tiktoken.get_encoding(ENCODING_NAME)
    return len(enc.encode(text))


def test_empty_input_returns_empty():
    assert chunk_text("") == []


def test_short_text_produces_one_chunk():
    text = "Hello, this is a short sentence."
    chunks = chunk_text(text)
    assert len(chunks) == 1
    assert chunks[0].strip() == text.strip()


def test_chunks_are_non_empty():
    text = " ".join(["word"] * 600)
    chunks = chunk_text(text)
    assert all(len(c) > 0 for c in chunks)


def test_chunk_token_count_within_limit():
    # Generate text longer than one chunk
    text = "This is a complete sentence. " * 50
    chunks = chunk_text(text, chunk_tokens=128, overlap_tokens=16)
    for chunk in chunks:
        assert _token_count(chunk) <= 128 + 16  # small tolerance for snapping


def test_multiple_chunks_for_long_text():
    text = "This is a sentence that ends here. " * 100
    chunks = chunk_text(text, chunk_tokens=64, overlap_tokens=8)
    assert len(chunks) > 1


def test_overlap_means_consecutive_chunks_share_content():
    """With overlap, adjacent chunks should share some tokens."""
    text = "Alpha beta gamma delta epsilon. " * 40
    chunks = chunk_text(text, chunk_tokens=32, overlap_tokens=8)
    if len(chunks) < 2:
        pytest.skip("Text too short to produce multiple chunks at these settings")

    enc = tiktoken.get_encoding(ENCODING_NAME)
    tokens_a = set(enc.encode(chunks[0]))
    tokens_b = set(enc.encode(chunks[1]))
    assert tokens_a & tokens_b, "Adjacent chunks share no tokens — overlap may be broken"


def test_output_covers_input_content():
    """All significant words from input should appear in at least one chunk."""
    words = [f"uniqueword{i}" for i in range(20)]
    text = ". ".join(words) + "."
    chunks = chunk_text(text, chunk_tokens=32, overlap_tokens=4)
    combined = " ".join(chunks)
    for word in words:
        assert word in combined, f"'{word}' not found in any chunk"


def test_sentence_snapping_does_not_cut_mid_word():
    text = "Short sentence one. Short sentence two. Short sentence three. " * 5
    chunks = chunk_text(text, chunk_tokens=32, overlap_tokens=4, snap_tolerance=10)
    for chunk in chunks:
        # A mid-word cut would leave a token without surrounding spaces at start/end
        # Basic sanity: no chunk ends in the middle of "sentence"
        stripped = chunk.rstrip()
        assert not stripped.endswith("sentenc"), f"Chunk appears cut mid-word: {stripped!r}"
