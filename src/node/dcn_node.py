"""
node/dcn_node.py
DCN Node — the primary intelligence unit.
Phases 1-3: local memory + brain, network routing, response merging.
"""

import uuid
import time
from dataclasses import dataclass, field
from typing import Optional, Callable

from node.local_brain import LocalBrain
from node.capability import CapabilityRegistry
from memory.memory_store import MemoryStore
from safety.safety_guard import SafetyGuard
from utils.resource_manager import ResourceManager, Priority


# ─── Query / Response types ───────────────────────────────────────────────────

@dataclass
class DCNQuery:
    query: str
    domain: str
    task_id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    context_scope: str = "local"       # "local" | "network" | "broadcast"
    originator_id: str = ""
    timestamp: float = field(default_factory=time.time)


@dataclass
class NodeResponse:
    task_id: str
    node_id: str
    answer: str
    confidence: float
    domain: str
    from_memory: bool = False
    answered: bool = False
    latency_ms: float = 0.0


@dataclass
class MergedResponse:
    task_id: str
    answer: str
    confidence: float
    contributors: list[str]
    source: str        # "memory" | "local_brain" | "network" | "merged"


# ─── Node ─────────────────────────────────────────────────────────────────────

class DCNNode:
    """
    A single DCN node. Wires together brain, memory, capabilities, and safety.
    Network communication uses pluggable send/receive callbacks (no hard coupling).
    """

    def __init__(
        self,
        node_id: str,
        domains: list[str],
        domain_strengths: dict[str, float] | None = None,
        resource_manager: ResourceManager | None = None,
    ):
        self.node_id = node_id
        self.domains = domains

        self.brain = LocalBrain(node_id, domains)
        self.memory = MemoryStore()
        self.capabilities = CapabilityRegistry(
            node_id,
            initial_domains=domain_strengths or {d: 1.0 for d in domains}
        )
        self.safety = SafetyGuard(node_id)
        self.resources = resource_manager or ResourceManager()

        # Network layer (injected externally for loose coupling)
        self._network_send: Optional[Callable] = None   # fn(query) -> list[NodeResponse]
        self._peers: list[str] = []

    # ─── Public API ───────────────────────────────────────────────────────────

    def process(self, query: str, domain: str = "general") -> MergedResponse:
        """Main entry point. Handles a query end-to-end."""
        t0 = time.time()
        task_id = str(uuid.uuid4())[:8]
        dcn_q = DCNQuery(
            query=query, domain=domain,
            task_id=task_id, originator_id=self.node_id
        )

        # 1. Safety check
        allowed, reason = self.safety.check(query, domain, "process")
        if not allowed:
            return MergedResponse(task_id, f"[Blocked: {reason}]", 0.0, [], "safety")

        # 2. Register task
        self.resources.register_task(task_id, Priority.LOCAL_AI)

        # 3. Memory-first lookup
        mem_hits = self.memory.retrieve(domain, query, top_k=3)
        if mem_hits and mem_hits[0].confidence >= 0.7:
            best = mem_hits[0]
            self.resources.complete(task_id)
            return MergedResponse(
                task_id=task_id,
                answer=best.answer,
                confidence=best.confidence,
                contributors=[self.node_id],
                source="memory"
            )

        # 4. Local brain
        brain_resp = self.brain.answer(query, domain)
        if brain_resp.answered and brain_resp.confidence >= 0.5:
            self.memory.store(domain, query, brain_resp.answer,
                              brain_resp.confidence, True)
            self.capabilities.record(domain, True)
            self.resources.complete(task_id)
            return MergedResponse(
                task_id=task_id,
                answer=brain_resp.answer,
                confidence=brain_resp.confidence,
                contributors=[self.node_id],
                source="local_brain"
            )

        # 5. Network routing (Phase 2+)
        if self._network_send is not None:
            net_responses = self._network_send(dcn_q)
            if net_responses:
                merged = self._merge_responses(task_id, net_responses, brain_resp)
                self.memory.store(domain, query, merged.answer, merged.confidence, True)
                self.resources.complete(task_id)
                return merged

        # 6. Best-effort from partial brain or memory
        fallback = (
            brain_resp.answer if brain_resp.answered
            else (mem_hits[0].answer if mem_hits else "Insufficient knowledge to answer.")
        )
        conf = brain_resp.confidence if brain_resp.answered else 0.2
        self.capabilities.record(domain, conf > 0.3)
        self.resources.complete(task_id)
        return MergedResponse(task_id, fallback, conf, [self.node_id], "fallback")

    def handle_routed_query(self, dcn_q: DCNQuery) -> NodeResponse:
        """Called by the network when another node routes a query here."""
        t0 = time.time()
        allowed, reason = self.safety.check(dcn_q.query, dcn_q.domain, "routed")
        if not allowed:
            return NodeResponse(dcn_q.task_id, self.node_id, "", 0.0, dcn_q.domain)

        mem_hits = self.memory.retrieve(dcn_q.domain, dcn_q.query, top_k=2)
        if mem_hits and mem_hits[0].confidence >= 0.6:
            best = mem_hits[0]
            return NodeResponse(
                dcn_q.task_id, self.node_id, best.answer,
                best.confidence, dcn_q.domain, from_memory=True,
                answered=True, latency_ms=(time.time()-t0)*1000
            )

        brain_resp = self.brain.answer(dcn_q.query, dcn_q.domain)
        return NodeResponse(
            dcn_q.task_id, self.node_id,
            brain_resp.answer, brain_resp.confidence,
            dcn_q.domain, from_memory=False,
            answered=brain_resp.answered,
            latency_ms=(time.time()-t0)*1000
        )

    # ─── Network plumbing ─────────────────────────────────────────────────────

    def register_network(self, send_fn: Callable):
        """Inject network send function. Keeps node decoupled from transport."""
        self._network_send = send_fn

    # ─── Response merging (Phase 3) ───────────────────────────────────────────

    def _merge_responses(
        self,
        task_id: str,
        responses: list[NodeResponse],
        local: "BrainResponse | None" = None
    ) -> MergedResponse:
        """Top-K merge: pick best by confidence, combine if top two agree."""
        candidates = [r for r in responses if r.answered and r.confidence > 0.3]

        # Add local if decent
        if local and local.answered and local.confidence > 0.3:
            candidates.append(NodeResponse(
                task_id, self.node_id, local.answer,
                local.confidence, "", answered=True
            ))

        if not candidates:
            return MergedResponse(task_id, "No confident answer available.", 0.1, [], "merged")

        # Sort by confidence descending — top-K = 3
        top = sorted(candidates, key=lambda r: r.confidence, reverse=True)[:3]
        best = top[0]

        # If top-2 have similar confidence — blend answers
        if len(top) >= 2 and abs(top[0].confidence - top[1].confidence) < 0.1:
            combined = f"{top[0].answer}\n[Alt: {top[1].answer}]"
            conf = (top[0].confidence + top[1].confidence) / 2
            contributors = [r.node_id for r in top[:2]]
            return MergedResponse(task_id, combined, conf, contributors, "merged")

        return MergedResponse(
            task_id, best.answer, best.confidence,
            [best.node_id], "network"
        )

    # ─── Status ───────────────────────────────────────────────────────────────

    def status(self) -> dict:
        return {
            "node_id": self.node_id,
            "domains": self.domains,
            "capabilities": self.capabilities.advertise(),
            "memory": self.memory.stats(),
            "resources": self.resources.status(),
            "rules": len(self.brain.rules),
        }
