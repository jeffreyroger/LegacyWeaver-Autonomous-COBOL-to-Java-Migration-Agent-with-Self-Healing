"""Trace event fan-out — BACKEND_PLAN.md §4.3 / Step B4.

The orchestrator's disk write (zuse/agent/orchestrator.py `_emit`) remains
the sole source of truth. This module only tees those same dicts to live
SSE subscribers and keeps a bounded in-memory replay buffer so a client
reconnecting with `Last-Event-ID` can catch up without re-reading the whole
trace file. Events are never filtered, aggregated, or reshaped here — the
frontend adapts to the SRS §4.7 schema, not the reverse.
"""

from __future__ import annotations

import queue
import threading
from dataclasses import dataclass, field

BUFFER_SIZE = 1000
# Bounded so a stalled subscriber queue can't grow without limit; a full
# queue is a "slow client" and gets dropped rather than blocking the run.
SUBSCRIBER_QUEUE_SIZE = 256


@dataclass
class RunEventBus:
    """One instance per run. Not shared across runs."""

    _lock: threading.Lock = field(default_factory=threading.Lock)
    _seq: int = 0
    _buffer: list[tuple[int, dict]] = field(default_factory=list)
    _subscribers: dict[int, "queue.Queue[tuple[int, dict] | None]"] = field(
        default_factory=dict
    )
    _next_subscriber_id: int = 0
    closed: bool = False

    def publish(self, event: dict) -> int:
        with self._lock:
            self._seq += 1
            seq = self._seq
            self._buffer.append((seq, event))
            if len(self._buffer) > BUFFER_SIZE:
                self._buffer.pop(0)
            dead: list[int] = []
            for sub_id, q in self._subscribers.items():
                try:
                    q.put_nowait((seq, event))
                except queue.Full:
                    # Backpressure policy: drop the client, never block the
                    # agent -- a slow browser must not slow a run.
                    dead.append(sub_id)
            for sub_id in dead:
                self._subscribers.pop(sub_id, None)
        return seq

    def close(self) -> None:
        with self._lock:
            self.closed = True
            for q in self._subscribers.values():
                try:
                    q.put_nowait(None)
                except queue.Full:
                    pass

    def subscribe(
        self, last_event_id: int = 0
    ) -> tuple[int, "queue.Queue[tuple[int, dict] | None]", list[tuple[int, dict]]]:
        """Returns (subscriber_id, live_queue, backlog).

        `backlog` is every buffered event with seq > last_event_id, served
        before anything arriving on the live queue -- this is the
        `Last-Event-ID` replay path. Events older than the buffer window
        are not here; the caller falls back to the disk trace for those.
        """
        with self._lock:
            sub_id = self._next_subscriber_id
            self._next_subscriber_id += 1
            backlog = [(s, e) for s, e in self._buffer if s > last_event_id]
            q: "queue.Queue[tuple[int, dict] | None]" = queue.Queue(
                maxsize=SUBSCRIBER_QUEUE_SIZE
            )
            if not self.closed:
                self._subscribers[sub_id] = q
            return sub_id, q, backlog

    def unsubscribe(self, sub_id: int) -> None:
        with self._lock:
            self._subscribers.pop(sub_id, None)

    def earliest_buffered_seq(self) -> int | None:
        with self._lock:
            return self._buffer[0][0] if self._buffer else None
