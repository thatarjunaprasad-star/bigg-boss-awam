"""Deterministic word-level tokenizer for the Awam inference engine.

Stands in for the model tokenizer when no torch/HF stack is present; keeps
token accounting (and therefore KV cache geometry) real.
"""
from __future__ import annotations

import re
import zlib
from dataclasses import dataclass

VOCAB_SIZE = 32000
_TOKEN_RE = re.compile(r"\w+|[^\w\s]", re.UNICODE)


@dataclass(frozen=True)
class Token:
    id: int
    piece: str


def tokenize(text: str) -> list[Token]:
    tokens: list[Token] = []
    for piece in _TOKEN_RE.findall(text):
        token_id = zlib.crc32(piece.lower().encode("utf-8")) % (VOCAB_SIZE - 256) + 256
        tokens.append(Token(id=token_id, piece=piece))
    return tokens


def token_ids(text: str) -> list[int]:
    return [t.id for t in tokenize(text)]


def count_tokens(text: str) -> int:
    return len(_TOKEN_RE.findall(text))


def detokenize(tokens: list[Token]) -> str:
    return " ".join(t.piece for t in tokens)
