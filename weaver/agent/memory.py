"""Failure memory — Step O2/O3.

Persistent, local, retrieval-first repair. Query before any inference: on
similarity above 0.85, apply the stored patch and verify -- zero model
calls. On a memory-hit verification failure, decrement confidence and fall
through to normal repair.

Embeddings come from the local `nomic-embed-text` model over loopback --
no embedding API (DC-1/NFR-8/NFR-10, same offline requirement as J1).
Storage is a flat JSON file: cosine similarity over a few dozen cases does
not need a real vector database, and a file-backed index keeps this
credential-free and inspectable, which matters more for a judge-facing
demo than ANN throughput would.
"""

from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass, field
from pathlib import Path

import requests

from weaver.agent.signature import SymptomSignature

OLLAMA_HOST = "http://127.0.0.1:11434"
EMBED_MODEL = "nomic-embed-text"
SIMILARITY_THRESHOLD = 0.85


def embed(text: str, host: str = OLLAMA_HOST) -> list[float]:
    resp = requests.post(f"{host}/api/embeddings", json={"model": EMBED_MODEL, "prompt": text}, timeout=60)
    resp.raise_for_status()
    return resp.json()["embedding"]


def cosine_similarity(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


@dataclass
class MemoryCase:
    case_id: str
    signature: SymptomSignature
    embedding: list[float]
    defect_class: str
    normalized_construct: str
    root_cause: str
    patch_description: str
    patch_body_template: str  # the verified-correct construct, as reusable Java text
    verification_status: str  # "verified" | "unverified"
    hit_count: int
    confidence: float
    provenance: str  # where this case actually came from (O3: no fabricated entries)


@dataclass
class FailureMemory:
    store_path: Path
    cases: list[MemoryCase] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.store_path = Path(self.store_path)
        if self.store_path.exists():
            raw = json.loads(self.store_path.read_text())
            self.cases = [
                MemoryCase(**{**c, "signature": SymptomSignature(**c["signature"])})
                for c in raw
            ]

    def save(self) -> None:
        self.store_path.parent.mkdir(parents=True, exist_ok=True)
        payload = [
            {**asdict(c), "signature": asdict(c.signature)}
            for c in self.cases
        ]
        self.store_path.write_text(json.dumps(payload, indent=2))

    def query(self, signature: SymptomSignature) -> tuple[MemoryCase, float] | None:
        """Query before any inference. Returns the best match above
        SIMILARITY_THRESHOLD, or None -- a None result means the caller
        must fall through to normal (deterministic or model-assisted)
        repair.
        """
        if not self.cases:
            return None
        query_embedding = embed(signature.as_text())
        best: tuple[MemoryCase, float] | None = None
        for case in self.cases:
            sim = cosine_similarity(query_embedding, case.embedding)
            if sim >= SIMILARITY_THRESHOLD and (best is None or sim > best[1]):
                best = (case, sim)
        return best

    def write_back(self, case: MemoryCase) -> None:
        """Write back a verified repair (O2.5)."""
        self.cases.append(case)
        self.save()

    def record_hit(self, case_id: str, verified: bool) -> None:
        for c in self.cases:
            if c.case_id == case_id:
                if verified:
                    c.hit_count += 1
                else:
                    c.confidence = max(0.0, c.confidence - 0.2)
                self.save()
                return
