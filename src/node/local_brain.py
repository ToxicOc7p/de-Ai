"""
node/local_brain.py
DCN Local Brain — rule-based reasoning engine, no ML training required.
Rules evolve: reinforced on success, removed on repeated failure.
"""

import re
import time
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Rule:
    rule_id: str
    pattern: str          # regex or keyword pattern
    response_template: str
    domain: str
    strength: float = 1.0  # 0..2, reinforced/weakened over time
    hits: int = 0
    failures: int = 0
    created_at: float = field(default_factory=time.time)

    def reinforce(self, delta: float = 0.1):
        self.strength = min(2.0, self.strength + delta)
        self.hits += 1

    def weaken(self, delta: float = 0.15):
        self.strength = max(0.0, self.strength - delta)
        self.failures += 1

    def is_alive(self) -> bool:
        return self.strength > 0.2

    def matches(self, query: str) -> bool:
        try:
            return bool(re.search(self.pattern, query, re.IGNORECASE))
        except re.error:
            return self.pattern.lower() in query.lower()


@dataclass
class BrainResponse:
    answer: str
    confidence: float
    rule_id: Optional[str]
    domain: str
    answered: bool


class LocalBrain:
    """
    Lightweight rule engine. Each node has its own rule set.
    Rules are seeded at init; new rules can be injected from network consensus.
    """

    def __init__(self, node_id: str, domains: list[str]):
        self.node_id = node_id
        self.domains = domains
        self.rules: dict[str, Rule] = {}
        self._seed_default_rules()

    # ─── Query ────────────────────────────────────────────────────────────────

    def answer(self, query: str, domain: str) -> BrainResponse:
        if domain not in self.domains:
            return BrainResponse("", 0.0, None, domain, False)

        matched = self._find_best_rule(query, domain)
        if matched is None:
            return BrainResponse("", 0.0, None, domain, False)

        answer = self._apply_rule(matched, query)
        confidence = min(0.95, 0.4 + matched.strength * 0.3)
        matched.reinforce(0.05)
        return BrainResponse(answer, confidence, matched.rule_id, domain, True)

    def feedback(self, rule_id: str, success: bool):
        rule = self.rules.get(rule_id)
        if rule is None:
            return
        if success:
            rule.reinforce(0.1)
        else:
            rule.weaken(0.15)

    def prune_weak_rules(self):
        dead = [rid for rid, r in self.rules.items() if not r.is_alive()]
        for rid in dead:
            del self.rules[rid]
        return len(dead)

    def inject_rule(self, rule: Rule):
        self.rules[rule.rule_id] = rule

    # ─── Internals ────────────────────────────────────────────────────────────

    def _find_best_rule(self, query: str, domain: str) -> Optional[Rule]:
        candidates = [
            r for r in self.rules.values()
            if r.domain == domain and r.matches(query) and r.is_alive()
        ]
        if not candidates:
            return None
        return max(candidates, key=lambda r: r.strength)

    def _apply_rule(self, rule: Rule, query: str) -> str:
        tpl = rule.response_template
        # Simple slot fill: {query} -> original query
        tokens = query.strip().split()
        tpl = tpl.replace("{query}", query)
        tpl = tpl.replace("{first_token}", tokens[0] if tokens else "")
        tpl = tpl.replace("{token_count}", str(len(tokens)))
        return tpl

    def _seed_default_rules(self):
        seed_rules = [
            # ── Math ──────────────────────────────────────────────────────────
            Rule("math_add",    r"\d+\s*\+\s*\d+",
                 "To add numbers, sum each digit column right-to-left, carrying over tens.", "math"),
            Rule("math_mul",    r"\d+\s*\*\s*\d+|\d+\s*times\s*\d+",
                 "Multiplication is repeated addition. Use long multiplication for multi-digit numbers.", "math"),
            Rule("math_div",    r"\d+\s*/\s*\d+|divide|divided by",
                 "Division splits a number into equal parts. Check divisibility first.", "math"),
            Rule("math_prime",  r"prime|factor",
                 "A prime number has exactly 2 factors: 1 and itself. Trial-divide up to √n.", "math"),
            Rule("math_general",r"calculat|comput|math|formula|equation",
                 "Break the problem into steps: identify variables, apply operations in PEMDAS order.", "math"),

            # ── Networking ────────────────────────────────────────────────────
            Rule("net_dns",     r"\bdns\b|domain name|resolve",
                 "DNS maps domain names to IP addresses. Query flows: local cache → resolver → root → TLD → authoritative.", "networking"),
            Rule("net_tcp",     r"\btcp\b|three.way handshake|reliable",
                 "TCP is connection-oriented. 3-way handshake: SYN → SYN-ACK → ACK. Provides ordering and retransmission.", "networking"),
            Rule("net_udp",     r"\budp\b|datagram|connectionless",
                 "UDP is connectionless and fast. No handshake, no retransmission. Use for streaming/gaming.", "networking"),
            Rule("net_http",    r"\bhttp\b|\brest\b|request|endpoint|api",
                 "HTTP is stateless request-response over TCP. Methods: GET/POST/PUT/DELETE. Status codes: 2xx success, 4xx client error, 5xx server error.", "networking"),
            Rule("net_ip",      r"\bip\b|subnet|cidr|routing",
                 "IP addresses route packets. IPv4: 32-bit dotted decimal. Subnets use CIDR notation (e.g. /24 = 256 addresses).", "networking"),

            # ── Android ───────────────────────────────────────────────────────
            Rule("and_activity",r"activity|lifecycle|onResume|onCreate",
                 "Android Activity lifecycle: onCreate→onStart→onResume (visible/active). Reverse on pause/stop/destroy.", "android"),
            Rule("and_intent",  r"intent|broadcast|component",
                 "Intents are messaging objects. Explicit intents target a specific component; implicit intents declare an action for the system to resolve.", "android"),
            Rule("and_perf",    r"performance|battery|memory leak|optimiz",
                 "Android performance: avoid allocations on the main thread, use ViewHolder pattern, recycle bitmaps, cancel coroutines on lifecycle end.", "android"),
            Rule("and_perm",    r"permission|manifest|runtime",
                 "Declare permissions in AndroidManifest.xml. Runtime permissions (API 23+) must be requested at runtime with ActivityCompat.requestPermissions.", "android"),

            # ── General ───────────────────────────────────────────────────────
            Rule("gen_define",  r"what is|define|explain|meaning of",
                 "This query asks for a definition. I can answer from my local knowledge base for: {query}.", "general"),
            Rule("gen_howto",   r"how to|how do|steps to|guide",
                 "For step-by-step guidance on '{query}': break the task into ordered steps, verify prerequisites first.", "general"),
        ]
        for rule in seed_rules:
            if rule.domain in self.domains or "general" in self.domains:
                self.rules[rule.rule_id] = rule

    def capability_report(self) -> dict:
        by_domain: dict[str, list[float]] = {}
        for r in self.rules.values():
            by_domain.setdefault(r.domain, []).append(r.strength)
        return {
            domain: round(sum(strengths) / len(strengths), 3)
            for domain, strengths in by_domain.items()
        }
