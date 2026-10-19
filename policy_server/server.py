"""
Policy server: loads a VLA policy once and answers observation -> action chunk over HTTP.

    python server.py --checkpoint outputs/neil_JOBID/checkpoints/last/pretrained_model
    python server.py --dummy                      # no model: tests the pipeline end to end
    python server.py --checkpoint ... --device cuda --port 8000

Standalone on purpose (no neil_robot imports): copy this folder to the laptop's
neil_vla env or to an Athena GPU node and run it there. The robot side reaches it
at http://127.0.0.1:<port> (directly, or through an SSH tunnel).

Wire format (JSON):

    POST /infer   {"step", "t", "task", "state": [floats],
                   "images": {key: {"jpeg_b64": str, "rotation": deg}}}
              ->  {"actions": [[floats] * action_dim] * chunk_size,
                   "timing_ms": {"decode", "infer", "total"}}
    GET  /info    {"policy", "checkpoint", "device", "input_features": {key: shape},
                   "action_dim", "chunk_size"}

Only one request is computed at a time; others wait their turn.
"""
from __future__ import annotations

import argparse
import base64
import json
import logging
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import numpy as np

log = logging.getLogger("policy_server")


# ── images ────────────────────────────────────────────────────────────────────

def decode_jpeg(data: bytes, rotation: int = 0) -> np.ndarray:
    """JPEG bytes -> RGB uint8 HxWx3, rotated clockwise by *rotation* degrees."""
    try:
        import cv2
        img = cv2.cvtColor(cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR), cv2.COLOR_BGR2RGB)
    except ImportError:
        import io
        from PIL import Image
        img = np.asarray(Image.open(io.BytesIO(data)).convert("RGB"))
    if rotation % 360:
        img = np.ascontiguousarray(np.rot90(img, k=-(rotation // 90)))
    return img


def resize(img: np.ndarray, h: int, w: int) -> np.ndarray:
    if img.shape[:2] == (h, w):
        return img
    try:
        import cv2
        return cv2.resize(img, (w, h), interpolation=cv2.INTER_AREA)
    except ImportError:
        from PIL import Image
        return np.asarray(Image.fromarray(img).resize((w, h)))


# ── policies ──────────────────────────────────────────────────────────────────

class DummyPolicy:
    """No model. Returns a chunk that holds the current state (or zeros), after
    *latency_s*, so the robot side can be tested end to end, including timing."""

    name = "dummy"

    def __init__(self, action_dim: int = 4, chunk_size: int = 50, latency_s: float = 0.0):
        self.action_dim, self.chunk_size, self.latency_s = action_dim, chunk_size, latency_s
        self.checkpoint, self.device = None, "cpu"
        self.input_features: dict[str, list[int]] = {}

    def infer(self, images: dict[str, np.ndarray], state: np.ndarray, task: str) -> np.ndarray:
        time.sleep(self.latency_s)
        hold = state if state.shape == (self.action_dim,) else np.zeros(self.action_dim, np.float32)
        return np.tile(hold, (self.chunk_size, 1))


class LeRobotPolicy:
    """A LeRobot policy (SmolVLA) from a pretrained_model folder or a Hub id."""

    name = "lerobot"

    def __init__(self, checkpoint: str, device: str = "cpu", n_actions: int | None = None):
        import torch
        self.torch = torch
        self.checkpoint, self.device = checkpoint, device
        self.policy, self.pre, self.post = _load_lerobot(checkpoint, device)
        cfg = self.policy.config
        self.name = getattr(cfg, "type", type(self.policy).__name__)
        self.input_features = {k: list(f.shape) for k, f in cfg.input_features.items()}
        self.action_dim = int(cfg.output_features["action"].shape[0])
        self.chunk_size = int(n_actions or getattr(cfg, "n_action_steps", None) or cfg.chunk_size)

    def infer(self, images: dict[str, np.ndarray], state: np.ndarray, task: str) -> np.ndarray:
        torch = self.torch
        if not any(k in self.input_features for k in images):
            raise KeyError(f"none of the images {sorted(images)} is a policy input "
                           f"({[k for k in self.input_features if k.startswith('observation.images.')]})")
        obs = {}
        for key, img in images.items():
            if key not in self.input_features:
                continue  # a camera the policy wasn't trained with
            if self.name != "smolvla":  # SmolVLA resizes with padding itself, keeping the aspect ratio
                _, h, w = self.input_features[key]
                img = resize(img, h, w)
            obs[key] = torch.from_numpy(img).permute(2, 0, 1).float().div(255).unsqueeze(0)
        if "observation.state" in self.input_features:
            want = self.input_features["observation.state"][0]
            # Shorter is fine: SmolVLA pads the state itself, and a fine-tuned checkpoint's
            # config can keep the base model's longer size while its normaliser has the real one.
            if state.shape[0] > want:
                raise ValueError(f"policy takes a state of at most {want} values; got {state.shape[0]}")
            obs["observation.state"] = torch.from_numpy(state).float().unsqueeze(0)
        with torch.inference_mode():
            if self.pre is not None:          # lerobot >= 0.4: processors normalise and tokenise
                obs["task"] = task
                batch = self.pre(obs)
                chunk = self.policy.predict_action_chunk(batch)
                chunk = self.post(chunk)
            else:                             # older lerobot: the policy normalises itself
                batch = {k: v.to(self.device) for k, v in obs.items()}
                batch["task"] = [task]
                chunk = self.policy.predict_action_chunk(batch)
        return chunk[0, : self.chunk_size].float().cpu().numpy()


def _load_lerobot(checkpoint: str, device: str):
    """(policy, preprocessor or None, postprocessor or None), for old and new lerobot layouts."""
    import importlib.util
    if importlib.util.find_spec("lerobot.policies"):
        from lerobot.policies.factory import get_policy_class, make_pre_post_processors
        from lerobot.configs.policies import PreTrainedConfig
    else:  # lerobot < 0.4
        from lerobot.common.policies.factory import get_policy_class
        from lerobot.configs.policies import PreTrainedConfig
        make_pre_post_processors = None
    cfg = PreTrainedConfig.from_pretrained(checkpoint)
    cfg.device = device
    policy = get_policy_class(cfg.type).from_pretrained(checkpoint, config=cfg)
    policy.to(device).eval()
    if make_pre_post_processors is None:
        return policy, None, None
    pre, post = make_pre_post_processors(
        policy.config, pretrained_path=checkpoint,
        preprocessor_overrides={"device_processor": {"device": device}})
    return policy, pre, post


# ── HTTP ──────────────────────────────────────────────────────────────────────

class Server(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, addr, policy):
        super().__init__(addr, Handler)
        self.policy = policy
        self.lock = threading.Lock()
        self.served = 0


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"  # keep-alive: one connection for the whole run
    server: Server

    def _reply(self, status: int, obj: dict) -> None:
        body = json.dumps(obj).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path != "/info":
            return self._reply(404, {"error": "not found"})
        p = self.server.policy
        self._reply(200, {"policy": p.name, "checkpoint": p.checkpoint, "device": p.device,
                          "input_features": p.input_features, "action_dim": p.action_dim,
                          "chunk_size": p.chunk_size, "served": self.server.served})

    def do_POST(self):
        if self.path != "/infer":
            return self._reply(404, {"error": "not found"})
        t0 = time.perf_counter()
        try:
            req = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            images = {k: decode_jpeg(base64.b64decode(v["jpeg_b64"]), v.get("rotation", 0))
                      for k, v in req["images"].items()}
            state = np.asarray(req["state"], np.float32)
            t1 = time.perf_counter()
            with self.server.lock:
                t2 = time.perf_counter()
                actions = self.server.policy.infer(images, state, req.get("task", ""))
                t3 = time.perf_counter()
                self.server.served += 1
        except Exception as exc:  # noqa: BLE001
            log.exception("request failed")
            return self._reply(500, {"error": repr(exc)})
        self._reply(200, {
            "actions": np.asarray(actions, np.float64).round(4).tolist(),
            "timing_ms": {"decode": round((t1 - t0) * 1000, 1), "queue": round((t2 - t1) * 1000, 1),
                          "infer": round((t3 - t2) * 1000, 1), "total": round((t3 - t0) * 1000, 1)},
        })
        log.info("step %s: %d actions in %.0f ms", req.get("step"), len(actions), (t3 - t0) * 1000)

    def log_message(self, *a):
        pass


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--checkpoint", help="pretrained_model folder (or Hub id) of a trained LeRobot policy")
    src.add_argument("--dummy", action="store_true", help="no model: return 'hold still' chunks")
    ap.add_argument("--device", default="cpu", help="cpu, cuda or mps (default cpu)")
    ap.add_argument("--host", default="127.0.0.1", help="interface to listen on (default: this machine only)")
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--n-actions", type=int, help="actions returned per chunk (default: the policy's n_action_steps)")
    ap.add_argument("--dummy-action-dim", type=int, default=4)
    ap.add_argument("--dummy-latency", type=float, default=0.0, help="seconds each dummy request takes")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    if args.dummy:
        policy = DummyPolicy(args.dummy_action_dim, args.n_actions or 50, args.dummy_latency)
    else:
        log.info("loading %s on %s ...", args.checkpoint, args.device)
        t0 = time.perf_counter()
        policy = LeRobotPolicy(args.checkpoint, args.device, args.n_actions)
        log.info("loaded %s in %.1f s: inputs %s, %d actions of %d values", policy.name,
                 time.perf_counter() - t0, policy.input_features, policy.chunk_size, policy.action_dim)
    server = Server((args.host, args.port), policy)
    log.info("serving %s on http://%s:%d", policy.name, args.host, args.port)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
