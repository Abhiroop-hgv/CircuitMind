"""
Text similarity for unmatched part numbers, with no dependencies.

ORIGIN
------
The hash-embedding idea is taken from CircuitMind's `app/embeddings.py`
(Shruthi-Joshi). Their primary path is `sentence-transformers/all-MiniLM-L6-v2`
with pgvector; the hash embedding is their offline fallback when the model
cannot be downloaded.

WHY THE FALLBACK IS THE PRIMARY PATH HERE
-----------------------------------------
On this machine the real model is not an option. `sentence-transformers` pulls
in torch -- roughly 2 GB installed -- and the laptop has 7.8 GB of RAM with a few
hundred megabytes free; the same constraint that made local LLM inference emit
garbage. pgvector is also not installed for this Postgres.

So: their fallback, run in memory over a 30-part catalogue. Thirty rows is a
list comprehension, not a database index.

WHAT THIS IS AND IS NOT
-----------------------
A hash embedding is NOT semantic. It scores on shared words, not shared meaning.
"Dual op-amp SOIC-8" and "Operational amplifier, 8-pin small outline" describe
the same thing and share almost no tokens, so this will score them near zero.

That is a real limitation and it is why nothing here decides anything. It ranks
candidates for a person to look at. A wrong suggestion costs a glance; a wrong
automatic match ends up on a board.
"""

from __future__ import annotations

import hashlib
import math
import re
from typing import Dict, List, Tuple

DIM = 384  # same as MiniLM, so a real model can replace this without changes


def tokenize(text: str) -> List[str]:
    """Alphanumeric runs, lowercased. Splits STM32F407 into stm32f407."""
    return [t for t in re.split(r"[^a-z0-9]+", (text or "").lower()) if t]


def hash_embed(text: str, dim: int = DIM) -> List[float]:
    """Deterministic bag-of-tokens hash embedding, L2 normalised."""
    vec = [0.0] * dim
    tokens = tokenize(text) or [(text or "").strip().lower()]
    for token in tokens:
        digest = hashlib.sha256(token.encode("utf-8")).digest()
        for i in range(8):
            idx = int.from_bytes(digest[i * 2: i * 2 + 2], "little") % dim
            vec[idx] += 1.0 if digest[i] % 2 == 0 else -1.0
    norm = math.sqrt(sum(v * v for v in vec)) or 1.0
    return [v / norm for v in vec]


def cosine(a: List[float], b: List[float]) -> float:
    return sum(x * y for x, y in zip(a, b))


def jaccard(a: str, b: str) -> float:
    """Plain token overlap. Blunt, but honest about what it measures."""
    sa, sb = set(tokenize(a)), set(tokenize(b))
    if not sa or not sb:
        return 0.0
    return len(sa & sb) / len(sa | sb)


def component_text(row: Dict) -> str:
    """The searchable text for a catalogue part."""
    specs = row.get("specs") or {}
    bits = [row.get("mpn", ""), row.get("manufacturer", ""),
            row.get("category", "").replace("_", " "), row.get("description", ""),
            str(specs.get("package", "")), str(specs.get("footprint_id", ""))]
    return " ".join(b for b in bits if b)


def rank(query: str, rows: List[Dict], top_k: int = 5) -> List[Tuple[Dict, float]]:
    """
    Score every catalogue part against the query text.

    Blends the hash cosine with plain token overlap. The two disagree usefully:
    cosine rewards a lot of shared vocabulary, Jaccard rewards a high proportion
    of it, and a short description should not be punished for being short.
    """
    q_vec = hash_embed(query)
    scored = []
    for row in rows:
        text = component_text(row)
        score = 0.5 * max(0.0, cosine(q_vec, hash_embed(text))) + 0.5 * jaccard(query, text)
        scored.append((row, round(score, 4)))
    scored.sort(key=lambda pair: -pair[1])
    return scored[:top_k]
