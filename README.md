# 🧠 DCN — Decentralized Cognitive Network

> **Original concept and architecture by the DCN Project Author.**
> See [LICENSE](./LICENSE) for attribution requirements before using this in your work.

[![License: DAL v1.0](https://img.shields.io/badge/License-DAL%20v1.0-blue.svg)](./LICENSE)
[![Python 3.11+](https://img.shields.io/badge/Python-3.11+-green.svg)](https://python.org)
[![No ML Training](https://img.shields.io/badge/Training-None%20Required-orange.svg)]()
[![Offline First](https://img.shields.io/badge/Mode-Offline%20First-purple.svg)]()

---

## 💡 What Is DCN?

**DCN (Decentralized Cognitive Network)** is a distributed AI architecture where intelligence does **not** live in a single central model. Instead, it **emerges** from a network of small, specialized nodes that:

- Each hold **partial knowledge**
- Reason locally using **rule-based engines** (no heavy ML)
- **Collaborate** over a lightweight network when local knowledge is insufficient
- **Learn** by accumulating and scoring memories — no parameter training ever

Think of it like a hive mind built from minimal units. No node is smart alone. Together, they handle complex queries.

---

## 🏗️ Architecture Overview

```
┌─────────────────────────────────────────────────────┐
│                   DCN Network Bus                    │
│  (capability-aware routing, structured responses)    │
└──────────┬──────────┬──────────┬────────────────────┘
           │          │          │
    ┌──────▼──┐ ┌─────▼───┐ ┌───▼─────┐
    │ Node-A  │ │ Node-B  │ │ Node-C  │  ...
    │ [math]  │ │ [net]   │ │[android]│
    └─────────┘ └─────────┘ └─────────┘
    Each node contains:
    ├── Local Brain     (rule engine, evolving strengths)
    ├── Memory Store    (hot/cold, scored, pruned)
    ├── Capability Reg  (domain strengths, auto-evolve)
    ├── Safety Guard    (permission checks, audit log)
    └── Resource Mgr    (priority, network cap 25%)
```

---

## 🧩 Core Components

### 1. Local Brain (`src/node/local_brain.py`)
- Rule-based reasoning engine — zero ML training
- Rules carry **strength scores**: reinforced on success (+0.1), weakened on failure (-0.15)
- Rules with strength < 0.2 are **automatically pruned**
- New rules injectable at runtime via `node.brain.inject_rule()`

### 2. Memory System (`src/memory/memory_store.py`)

| Tier | Location | Capacity | Speed |
|------|----------|----------|-------|
| Hot  | RAM dict | 200 entries | O(1) |
| Cold | Archive  | 2000 entries | O(1) |

Scoring formula:
```
score = recency_decay × (1 + freq_boost) × confidence × success_weight
recency_decay  = 1 / (1 + age_hours × 0.1)
freq_boost     = min(access_count × 0.2, 2.0)
success_weight = 1.0 if success else 0.3
```
Entries below score 0.15 are pruned. Topic-based segmentation prevents full-memory scans.

### 3. Capability Registry (`src/node/capability.py`)
- Declares domains (e.g. `math`, `networking`, `android`)
- Strength evolves: +0.05 on success, -0.08 on failure, capped at [0.1, 3.0]
- Used by network to route queries to best-fit nodes

### 4. Network Layer (`src/network/network.py`)
- **No global model sharing** — only structured responses + capability summaries shared
- Top-3 capable peers selected per domain per query
- Strict task isolation — unique `task_id` per query, no context bleed
- Pluggable transport: swap `DCNNetwork` internals for gRPC/WebSocket in production

### 5. Response Merging (`src/node/dcn_node.py`)
- Top-K merge sorted by confidence
- If top-2 nodes within 0.1 confidence → answers are blended
- Otherwise single best answer returned

### 6. Safety Guard (`src/safety/safety_guard.py`)
- Blocks domains: `auth`, `finance`, `credentials`, `private`
- Regex-blocks: passwords, API keys, SSNs, bank account patterns, private keys
- All actions logged with SHA-256 query hash (never stores raw queries in log)

### 7. Resource Manager (`src/utils/resource_manager.py`)
```
Priority order (highest → lowest):
  1. System services    40% CPU,  5% net, 60s timeout
  2. Foreground apps    30% CPU, 10% net, 30s timeout
  3. Local AI           20% CPU,  5% net, 10s timeout
  4. Network tasks      10% CPU, 25% net, 15s timeout  ← hard cap

Dynamic scaling:
  load > 80%           → ×0.4  (throttle hard)
  load > 50%           → ×0.7
  load < 20% + charging → ×1.3  (boost)

Tasks are: small, interruptible, resumable (checkpoint/resume API)
```

---

## 🚀 Quickstart

### Requirements
```
Python 3.11+   # Zero external dependencies
```

### Run all phases
```bash
cd de-ai
python tests/test_phase1.py   # single node
python tests/test_phase2.py   # 2-node routing
python tests/test_phase3.py   # 5-node collaboration + merging
```

### Use in code
```python
from src.node.dcn_node import DCNNode
from src.network.network import DCNNetwork

net = DCNNetwork()

node_math = DCNNode("math-node", ["math", "general"],
                    domain_strengths={"math": 2.0, "general": 1.0})
node_net  = DCNNode("net-node",  ["networking", "android"],
                    domain_strengths={"networking": 2.0, "android": 1.5})

net.register(node_math)
net.register(node_net)

# Query any node — it routes automatically to the right specialist
resp = node_math.process("How does the TCP handshake work?", "networking")
print(resp.answer)
print(f"source={resp.source}  confidence={resp.confidence:.2f}  contributors={resp.contributors}")
```

---

## 📁 File Structure

```
de-ai/
├── LICENSE                              # DCN Attribution License v1.0
├── README.md
├── .gitignore
├── .github/workflows/test.yml           # CI — runs all 3 phases
├── src/
│   ├── __init__.py
│   ├── node/
│   │   ├── __init__.py
│   │   ├── dcn_node.py                  # Main node: process, route, merge
│   │   ├── local_brain.py               # Rule engine with evolving strengths
│   │   └── capability.py                # Domain capability registry
│   ├── memory/
│   │   ├── __init__.py
│   │   └── memory_store.py              # Hot/cold memory, scoring, pruning
│   ├── network/
│   │   ├── __init__.py
│   │   └── network.py                   # Network bus, routing, topology
│   ├── retrieval/
│   │   ├── __init__.py
│   │   └── retrieval_engine.py          # Top-K segmented retrieval
│   ├── safety/
│   │   ├── __init__.py
│   │   └── safety_guard.py              # Permissions, blocked patterns, audit log
│   └── utils/
│       ├── __init__.py
│       └── resource_manager.py          # Priority system, dynamic throttling
├── tests/
│   ├── test_phase1.py                   # Phase 1: single node
│   ├── test_phase2.py                   # Phase 2: 2-node routing
│   └── test_phase3.py                   # Phase 3: multi-node + merging
├── examples/
│   └── custom_node.py                   # How to extend with custom domains/rules
└── docs/
    └── architecture.md                  # Deep-dive: query lifecycle, formulas, roadmap
```

---

## 🔭 Roadmap

| Phase | Status | Description |
|-------|--------|-------------|
| 1 | ✅ Done | Single node: local brain + memory |
| 2 | ✅ Done | 2-node routing + capability matching |
| 3 | ✅ Done | Multi-node collaboration + Top-K merging |
| 4 | 🔜 Planned | Persistent memory (SQLite / JSON snapshots) |
| 5 | 🔜 Planned | Real network transport (gRPC / WebSocket) |
| 6 | 🔜 Planned | Optional semantic embedding layer |
| 7 | 🔜 Planned | Android / edge device deployment |

---

## 🧠 Design Philosophy

> "Intelligence doesn't need to be monolithic."

1. **No training required** — learning = memory accumulation + rule scoring
2. **No single point of failure** — remove any node, network adapts
3. **Privacy by design** — no raw data leaves a node; only summaries shared

---

## 📜 License & Attribution

Released under the **DCN Attribution License (DAL) v1.0**.

If you use this code, architecture, or concept in any project, paper, or product:
- Credit: *"Based on the Decentralized Cognitive Network (DCN) — original concept by ToxC7"*
- Link back to this repository in your documentation

See [LICENSE](./LICENSE) for full terms.
