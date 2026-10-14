"""
Talk to the policy server (policy_server/server.py) over HTTP.

    client = PolicyClient("http://127.0.0.1:8000")
    info = client.info()                 # what the policy expects and returns
    chunk = client.infer(obs)            # obs from ObservationSpec.build()

Plain HTTP + JSON with one kept-alive connection, so the robot side needs no
extra packages and the server can sit anywhere reachable: this laptop, or an
Athena node behind an SSH tunnel (the URL stays http://127.0.0.1:<port>).

Wire format (both directions are JSON):

    POST /infer   {"step", "t", "task", "state": [floats],
                   "images": {key: {"jpeg_b64": str, "rotation": deg}}}
              ->  {"actions": [[floats] * action_dim] * chunk_size,
                   "timing_ms": {"decode", "infer", "total"}}
    GET  /info    {"policy", "checkpoint", "device", "input_features": {key: shape},
                   "action_dim", "chunk_size"}
"""
from __future__ import annotations

import base64
import http.client
import json
import time
import urllib.parse
from dataclasses import dataclass

from neil_robot import clock

DEFAULT_URL = "http://127.0.0.1:8000"


class PolicyServerError(RuntimeError):
    pass


@dataclass(frozen=True)
class ActionChunk:
    actions: list[list[float]]   # chunk_size x action_dim; actions[0] is for the observation's step
    obs_step: int                # recorder step the observation was taken at
    sent_t: float                # clock.now() when the request was sent
    received_t: float            # clock.now() when the reply arrived
    server_timing_ms: dict

    @property
    def round_trip_ms(self) -> float:
        return (self.received_t - self.sent_t) * 1000


class PolicyClient:
    def __init__(self, url: str = DEFAULT_URL, timeout_s: float = 120):
        u = urllib.parse.urlsplit(url)
        if u.scheme != "http":
            raise ValueError(f"policy server URL must be http://, got {url}")
        self.url = url
        self.host, self.port = u.hostname, u.port or 80
        self.timeout_s = timeout_s
        self._conn: http.client.HTTPConnection | None = None

    def close(self) -> None:
        if self._conn:
            self._conn.close()
            self._conn = None

    def _request(self, method: str, path: str, body: dict | None = None) -> dict:
        data = None if body is None else json.dumps(body).encode()
        headers = {"Content-Type": "application/json"} if data else {}
        for attempt in (1, 2):  # once more on a dropped keep-alive connection
            if self._conn is None:
                self._conn = http.client.HTTPConnection(self.host, self.port, timeout=self.timeout_s)
            try:
                self._conn.request(method, path, body=data, headers=headers)
                resp = self._conn.getresponse()
                payload = resp.read()
            except (ConnectionError, http.client.HTTPException, OSError) as exc:
                self.close()
                if attempt == 2:
                    raise PolicyServerError(f"policy server at {self.url} unreachable: {exc}") from exc
                continue
            if resp.status != 200:
                raise PolicyServerError(f"{method} {path}: HTTP {resp.status}: {payload[:1000].decode(errors='replace')}")
            return json.loads(payload)
        raise AssertionError("unreachable")

    def info(self) -> dict:
        return self._request("GET", "/info")

    def wait_ready(self, wait_s: float = 60) -> dict:
        """info(), retrying until the server is up (it may still be loading the model)."""
        deadline = time.monotonic() + wait_s
        while True:
            try:
                return self.info()
            except PolicyServerError:
                if time.monotonic() > deadline:
                    raise
                time.sleep(1)

    def infer(self, obs: dict) -> ActionChunk:
        body = {
            "step": obs["step"], "t": obs["t"], "task": obs["task"], "state": obs["state"],
            "images": {k: {"jpeg_b64": base64.b64encode(v["jpeg"]).decode(), "rotation": v["rotation"]}
                       for k, v in obs["images"].items()},
        }
        sent = clock.now()
        reply = self._request("POST", "/infer", body)
        return ActionChunk(reply["actions"], obs["step"], sent, clock.now(), reply.get("timing_ms", {}))
