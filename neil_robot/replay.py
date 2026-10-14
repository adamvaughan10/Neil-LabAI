"""
Play a recorded session back as if it were the live robot, for testing without it.

    session = ReplaySession("logs/session_20261013_144751")
    cameras = session.cameras()          # {"pi": ..., "external": ...}, same API as the live streams
    motors = session.motors()            # same API as MotorStateStream

Each source serves the recorded step for the current time (the recording's own
rate, looping at the end), so the recorder and the policy runner see the same
kind of data they get from the robot: newest-only frames, cached motor state.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from neil_robot import clock
from neil_robot.streams import Frame


class ReplaySession:
    def __init__(self, session_dir):
        self.dir = Path(session_dir)
        self.rows = [json.loads(l) for l in (self.dir / "steps.jsonl").read_text(encoding="utf-8").splitlines() if l]
        if not self.rows:
            raise ValueError(f"{self.dir}: steps.jsonl is empty")
        info = json.loads((self.dir / "info.json").read_text(encoding="utf-8"))
        self.fps = info["fps"]
        self.rotations = {n: c.get("rotation", 0) for n, c in info.get("cameras", {}).items()}
        self.t0 = clock.now()

    def position(self) -> tuple[int, int]:
        """(loop number, step index) for the current time."""
        k = max(0, int((clock.now() - self.t0) * self.fps + 1e-3))  # + 1e-3: a tick exactly on step k is step k
        return divmod(k, len(self.rows))

    def cameras(self) -> dict[str, "ReplayCamera"]:
        names = [n for n in ("pi", "external") if self.rows[0].get(n)]
        return {n: ReplayCamera(self, n) for n in names}

    def motors(self) -> "ReplayMotors | None":
        return ReplayMotors(self) if self.rows[0].get("motors") else None


class ReplayCamera:
    """Stands in for an MjpegStream."""

    def __init__(self, session: ReplaySession, name: str):
        self.session, self.name = session, name
        self.url = f"replay://{session.dir.name}/{name}"
        self.rotation = session.rotations.get(name, 0)
        self.latency_s = 0.0
        self.error = None
        self._cache: tuple[int, bytes] | None = None

    def start(self, *_):
        return self

    def stop(self):
        pass

    def latest(self) -> Frame | None:
        loop, i = self.session.position()
        cam = self.session.rows[i].get(self.name)
        if not cam:
            return None
        if not self._cache or self._cache[0] != i:
            self._cache = (i, (self.session.dir / cam["file"]).read_bytes())
        index = loop * 1_000_000 + cam["frame"]
        return Frame(self._cache[1], clock.now() - cam["age_ms"] / 1000, index)


@dataclass(frozen=True)
class _ReplayState:
    motors: dict
    ts: float

    def as_step(self, t: float) -> dict:
        return {**self.motors, "ts": round(self.ts, 6), "age_ms": round((t - self.ts) * 1000, 2)}


class ReplayMotors:
    """Stands in for a MotorStateStream (read-only, like the real one)."""

    def __init__(self, session: ReplaySession):
        self.session = session

    def start(self, *_):
        return self

    def check_ready(self):
        pass

    def stop(self):
        pass

    def latest(self) -> _ReplayState | None:
        loop, i = self.session.position()
        m = dict(self.session.rows[i]["motors"])
        m["seq"] = loop * 1_000_000 + m.get("seq", i)
        return _ReplayState(m, clock.now() - m.get("age_ms", 0) / 1000)
