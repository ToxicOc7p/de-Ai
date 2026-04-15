"""
memory/memory_store.py
DCN Memory System — hot/cold storage with scoring + pruning
"""

import time
import json
import hashlib
from collections import defaultdict
from dataclasses import dataclass, field, asdict
from typing import Any, Optional


@dataclass
class MemoryEntry:
    entry_id: str
    topic: str
    query: str
    answer: str
    confidence: float
    timestamp: float = field(default_factory=time.time)
    access_count: int = 0
    last_accessed: float = field(default_factory=time.time)
    success: bool = True
    score: float = 0.0

    def compute_score(self) -> float:
        """Score = frequency * recency_decay * confidence * success_weight"""
        now = time.time()
        age_hours = (now - self.timestamp) / 3600
        recency = 1.0 / (1.0 + age_hours * 0.1)
        freq_boost = min(self.access_count * 0.2, 2.0)
        success_weight = 1.0 if self.success else 0.3
        self.score = recency * (1.0 + freq_boost) * self.confidence * success_weight
        return self.score


class MemoryStore:
    """
    Two-tier memory:
      hot  — dict in RAM, fast access, limited size
      cold — dict archive, lower priority, pruned aggressively
    """

    HOT_CAPACITY = 200
    COLD_CAPACITY = 2000
    PRUNE_THRESHOLD = 0.15  # entries below this score get pruned

    def __init__(self):
        self.hot: dict[str, MemoryEntry] = {}       # entry_id -> MemoryEntry
        self.cold: dict[str, MemoryEntry] = {}
        self.index: dict[str, list[str]] = defaultdict(list)  # topic -> [entry_ids]

    # ─── Write ────────────────────────────────────────────────────────────────

    def store(self, topic: str, query: str, answer: str,
              confidence: float = 1.0, success: bool = True) -> str:
        entry_id = self._make_id(topic, query)
        if entry_id in self.hot:
            e = self.hot[entry_id]
            e.access_count += 1
            e.answer = answer
            e.confidence = max(e.confidence, confidence)
            e.success = success
            e.compute_score()
            return entry_id

        entry = MemoryEntry(
            entry_id=entry_id, topic=topic, query=query,
            answer=answer, confidence=confidence, success=success
        )
        entry.compute_score()
        self.hot[entry_id] = entry
        self.index[topic].append(entry_id)

        if len(self.hot) > self.HOT_CAPACITY:
            self._evict_to_cold()
        return entry_id

    # ─── Read ─────────────────────────────────────────────────────────────────

    def retrieve(self, topic: str, query: str, top_k: int = 5) -> list[MemoryEntry]:
        """Top-K retrieval by score within topic segment — never full scan."""
        candidates: list[MemoryEntry] = []
        for eid in self.index.get(topic, []):
            e = self.hot.get(eid) or self.cold.get(eid)
            if e is None:
                continue
            e.access_count += 1
            e.last_accessed = time.time()
            e.compute_score()
            # Simple relevance: shared tokens between query and stored query
            rel = self._token_overlap(query, e.query)
            if rel > 0:
                candidates.append((rel * e.score, e))

        candidates.sort(key=lambda x: x[0], reverse=True)
        return [e for _, e in candidates[:top_k]]

    def retrieve_by_id(self, entry_id: str) -> Optional[MemoryEntry]:
        return self.hot.get(entry_id) or self.cold.get(entry_id)

    # ─── Maintenance ──────────────────────────────────────────────────────────

    def prune(self):
        """Remove low-value entries from cold storage."""
        before = len(self.cold)
        self.cold = {
            eid: e for eid, e in self.cold.items()
            if e.compute_score() >= self.PRUNE_THRESHOLD
        }
        removed = before - len(self.cold)
        self._rebuild_index()
        return removed

    def _evict_to_cold(self):
        """Move lowest-scoring hot entries to cold."""
        sorted_hot = sorted(self.hot.items(), key=lambda x: x[1].score)
        evict_count = max(1, len(self.hot) - self.HOT_CAPACITY + 20)
        for eid, entry in sorted_hot[:evict_count]:
            del self.hot[eid]
            if entry.score >= self.PRUNE_THRESHOLD:
                self.cold[eid] = entry
            if len(self.cold) > self.COLD_CAPACITY:
                self._prune_cold_fast()

    def _prune_cold_fast(self):
        sorted_cold = sorted(self.cold.items(), key=lambda x: x[1].score)
        for eid, _ in sorted_cold[:100]:
            del self.cold[eid]

    def _rebuild_index(self):
        self.index = defaultdict(list)
        for eid, e in {**self.hot, **self.cold}.items():
            self.index[e.topic].append(eid)

    # ─── Helpers ──────────────────────────────────────────────────────────────

    @staticmethod
    def _make_id(topic: str, query: str) -> str:
        h = hashlib.md5(f"{topic}:{query.lower().strip()}".encode()).hexdigest()
        return h[:12]

    @staticmethod
    def _token_overlap(a: str, b: str) -> float:
        ta = set(a.lower().split())
        tb = set(b.lower().split())
        if not ta or not tb:
            return 0.0
        return len(ta & tb) / len(ta | tb)

    def stats(self) -> dict:
        return {
            "hot_count": len(self.hot),
            "cold_count": len(self.cold),
            "topics": list(self.index.keys()),
            "total": len(self.hot) + len(self.cold)
        }

    def export(self) -> dict:
        return {
            "hot": {k: asdict(v) for k, v in self.hot.items()},
            "cold": {k: asdict(v) for k, v in self.cold.items()}
        }

    def load(self, data: dict):
        for k, v in data.get("hot", {}).items():
            self.hot[k] = MemoryEntry(**v)
        for k, v in data.get("cold", {}).items():
            self.cold[k] = MemoryEntry(**v)
        self._rebuild_index()
