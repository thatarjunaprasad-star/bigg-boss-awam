"""Request telemetry: latency ring buffers, counters, percentile snapshots."""
from __future__ import annotations

import math
import threading
import time
from collections import defaultdict, deque
from dataclasses import dataclass, field


def _percentile(sorted_values: list[float], pct: float) -> float:
    if not sorted_values:
        return 0.0
    if len(sorted_values) == 1:
        return sorted_values[0]
    rank = (pct / 100.0) * (len(sorted_values) - 1)
    lo = math.floor(rank)
    hi = math.ceil(rank)
    if lo == hi:
        return sorted_values[lo]
    frac = rank - lo
    return sorted_values[lo] * (1 - frac) + sorted_values[hi] * frac


@dataclass
class LatencySnapshot:
    count: int = 0
    p50: float = 0.0
    p95: float = 0.0
    p99: float = 0.0
    max: float = 0.0
    mean: float = 0.0


@dataclass
class EngineCounters:
    requests: int = 0
    errors: int = 0
    tokens_in: int = 0
    tokens_out: int = 0
    generation_ms_total: float = 0.0
    votes: int = 0
    ratings: int = 0
    trivia_answers: int = 0
    trivia_correct: int = 0
    chat_messages: int = 0


class TelemetryService:
    """Thread-safe metrics collector feeding the /api/diagnostics dashboard."""

    def __init__(self, window: int = 512) -> None:
        self._lock = threading.Lock()
        self._window = window
        self._latencies: dict[str, deque[float]] = defaultdict(lambda: deque(maxlen=window))
        self._recent: deque[float] = deque(maxlen=window)
        self.counters = EngineCounters()
        self.started_at = time.time()

    # -- recording ----------------------------------------------------------
    def record_latency(self, route: str, ms: float) -> None:
        with self._lock:
            self._latencies[route].append(ms)
            self._recent.append(ms)

    def bump(self, name: str, amount: int = 1) -> None:
        with self._lock:
            if hasattr(self.counters, name):
                setattr(self.counters, name, getattr(self.counters, name) + amount)

    def add_tokens(self, tokens_in: int, tokens_out: int, gen_ms: float) -> None:
        with self._lock:
            self.counters.tokens_in += tokens_in
            self.counters.tokens_out += tokens_out
            self.counters.generation_ms_total += gen_ms

    def record_error(self) -> None:
        with self._lock:
            self.counters.errors += 1

    # -- snapshots ----------------------------------------------------------
    def snapshot_latencies(self, route: str) -> LatencySnapshot:
        with self._lock:
            values = sorted(self._latencies.get(route, ()))
            return self._snap(values)

    def snapshot_recent(self) -> LatencySnapshot:
        with self._lock:
            values = sorted(self._recent)
            return self._snap(values)

    @staticmethod
    def _snap(values: list[float]) -> LatencySnapshot:
        if not values:
            return LatencySnapshot()
        return LatencySnapshot(
            count=len(values),
            p50=round(_percentile(values, 50), 2),
            p95=round(_percentile(values, 95), 2),
            p99=round(_percentile(values, 99), 2),
            max=round(values[-1], 2),
            mean=round(sum(values) / len(values), 2),
        )

    def recent_series(self, limit: int = 120) -> list[float]:
        with self._lock:
            return list(self._recent)[-limit:]

    def overview(self) -> dict:
        with self._lock:
            c = self.counters
            uptime = time.time() - self.started_at
            tps = (c.tokens_out / (c.generation_ms_total / 1000.0)) if c.generation_ms_total else 0.0
            per_route = {
                route: self._snap(sorted(vals)).__dict__
                for route, vals in self._latencies.items()
            }
            accuracy = (c.trivia_correct / c.trivia_answers * 100.0) if c.trivia_answers else 0.0
            return {
                "uptime_seconds": round(uptime, 1),
                "requests": c.requests,
                "errors": c.errors,
                "tokens_in": c.tokens_in,
                "tokens_out": c.tokens_out,
                "tokens_per_sec": round(tps, 1),
                "generation_ms_total": round(c.generation_ms_total, 1),
                "chat_messages": c.chat_messages,
                "votes_cast": c.votes,
                "ratings_given": c.ratings,
                "trivia_answers": c.trivia_answers,
                "trivia_accuracy_pct": round(accuracy, 1),
                "latency_recent": self._snap(sorted(self._recent)).__dict__,
                "latency_per_route": per_route,
            }
