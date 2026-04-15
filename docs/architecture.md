# DCN Architecture — Deep Dive

## Query Lifecycle

```
User Query
    │
    ▼
DCNNode.process(query, domain)
    │
    ├── 1. SafetyGuard.check()
    │       blocked? ──YES──► return "[Blocked: reason]"
    │           │NO
    ├── 2. ResourceManager.register_task()
    │       allocate CPU/net budget + timeout
    │
    ├── 3. MemoryStore.retrieve()   [top-K, topic-segmented]
    │       confidence >= 0.7? ──YES──► return memory hit
    │           │NO
    ├── 4. LocalBrain.answer()      [rule matching]
    │       confidence >= 0.5? ──YES──► store→memory, return
    │           │NO
    ├── 5. Network.route()          [top-3 peers by capability]
    │       responses found?  ──YES──► merge_responses(), store, return
    │           │NO
    └── 6. Fallback                 [partial brain or weak memory]
```

---

## Memory Scoring Formula

```python
score = recency(t) * (1 + min(access_count * 0.2, 2.0)) * confidence * success_weight

recency(t)      = 1 / (1 + age_hours * 0.1)
success_weight  = 1.0 if success else 0.3
confidence      = float in [0.0, 1.0]

Hot capacity  : 200 entries  (RAM)
Cold capacity : 2000 entries (archive)

Eviction : lowest-scored hot entries → cold when hot > 200
Pruning  : cold entries with score < 0.15 are deleted
```

---

## Capability Evolution

```python
On success : strength = min(3.0, strength + 0.05)
On failure : strength = max(0.1, strength - 0.08)

Routing selects top-3 peers with strength > 0.2 for the query domain.

Advertised to peers as:
{
  "node_id": "node-A",
  "capabilities": {
    "math": { "strength": 2.1, "query_count": 42, "success_rate": 0.95 }
  }
}
```

---

## Rule Evolution

```python
On success : rule.strength = min(2.0, rule.strength + 0.1)
On failure : rule.strength = max(0.0, rule.strength - 0.15)
Prune      : rules with strength < 0.2 are removed automatically

New rules injected via:
  node.brain.inject_rule(Rule(rule_id, pattern, response_template, domain, strength))
```

---

## Network Constraints

| Constraint              | Value                              |
|-------------------------|------------------------------------|
| Max network usage       | 25% hard cap                       |
| Peers queried per req   | Top 3 by domain capability         |
| Data shared             | Structured response + cap summary  |
| Never shared            | Model weights, raw memory, queries |
| Task isolation          | Unique task_id, no context bleed   |

---

## Resource Priority Table

```
┌────────────────┬──────────┬───────────┬───────────┐
│ Priority       │ CPU Max  │ Net Max   │ Timeout   │
├────────────────┼──────────┼───────────┼───────────┤
│ System         │ 40%      │  5%       │ 60s       │
│ Foreground     │ 30%      │ 10%       │ 30s       │
│ Local AI       │ 20%      │  5%       │ 10s       │
│ Network Tasks  │ 10%      │ 25%       │ 15s       │
└────────────────┴──────────┴───────────┴───────────┘

Dynamic factor:
  system load > 80%             → ×0.4  (throttle hard)
  system load > 50%             → ×0.7
  system load < 20% + charging  → ×1.3  (boost)
```

---

## Phase Roadmap

```
Phase 1 ✅  Single node   — local brain + memory
Phase 2 ✅  2-node        — capability routing, basic network
Phase 3 ✅  Multi-node    — Top-K merge, network collaboration
Phase 4 🔜  Persistence   — SQLite snapshots, cold memory on disk
Phase 5 🔜  Transport     — gRPC/WebSocket real network
Phase 6 🔜  Embeddings    — optional semantic retrieval layer
Phase 7 🔜  Edge/Android  — battery-aware scheduling, APK packaging
```

---

## Extending DCN

### Add a custom domain node

```python
from src.node.dcn_node import DCNNode
from src.node.local_brain import Rule

node = DCNNode("my-node", ["my_domain"])

node.brain.inject_rule(Rule(
    rule_id="my_rule_1",
    pattern=r"keyword|another pattern",
    response_template="Answer for '{query}': do X then Y.",
    domain="my_domain",
    strength=1.5
))
```

### Swap the transport layer

Replace `DCNNetwork._route()` with any transport:

```python
# gRPC example (pseudocode)
def _route(self, query, exclude):
    stub = dcn_pb2_grpc.NodeServiceStub(channel)
    responses = []
    for peer_addr in self._get_capable_peers(query.domain, exclude):
        resp = stub.HandleQuery(dcn_pb2.QueryRequest(
            task_id=query.task_id,
            query=query.query,
            domain=query.domain
        ))
        responses.append(NodeResponse(
            task_id=resp.task_id,
            node_id=resp.node_id,
            answer=resp.answer,
            confidence=resp.confidence,
            domain=resp.domain,
            answered=resp.answered
        ))
    return responses
```

The `DCNNode` interface stays identical — only the network layer changes.
