"""
network/network.py
DCN Network Layer — node registry, capability-based routing, query dispatch.
No global model sharing. Only structured responses + capability summaries shared.
"""

import time
import threading
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from node.dcn_node import DCNNode, DCNQuery, NodeResponse


class DCNNetwork:
    """
    In-process network bus for the DCN prototype.
    In production, replace with gRPC / WebSocket / message queue.
    Each node registers itself; the network routes queries by capability score.
    """

    def __init__(self):
        self._nodes: dict[str, "DCNNode"] = {}
        self._lock = threading.Lock()
        self._route_log: list[dict] = []

    # ─── Node registration ────────────────────────────────────────────────────

    def register(self, node: "DCNNode"):
        with self._lock:
            self._nodes[node.node_id] = node
            # Wire the node's network send function
            node.register_network(self._make_send_fn(node.node_id))

    def deregister(self, node_id: str):
        with self._lock:
            self._nodes.pop(node_id, None)

    # ─── Routing ──────────────────────────────────────────────────────────────

    def _make_send_fn(self, originator_id: str):
        """Returns a closure that routes queries from a specific node."""
        def send(query: "DCNQuery") -> list["NodeResponse"]:
            return self._route(query, exclude=originator_id)
        return send

    def _route(self, query: "DCNQuery", exclude: str) -> list["NodeResponse"]:
        """Route to top-N capable nodes. Strict task isolation — no context bleed."""
        with self._lock:
            peers = {nid: n for nid, n in self._nodes.items() if nid != exclude}

        if not peers:
            return []

        # Score each peer by domain capability
        scored = []
        for nid, node in peers.items():
            strength = node.capabilities.get_strength(query.domain)
            if strength > 0.2:
                scored.append((strength, nid, node))

        # Sort by strength, pick top 3
        scored.sort(key=lambda x: x[0], reverse=True)
        top_nodes = scored[:3]

        responses = []
        for _, nid, node in top_nodes:
            try:
                resp = node.handle_routed_query(query)
                responses.append(resp)
                self._log_route(query.task_id, exclude, nid, resp.confidence)
            except Exception as e:
                self._log_route(query.task_id, exclude, nid, 0.0, error=str(e))

        return responses

    def _log_route(self, task_id: str, from_id: str, to_id: str,
                   confidence: float, error: str = ""):
        self._route_log.append({
            "task_id": task_id,
            "from": from_id,
            "to": to_id,
            "confidence": round(confidence, 3),
            "error": error,
            "time": round(time.time(), 3)
        })
        # Keep log bounded
        if len(self._route_log) > 500:
            self._route_log = self._route_log[-500:]

    # ─── Broadcast ────────────────────────────────────────────────────────────

    def broadcast_capability_update(self, node_id: str):
        """Notify all nodes of a capability advertisement (summaries only)."""
        source = self._nodes.get(node_id)
        if not source:
            return
        advert = source.capabilities.advertise()
        # Peers receive summary — no model weights, no raw memory
        for nid, node in self._nodes.items():
            if nid != node_id:
                # Nodes can optionally use this to build routing tables
                # (no-op in this prototype; routing uses live capability queries)
                pass

    # ─── Diagnostics ──────────────────────────────────────────────────────────

    def topology(self) -> dict:
        return {
            "node_count": len(self._nodes),
            "nodes": {
                nid: {
                    "domains": n.domains,
                    "capabilities": n.capabilities.advertise()["capabilities"]
                }
                for nid, n in self._nodes.items()
            }
        }

    def recent_routes(self, n: int = 20) -> list[dict]:
        return self._route_log[-n:]

    def node_count(self) -> int:
        return len(self._nodes)
