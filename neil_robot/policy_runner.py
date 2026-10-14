"""
Real-time policy loop: observations out at the recorder's tick, action chunks back.

    runner = PolicyRunner(client, spec, mode="sync")
    rec = SyncRecorder(cameras, extras={"motors": ...}, on_step=runner.on_step)
    rec.start(); runner.start(rec.out_dir); ...; runner.stop(); rec.stop()

The recorder ticks at a fixed rate (15 fps) and calls on_step() with every step.
on_step() never waits on the network: it takes the next planned action off a
queue, and when the queue runs low it hands the step's observation to a worker
thread, which sends it to the policy server and refills the queue with the reply.

Two modes:

  sync   Run the whole chunk, then ask again. While the request is in flight the
         queue is empty and the robot holds still.
  async  Ask for the next chunk once only *refill_at* actions are left, and keep
         running the current one meanwhile, so the robot doesn't stop.

A chunk's actions[k] is meant for k steps after its observation. If the robot
executed n actions while the request was in flight (async), the world moved on by
n steps, so the reply's first n actions are skipped and the rest replace whatever
is left of the old chunk. If it held still (sync, or the very first request),
nothing is skipped.

Every step in steps.jsonl gets:
    "action": {"values": [...], "chunk": n, "index": i}   or null while holding
    "policy": {"queued": n, "in_flight": bool}
and every request gets a line in inference.jsonl (latency, skipped actions, errors).

Actions are only logged here. Driving the motors needs the Pi-side controller (next phase);
*execute* is the hook it will plug into.
"""
from __future__ import annotations

import json
import logging
import threading
from collections import deque
from pathlib import Path
from typing import Callable

from neil_robot import clock
from neil_robot.observation import ObservationError, ObservationSpec
from neil_robot.policy_client import PolicyClient

log = logging.getLogger(__name__)


class PolicyRunner:
    def __init__(
        self,
        client: PolicyClient,
        spec: ObservationSpec,
        mode: str = "sync",
        refill_at: int = 10,
        actions_per_chunk: int | None = None,
        task: str | None = None,
        execute: Callable[[list[float]], None] | None = None,
    ):
        if mode not in ("sync", "async"):
            raise ValueError("mode must be 'sync' or 'async'")
        self.client = client
        self.spec = spec
        self.mode = mode
        self.refill_at = refill_at if mode == "async" else 0
        self.actions_per_chunk = actions_per_chunk
        self.task = task
        self.execute = execute
        self.requests = 0
        self.errors = 0
        self.last_error: str | None = None
        self.latencies_ms: list[float] = []
        self._queue: deque[tuple[int, int, list[float]]] = deque()  # (chunk, index, values)
        self._lock = threading.Lock()
        self._pending: dict | None = None
        self._in_flight = False
        self._wake = threading.Event()
        self._stop = threading.Event()
        self._last_step = -1
        self._executed = 0          # actions handed out so far
        self._executed_at_obs = 0   # ... when the in-flight observation was taken
        self._log = None
        self._worker: threading.Thread | None = None

    # ── lifecycle ─────────────────────────────────────────────────────────────

    def start(self, out_dir: Path) -> "PolicyRunner":
        self._log = open(Path(out_dir) / "inference.jsonl", "w", encoding="utf-8")
        self._stop.clear()
        self._worker = threading.Thread(target=self._work, name="policy-worker", daemon=True)
        self._worker.start()
        return self

    def stop(self) -> None:
        self._stop.set()
        self._wake.set()
        if self._worker:
            self._worker.join(timeout=self.client.timeout_s + 5)
        if self._log:
            self._log.close()
            self._log = None

    # ── called by the recorder at every tick (must not block) ─────────────────

    def on_step(self, row: dict, files: dict[str, bytes]) -> None:
        with self._lock:
            self._last_step = row["step"]
            nxt = self._queue.popleft() if self._queue else None
            self._executed += nxt is not None
            need = not self._in_flight and self._pending is None and len(self._queue) <= self.refill_at
            if need and self._worker is not None:
                try:
                    self._pending = self.spec.build(row, files, self.task)
                    self._executed_at_obs = self._executed
                    self._in_flight = True
                    self._wake.set()
                except ObservationError as exc:
                    row["obs_error"] = str(exc)
            row["action"] = None if nxt is None else {"values": nxt[2], "chunk": nxt[0], "index": nxt[1]}
            row["policy"] = {"queued": len(self._queue), "in_flight": self._in_flight}
        if nxt is not None and self.execute:
            self.execute(nxt[2])

    # ── worker ────────────────────────────────────────────────────────────────

    def _work(self) -> None:
        while not self._stop.is_set():
            self._wake.wait()
            self._wake.clear()
            with self._lock:
                obs, self._pending = self._pending, None
            if obs is None:
                continue
            chunk_id = self.requests
            self.requests += 1
            entry = {"chunk": chunk_id, "obs_step": obs["step"], "obs_age_ms": obs["age_ms"]}
            try:
                chunk = self.client.infer(obs)
            except Exception as exc:  # noqa: BLE001
                self.errors += 1
                self.last_error = repr(exc)
                log.warning("policy request failed: %s", exc)
                entry["error"] = repr(exc)
                with self._lock:
                    self._in_flight = False
                self._write(entry)
                continue
            actions = chunk.actions[: self.actions_per_chunk] if self.actions_per_chunk else chunk.actions
            with self._lock:
                skip = self._executed - self._executed_at_obs
                self._queue.clear()
                self._queue.extend((chunk_id, i, a) for i, a in enumerate(actions) if i >= skip)
                self._in_flight = False
                queued = len(self._queue)
            self.latencies_ms.append(chunk.round_trip_ms)
            entry.update({"reply_step": self._last_step, "round_trip_ms": round(chunk.round_trip_ms, 1),
                          "server_ms": chunk.server_timing_ms, "chunk_size": len(chunk.actions),
                          "skipped": skip, "queued": queued, "first_action": actions[0] if actions else None})
            self._write(entry)

    def _write(self, entry: dict) -> None:
        entry["t"] = round(clock.now(), 6)
        if self._log:
            self._log.write(json.dumps(entry) + "\n")
            self._log.flush()
