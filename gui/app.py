"""
Neil VLA control panel: a local web page for running the model on Neil.

    .venv/bin/python gui/app.py                          # then open http://127.0.0.1:8090
    .venv/bin/python gui/app.py --replay logs/session_X  # no robot: a recording stands in for Neil

The page shows both cameras and the motor readings, starts or picks a policy server,
and runs the model at 10 steps a second, like scripts/run_policy.py:

  Dry run  Cameras through PiCameraStream, motors through the read-only MotorStateStream.
           The model's actions are turned into the commands Neil *would* get, and logged.
  Drive    The inference kit's pi_bridge.py runs on the Pi (uploaded to /tmp): it holds the
           motors and serves the front camera. Each action is capped here (wheel speed,
           arm and gripper target ranges) and again by pi_bridge.py, then sent.

Stopping a drive run, the emergency stop, closing the page (no poll for 1.5 s) or losing
SSH all stop the wheels; pi_bridge.py also stops them 0.5 s after its last command.
Only one program can hold Neil's motors and Pi camera: stop the gamepad, the recorder
and run_policy.py before connecting, and press Disconnect here before running them.

Every run is saved in logs/gui_run_<date>_<time>/ like run_policy.py's: images,
steps.jsonl (each step's action and the command it became), inference.jsonl, policy.json.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import signal
import socket
import subprocess
import sys
import threading
import time
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# Lab defaults, before neil_robot.config reads the environment.
_LAB_KEY = Path.home() / ".ssh" / "id_ed25519_labpi"
if not os.getenv("RPI_SSH_KEY") and _LAB_KEY.exists():
    os.environ["RPI_SSH_KEY"] = str(_LAB_KEY)
os.environ.setdefault("EXTERNAL_CAMERA_URL", "http://132.68.34.85:8080/stream.mjpg")

from neil_robot import clock, config  # noqa: E402
from neil_robot.motor_stream import MotorState, MotorStateStream  # noqa: E402
from neil_robot.observation import ObservationSpec  # noqa: E402
from neil_robot.policy_client import PolicyClient, PolicyServerError  # noqa: E402
from neil_robot.policy_runner import PolicyRunner  # noqa: E402
from neil_robot.recorder import SyncRecorder  # noqa: E402
from neil_robot.replay import ReplaySession  # noqa: E402
from neil_robot.rpi_client import RPiClient  # noqa: E402
from neil_robot.streams import ExternalCameraStream, MjpegStream, PiCameraStream  # noqa: E402

log = logging.getLogger("gui")

STATIC = Path(__file__).resolve().parent / "index.html"
KIT = ROOT / "inference_kit"
BRIDGE_SRC = Path(os.getenv("NEIL_GUI_BRIDGE", KIT / "pi_bridge.py"))
BRIDGE_PI_PATH = "/tmp/neil_gui_pi_bridge.py"
SERVER_SCRIPT = ROOT / "policy_server" / "server.py"
FPS = 10  # the pick_cup data was recorded at 10 steps a second
DEADMAN_S = 1.5

# Robot terms (+ forward / arm down / gripper open) = sign x raw motor value.
SIGN = {"left": config.LEFT_WHEEL_SIGN_FORWARD, "right": config.RIGHT_WHEEL_SIGN_FORWARD,
        "arm": config.ARM_MOTOR_SIGN_DOWN, "grip": config.GRIPPER_MOTOR_SIGN_OPEN}
PORT = {"left": config.PORT_LEFT_WHEEL, "right": config.PORT_RIGHT_WHEEL,
        "arm": config.PORT_ARM, "grip": config.PORT_GRIPPER}

# Hard limits, the same as pi_bridge.py's: the page can only narrow them.
HARD = {"wheel_cap": 30, "arm": (-25, 10), "grip": (-80, 5)}
DEFAULT_CAPS = {"wheel_cap": 30, "wheels": True, "arm_grip": True,
                "arm_min": -25, "arm_max": 10, "grip_min": -80, "grip_max": 5}


def vla_python() -> str | None:
    """The Python that has lerobot (the policy server's env)."""
    for p in (os.getenv("NEIL_VLA_PYTHON"), ROOT / ".venv-vla/bin/python",
              ROOT.parent / "Neil LabAI-dryrun/.venv-vla/bin/python", KIT / ".venv/bin/python"):
        if p and Path(p).exists():
            return str(p)
    return None


def port_in_use(port: int) -> bool:
    with socket.socket() as s:
        s.settimeout(0.3)
        return s.connect_ex(("127.0.0.1", port)) == 0


def robot_readings(step: dict | None) -> dict | None:
    """A motor step entry (MotorState.as_step) as the four values the model sees, in robot terms."""
    if not step:
        return None

    def val(role, field, sign):
        m = step.get(role) or {}
        return None if m.get(field) is None else round(sign * m[field], 1)
    return {"left": val("left_wheel", "speed", SIGN["left"]), "right": val("right_wheel", "speed", SIGN["right"]),
            "arm": val("arm", "pos_deg", SIGN["arm"]), "grip": val("gripper", "pos_deg", SIGN["grip"]),
            "age_ms": step.get("age_ms")}


# ── the motor link for drive runs ─────────────────────────────────────────────

class BridgeLink:
    """inference_kit/pi_bridge.py on the Pi. A thread sends the newest command every 0.1 s
    (or "wheels stop" once it is 0.25 s old) and reads the motor state each reply carries.
    latest() gives that state as a MotorState, like MotorStateStream."""

    HOLD = {"left": 0, "right": 0}

    def __init__(self):
        self._client = RPiClient()
        self._stdin = self._stdout = None
        self._cmd: dict | None = None
        self._cmd_t = 0.0
        self._io = threading.Lock()
        self._wake = threading.Event()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._latest: MotorState | None = None
        self._seq = 0
        self.error: str | None = None
        self.closed = False

    def start(self) -> "BridgeLink":
        ssh = self._client.connect()
        self._client.run_shell(f"pkill -INT -f {BRIDGE_PI_PATH}; sleep 0.5", timeout=10)
        with ssh.open_sftp() as sftp, sftp.open(BRIDGE_PI_PATH, "w") as f:
            f.write(BRIDGE_SRC.read_text())
        self._stdin, self._stdout, _ = ssh.exec_command(f"python3 -u {BRIDGE_PI_PATH} 2>&1")
        self._stdout.channel.settimeout(30)
        lines = []
        for line in self._stdout:  # buildhat may print firmware messages first
            lines.append(line.rstrip())
            if line.startswith("{") and json.loads(line).get("ready"):
                break
        else:
            raise RuntimeError("pi_bridge.py stopped before it was ready:\n" + "\n".join(lines[-15:]))
        self._stdout.channel.settimeout(3)
        self._exchange(self.HOLD)  # first reading, without moving
        self._thread = threading.Thread(target=self._loop, name="bridge", daemon=True)
        self._thread.start()
        return self

    def set_command(self, cmd: dict) -> None:
        self._cmd, self._cmd_t = cmd, time.monotonic()
        self._wake.set()

    def latest(self) -> MotorState | None:
        return self._latest

    def _exchange(self, cmd: dict) -> None:
        with self._io:
            if self.closed:
                return
            self._stdin.write(json.dumps(cmd) + "\n")
            self._stdin.flush()
            while True:
                line = self._stdout.readline()
                if not line:
                    raise RuntimeError("pi_bridge.py exited")
                if line.startswith("{") and "left_speed" in line:
                    break
        s = json.loads(line)
        raw = lambda role, v: SIGN[role] * v  # noqa: E731  (signs are +-1: their own inverse)
        motors = {PORT["left"]: {"speed": raw("left", s["left_speed"]), "pos": None, "apos": None},
                  PORT["right"]: {"speed": raw("right", s["right_speed"]), "pos": None, "apos": None},
                  PORT["arm"]: {"speed": None, "pos": raw("arm", s["arm_pos"]), "apos": None},
                  PORT["grip"]: {"speed": None, "pos": raw("grip", s["grip_pos"]), "apos": None}}
        self._seq += 1
        self._latest = MotorState(clock.now(), s["t"], self._seq, motors, {})

    def _loop(self) -> None:
        try:
            while not self._stop.is_set():
                self._wake.wait(0.1)
                self._wake.clear()
                if self._stop.is_set():
                    break
                fresh = self._cmd is not None and time.monotonic() - self._cmd_t < 0.25
                self._exchange(self._cmd if fresh else self.HOLD)
        except Exception as exc:  # noqa: BLE001
            if not self._stop.is_set():
                self.error = repr(exc)
                log.warning("bridge stopped: %s", exc)

    def stop(self) -> None:
        """Wheels stop now; closing stdin ends pi_bridge.py, which lets every motor go."""
        self._stop.set()
        self._wake.set()
        try:
            with self._io:
                if not self.closed:
                    self.closed = True
                    self._stdin.write(json.dumps(self.HOLD) + "\n")
                    self._stdin.flush()
                    self._stdin.channel.shutdown_write()
        except Exception:  # noqa: BLE001
            pass
        if self._thread:
            self._thread.join(timeout=4)
        ch = self._stdout.channel if self._stdout else None
        deadline = time.monotonic() + 3
        while ch and not ch.exit_status_ready() and time.monotonic() < deadline:
            time.sleep(0.05)
        try:  # still running: SIGINT, so Python's exit handlers stop the motors
            self._client.run_shell(f"pkill -INT -f {BRIDGE_PI_PATH}", timeout=10)
        except Exception:  # noqa: BLE001
            pass
        self._client.close()


# ── the policy server ─────────────────────────────────────────────────────────

class ModelServer:
    """A policy_server/server.py this page started, or one already running at a URL."""

    def __init__(self):
        self.url = "http://127.0.0.1:8001"
        self.proc: subprocess.Popen | None = None
        self.checkpoint: str | None = None
        self.log_path: Path | None = None
        self.info: dict | None = None
        self.status = "none"     # none / loading / ready / error / stopped
        self.error: str | None = None

    def start(self, checkpoint: str, device: str, port: int) -> None:
        py = vla_python()
        if not py:
            raise RuntimeError("no Python with lerobot found: set NEIL_VLA_PYTHON")
        self.stop()
        if port_in_use(port):
            raise RuntimeError(f"port {port} is taken (another policy server?): pick another, or use that one by URL")
        args = ["--dummy"] if checkpoint == "dummy" else ["--checkpoint", checkpoint, "--device", device]
        config.LOGS_DIR.mkdir(parents=True, exist_ok=True)
        self.log_path = config.LOGS_DIR / f"gui_server_{time.strftime('%Y%m%d_%H%M%S')}.log"
        with open(self.log_path, "w") as logf:
            self.proc = subprocess.Popen([py, str(SERVER_SCRIPT), *args, "--port", str(port)], cwd=ROOT,
                                         stdout=logf, stderr=subprocess.STDOUT, start_new_session=True)
        self.url, self.checkpoint, self.info, self.error, self.status = \
            f"http://127.0.0.1:{port}", checkpoint, None, None, "loading"
        threading.Thread(target=self._wait_ready, args=(self.proc,), daemon=True).start()

    def _wait_ready(self, proc) -> None:
        client = PolicyClient(self.url, timeout_s=5)
        while proc is self.proc and proc.poll() is None:
            try:
                self.info, self.status = client.info(), "ready"
                return
            except PolicyServerError:
                time.sleep(1)
        if proc is self.proc:
            self.status, self.error = "error", f"server exited ({proc.returncode}): {self.log_tail()}"

    def use(self, url: str) -> None:
        self.stop()
        self.url, self.checkpoint, self.status, self.error = url.rstrip("/"), None, "loading", None
        try:
            self.info = PolicyClient(self.url, timeout_s=5).info()
            self.checkpoint, self.status = self.info.get("checkpoint"), "ready"
        except Exception as exc:  # noqa: BLE001
            self.info, self.status, self.error = None, "error", str(exc)

    def stop(self) -> None:
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(10)
            except subprocess.TimeoutExpired:
                self.proc.kill()
        if self.proc:
            self.status, self.info = "stopped", None
        self.proc = None

    def log_tail(self, n: int = 6) -> str:
        if not self.log_path or not self.log_path.exists():
            return ""
        return "\n".join(self.log_path.read_text(errors="replace").splitlines()[-n:])

    def snapshot(self) -> dict:
        if self.proc and self.proc.poll() is not None and self.status in ("loading", "ready"):
            self.status, self.error = "error", f"server exited ({self.proc.returncode}): {self.log_tail()}"
        return {"url": self.url, "status": self.status, "checkpoint": self.checkpoint, "error": self.error,
                "managed": self.proc is not None, "log": str(self.log_path) if self.log_path else None,
                "log_tail": self.log_tail(4) if self.status == "loading" else None,
                "info": {k: self.info.get(k) for k in ("policy", "device", "action_dim", "chunk_size",
                                                       "input_features", "served")} if self.info else None}


# ── a run ─────────────────────────────────────────────────────────────────────

def check_spec(spec: ObservationSpec, info: dict) -> tuple[list[str], list[str]]:
    """(problems that stop a run, warnings) comparing the spec with the policy's inputs."""
    feats, problems, warnings = info.get("input_features") or {}, [], []
    want = {k for k in feats if k.startswith("observation.images.")}
    if want and not want & set(spec.images):
        problems.append(f"the spec fills none of the policy's images {sorted(want)}")
    elif missing := sorted(want - set(spec.images)):
        warnings.append(f"policy images not sent (left empty): {missing}")
    if "observation.state" in feats and feats["observation.state"][0] < len(spec.state):
        problems.append(f"policy takes {feats['observation.state'][0]} state values, spec sends {len(spec.state)}")
    if (info.get("action_dim") or 0) < 4:
        problems.append(f"policy returns {info.get('action_dim')} action values; driving needs 4")
    return problems, warnings


class Run:
    def __init__(self, ctl: "Controller", spec_path: str, task: str, mode: str, drive: bool,
                 seconds: float | None, refill_at: int, actions_per_chunk: int | None = None):
        self.ctl, self.drive, self.mode, self.seconds = ctl, drive, mode, seconds
        self.spec_path, self.spec = spec_path, ObservationSpec.load(ROOT / spec_path)
        self.task = task.strip() or self.spec.task
        self.actions_per_chunk = actions_per_chunk
        # async: ask again when half of the used actions are left
        self.refill_at = min(refill_at, actions_per_chunk // 2) if actions_per_chunk else refill_at
        self.status, self.error, self.warnings = "starting", None, []
        self.estopped, self.stop_reason = False, None
        self._entered_drive = False
        self._start_done = threading.Event()  # teardown waits for the start to finish or fail
        self.out_dir: Path | None = None
        self.runner: PolicyRunner | None = None
        self.rec: SyncRecorder | None = None
        self.client: PolicyClient | None = None
        self.step, self.action, self.command, self.obs_error = None, None, None, None
        self.history: deque = deque(maxlen=100)
        self._cmd_this_step = None
        self._stopping = threading.Lock()
        self._stop_evt = threading.Event()
        threading.Thread(target=self._start, name="run", daemon=True).start()

    # called by the recorder at every tick: must not block
    def on_step(self, row: dict, files: dict) -> None:
        self._cmd_this_step = None
        self.runner.on_step(row, files)
        a = row.get("action")
        self.step, self.obs_error = row["step"], row.get("obs_error")
        self.action = a["values"] if a else None
        self.command = self._cmd_this_step
        row["command"] = None if self._cmd_this_step is None else {**self._cmd_this_step, "sent": self.drive}
        self.history.append(self.action[:4] if self.action else None)

    def execute(self, values: list[float]) -> None:
        cmd = self.ctl.command_for(values)
        self._cmd_this_step = cmd
        if self.drive and not self.estopped and self.ctl.bridge:
            self.ctl.bridge.set_command(cmd)

    def _start(self) -> None:
        ctl = self.ctl
        try:
            self.client = PolicyClient(ctl.model.url, timeout_s=30)
            info = self.client.wait_ready(wait_s=5)
            problems, self.warnings = check_spec(self.spec, info)
            if problems:
                raise RuntimeError("; ".join(problems))
            if self.drive:
                self._entered_drive = True  # set first: a half-started bridge is stopped too
                ctl.enter_drive()
            if self._stop_evt.is_set():
                raise RuntimeError("stopped while starting")
            cams = {}
            for name in sorted(self.spec.cameras):
                if not ctl.cams.get(name):
                    raise RuntimeError(f"the {name} camera isn't connected")
                cams[name] = ctl.cams[name]
            motors = ctl.motors
            if motors is None:
                raise RuntimeError("the motors aren't connected")

            def motor_step(t):
                s = motors.latest()
                return None if s is None else s.as_step(t)

            self.out_dir = config.LOGS_DIR / f"gui_run_{time.strftime('%Y%m%d_%H%M%S')}"
            self.out_dir.mkdir(parents=True, exist_ok=True)
            (self.out_dir / "policy.json").write_text(json.dumps(
                {"server": ctl.model.url, "server_info": info, "spec_file": self.spec_path, "spec": self.spec.to_dict(),
                 "task": self.task, "mode": self.mode, "refill_at": self.refill_at,
                 "actions_per_chunk": self.actions_per_chunk, "dry_run": not self.drive,
                 "caps": ctl.caps, "replay": ctl.replay}, indent=2))
            self.runner = PolicyRunner(self.client, self.spec, mode=self.mode, refill_at=self.refill_at,
                                       actions_per_chunk=self.actions_per_chunk, task=self.task, execute=self.execute)
            rec = SyncRecorder(cams, fps=FPS, out_dir=self.out_dir, extras={"motors": motor_step},
                                    make_videos=False, on_step=self.on_step)
            self.runner.start(self.out_dir)
            if isinstance(ctl.replay_session, ReplaySession):
                ctl.replay_session.t0 = clock.now() + 0.05  # replay from step 0
            if self._stop_evt.is_set():
                raise RuntimeError("stopped while starting")
            rec.start()
            self.rec, self.status = rec, "running"
            ctl.note(f"run started: {'DRIVE' if self.drive else 'dry run'}, {self.mode}, task {self.task!r}")
        except Exception as exc:  # noqa: BLE001
            self.error = str(exc)
            ctl.note(f"run failed to start: {exc}")
            self._start_done.set()
            self.stop("failed to start")
            return
        self._start_done.set()
        while not self._stop_evt.wait(0.2):
            if self.seconds and self.rec.elapsed >= self.seconds:
                self.stop(f"{self.seconds:g} s done")
            elif self.drive and ctl.bridge and ctl.bridge.error:
                self.stop(f"motor link lost: {ctl.bridge.error}")

    def stop(self, reason: str) -> None:
        if not self._stopping.acquire(blocking=False):
            return
        self.stop_reason = reason
        self._stop_evt.set()
        if self.status != "starting" or self.error:
            self.status = "stopping"
        if self.drive and self.ctl.bridge:
            self.ctl.bridge.set_command(BridgeLink.HOLD)
        threading.Thread(target=self._teardown, daemon=True).start()

    def _teardown(self) -> None:
        ctl = self.ctl
        self._start_done.wait(60)
        try:
            if self._entered_drive:
                ctl.leave_drive()  # the motors first
            if self.rec:
                self.rec.stop()
            if self.runner:
                self.runner.stop()
            if self.client:
                self.client.close()
        except Exception as exc:  # noqa: BLE001
            ctl.note(f"while stopping: {exc}")
        self.status = "failed" if self.error else "done"
        ctl.note(f"run stopped ({self.stop_reason})" + (f", saved to {self.out_dir.relative_to(ROOT)}"
                                                        if self.out_dir else ""))
        if self._entered_drive:
            ctl.reconnect_after_drive()

    def snapshot(self) -> dict:
        r = self.runner
        lats = sorted(r.latencies_ms) if r else []
        return {
            "status": self.status, "error": self.error, "warnings": self.warnings, "drive": self.drive,
            "estopped": self.estopped, "stop_reason": self.stop_reason, "mode": self.mode, "task": self.task,
            "spec": self.spec_path, "seconds": self.seconds,
            "elapsed": round(self.rec.elapsed, 1) if self.rec and self.rec.t0 else 0,
            "step": self.step, "action": self.action, "command": self.command, "obs_error": self.obs_error,
            "chunks": len(lats), "errors": r.errors if r else 0, "last_error": r.last_error if r else None,
            "latency_ms": round(r.latencies_ms[-1]) if r and r.latencies_ms else None,
            "latency_median_ms": round(lats[len(lats) // 2]) if lats else None,
            "queued": len(r._queue) if r else 0, "in_flight": r._in_flight if r else False,
            "history": list(self.history), "action_names": self.spec.action[:4],
            "out_dir": str(self.out_dir.relative_to(ROOT)) if self.out_dir else None,
        }


# ── everything the page controls ──────────────────────────────────────────────

class Controller:
    def __init__(self, replay: str | None):
        self.replay = replay
        self.replay_session: ReplaySession | None = None
        self.cams: dict[str, object] = {}
        self.cam_status = {"pi": "off", "external": "off"}
        self.motors = None
        self.motor_status, self.motor_kind = "off", None
        self.bridge: BridgeLink | None = None
        self.busy: str | None = None       # what a background connect/disconnect is doing
        self.model = ModelServer()
        self.run: Run | None = None
        self.caps = dict(DEFAULT_CAPS)
        self.last_poll = time.monotonic()
        self.messages: deque = deque(maxlen=30)
        self.lock = threading.RLock()
        threading.Thread(target=self._deadman, daemon=True).start()

    def note(self, msg: str) -> None:
        log.info(msg)
        self.messages.append({"t": time.strftime("%H:%M:%S"), "msg": msg})

    @property
    def running(self) -> bool:
        return self.run is not None and self.run.status in ("starting", "running", "stopping")

    # robot connection (dry-run mode: read-only motors, the Pi camera on its own server)

    def connect(self) -> None:
        if self.busy or self.running:
            raise RuntimeError("busy")
        self.busy = "connecting"
        threading.Thread(target=self._connect, daemon=True).start()

    def _connect(self, which=("pi", "external", "motors")) -> None:
        try:
            if self.replay:
                if not self.replay_session:
                    self.replay_session = ReplaySession(ROOT / self.replay)
                    self.replay_session.t0 = clock.now()
                for name, cam in self.replay_session.cameras().items():
                    self.cams[name], self.cam_status[name] = cam, "on (replay)"
                self.motors, self.motor_status, self.motor_kind = self.replay_session.motors(), "on (replay)", "replay"
                self.note(f"replaying {self.replay}")
                return
            makers = {"pi": PiCameraStream, "external": ExternalCameraStream}
            for name in ("pi", "external"):
                if name in which and not self.cams.get(name):
                    self.cam_status[name] = "connecting"
                    try:
                        self.cams[name] = makers[name]().start()
                        self.cam_status[name] = "on"
                    except Exception as exc:  # noqa: BLE001
                        self.cam_status[name] = f"error: {exc}"
                        self.note(f"{name} camera: {exc}")
            if "motors" in which and self.motors is None:
                self.motor_status = "connecting"
                m = MotorStateStream()
                try:
                    m.start()
                    m.check_ready()
                    self.motors, self.motor_status, self.motor_kind = m, "on (read-only)", "read-only"
                except Exception as exc:  # noqa: BLE001
                    m.stop()
                    self.motor_status = f"error: {exc}"
                    self.note(f"motors: {exc}")
        finally:
            self.busy = None

    def disconnect(self) -> None:
        if self.running:
            raise RuntimeError("stop the run first")
        self.busy = "disconnecting"
        try:
            self._release(("pi", "external", "motors"))
            self.note("disconnected: the Pi's motors and camera are free")
        finally:
            self.busy = None

    def _release(self, which) -> None:
        for name in ("pi", "external"):
            if name in which and self.cams.get(name):
                try:
                    self.cams.pop(name).stop()
                except Exception:  # noqa: BLE001
                    pass
                self.cam_status[name] = "off"
        if "motors" in which and self.motors is not None:
            try:
                self.motors.stop()
            except Exception:  # noqa: BLE001
                pass
            self.motors, self.motor_status, self.motor_kind = None, "off", None

    # drive mode: pi_bridge.py holds the motors and the Pi camera

    def enter_drive(self) -> None:
        if self.replay:
            raise RuntimeError("drive is off while replaying a recording")
        if not BRIDGE_SRC.exists():
            raise RuntimeError(f"{BRIDGE_SRC} not found")
        self._release(("pi", "motors"))
        self.motor_status = self.cam_status["pi"] = "starting pi_bridge.py"
        bridge = BridgeLink()
        try:
            bridge.start()
        except Exception:
            bridge.stop()
            self.motor_status = self.cam_status["pi"] = "off"
            raise
        self.bridge, self.motors, self.motor_status, self.motor_kind = bridge, bridge, "on (DRIVING)", "bridge"
        # pi_bridge.py's camera server, and 1 s of motor readings: the first one after it
        # starts can be stale (gripper reads closed), and the model must not plan from it.
        deadline = time.monotonic() + 3
        while (bridge.latest() is None or bridge.latest().seq < 10) and time.monotonic() < deadline:
            time.sleep(0.05)
        time.sleep(max(0.0, 1.0 - 0.1 * (bridge.latest().seq if bridge.latest() else 0)))
        cam = MjpegStream(f"http://{config.RPI_HOST}:{config.PI_STREAM_PORT}/")
        cam.name, cam.latency_s = "pi", config.PI_CAMERA_LATENCY_S
        try:
            self.cams["pi"] = cam.start()
            self.cam_status["pi"] = "on (via pi_bridge)"
        except Exception as exc:  # noqa: BLE001
            self.cam_status["pi"] = f"error: {exc}"

    def leave_drive(self) -> None:
        if self.bridge:
            self.bridge.stop()
            self.bridge = None
            self.note("pi_bridge.py stopped: wheels stopped, arm and gripper released")
        self._release(("pi", "motors"))

    def reconnect_after_drive(self) -> None:
        self.busy = "reconnecting"
        self._connect(("pi", "motors"))

    # safety

    def estop(self) -> None:
        run = self.run
        if run:
            run.estopped = True
        if self.bridge:
            self.bridge.stop()  # synchronous: the wheels stop before this returns
        if run and self.running:
            run.stop("EMERGENCY STOP")
        self.note("EMERGENCY STOP")

    def _deadman(self) -> None:
        while True:
            time.sleep(0.25)
            run = self.run
            if run and run.drive and self.running and not run.estopped \
                    and time.monotonic() - self.last_poll > DEADMAN_S:
                self.note(f"the page stopped polling for {DEADMAN_S:g} s")
                self.estop()

    def command_for(self, values: list[float]) -> dict:
        """One action -> the pi_bridge.py command, within the page's caps."""
        c = self.caps
        clamp = lambda v, lo, hi: max(lo, min(hi, v))  # noqa: E731
        cap = c["wheel_cap"]
        cmd = {"left": int(clamp(round(values[0]), -cap, cap)) if c["wheels"] else 0,
               "right": int(clamp(round(values[1]), -cap, cap)) if c["wheels"] else 0}
        if c["arm_grip"]:
            cmd["arm_pos"] = round(clamp(values[2], c["arm_min"], c["arm_max"]), 1)
            cmd["grip_pos"] = round(clamp(values[3], c["grip_min"], c["grip_max"]), 1)
        return cmd

    def set_caps(self, new: dict) -> None:
        c = dict(self.caps)
        for k in ("wheels", "arm_grip"):
            if k in new:
                c[k] = bool(new[k])
        for k in ("wheel_cap", "arm_min", "arm_max", "grip_min", "grip_max"):
            if k in new:
                c[k] = float(new[k])
        c["wheel_cap"] = max(0, min(HARD["wheel_cap"], c["wheel_cap"]))
        for j in ("arm", "grip"):
            lo, hi = HARD[j]
            c[f"{j}_min"], c[f"{j}_max"] = max(lo, c[f"{j}_min"]), min(hi, c[f"{j}_max"])
            if c[f"{j}_min"] > c[f"{j}_max"]:
                raise ValueError(f"{j}: min is above max")
        self.caps = c

    def start_run(self, body: dict) -> None:
        if self.running:
            raise RuntimeError("a run is already going")
        if self.busy:
            raise RuntimeError(f"wait: {self.busy}")
        if body.get("caps"):
            self.set_caps(body["caps"])
        seconds = float(body["seconds"]) if body.get("seconds") else None
        self.run = Run(self, body["spec"], body.get("task", ""), body.get("mode", "async"), bool(body.get("drive")),
                       seconds, int(body.get("refill_at", 10)), int(body.get("actions_per_chunk") or 0) or None)

    def snapshot(self) -> dict:
        self.last_poll = time.monotonic()
        state = self.motors.latest() if self.motors is not None else None
        try:
            readings = robot_readings(state.as_step(clock.now())) if state else None
        except Exception:  # noqa: BLE001
            readings = None
        return {
            "replay": self.replay, "busy": self.busy, "running": self.running,
            "cams": {n: {"status": s, "frames": getattr(self.cams.get(n), "count", None)}
                     for n, s in self.cam_status.items()},
            "motors": {"status": self.motor_status, "kind": self.motor_kind, "robot": readings},
            "model": self.model.snapshot(), "caps": self.caps, "hard": HARD,
            "run": self.run.snapshot() if self.run else None,
            "messages": list(self.messages)[-8:],
        }


# ── HTTP ──────────────────────────────────────────────────────────────────────

def options() -> dict:
    ckpts = []
    if (KIT / "model" / "config.json").exists():
        ckpts.append({"value": str((KIT / "model").relative_to(ROOT)), "label": "pick_cup (inference kit, job 181436)"})
    for d in sorted((ROOT / "models").glob("*/pretrained_model")) if (ROOT / "models").exists() else []:
        ckpts.append({"value": str(d.relative_to(ROOT)), "label": str(d.relative_to(ROOT))})
    ckpts += [{"value": "lerobot/smolvla_base", "label": "smolvla_base (untrained for Neil)"},
              {"value": "dummy", "label": "dummy (no model, holds still)"}]
    specs = sorted(str(p.relative_to(ROOT)) for p in (ROOT / "specs").glob("*.json"))
    default_spec = "specs/pick_cup_kit.json" if "specs/pick_cup_kit.json" in specs else specs[0]
    return {"checkpoints": ckpts, "specs": specs, "default_spec": default_spec, "task": "pick up the cup",
            "vla_python": vla_python(), "external_url": config.EXTERNAL_CAMERA_URL, "pi": config.RPI_HOST,
            "default_caps": DEFAULT_CAPS}


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    ctl: Controller

    def _json(self, obj, status=200):
        body = json.dumps(obj).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = self.path.split("?")[0]
        if path == "/":
            body = STATIC.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif path == "/api/state":
            self._json(self.ctl.snapshot())
        elif path == "/api/options":
            self._json(options())
        elif path.startswith("/stream/"):
            self._mjpeg(path.rsplit("/", 1)[1])
        else:
            self._json({"error": "not found"}, 404)

    def _mjpeg(self, name: str) -> None:
        """Re-serve a camera's newest frames to the page (the Pi's own server takes one viewer)."""
        self.send_response(200)
        self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=FRAME")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Connection", "close")
        self.end_headers()
        last = None
        try:
            while True:
                cam = self.ctl.cams.get(name)
                f = cam.latest() if cam else None
                if f is not None and f.index != last:
                    last = f.index
                    self.wfile.write(b"--FRAME\r\nContent-Type: image/jpeg\r\nContent-Length: "
                                     + str(len(f.jpeg)).encode() + b"\r\n\r\n" + f.jpeg + b"\r\n")
                time.sleep(1 / 15)
        except (BrokenPipeError, ConnectionResetError):
            pass
        self.close_connection = True

    def do_POST(self):
        n = int(self.headers.get("Content-Length") or 0)
        body = json.loads(self.rfile.read(n) or b"{}")
        ctl, path = self.ctl, self.path
        try:
            if path == "/api/estop":
                ctl.estop()
            elif path == "/api/connect":
                ctl.connect()
            elif path == "/api/disconnect":
                ctl.disconnect()
            elif path == "/api/model/start":
                ctl.model.start(body["checkpoint"], body.get("device", "mps"), int(body.get("port", 8001)))
                ctl.note(f"starting policy server: {body['checkpoint']} on {body.get('device', 'mps')}")
            elif path == "/api/model/use":
                ctl.model.use(body["url"])
            elif path == "/api/model/stop":
                if ctl.running:
                    raise RuntimeError("stop the run first")
                ctl.model.stop()
            elif path == "/api/run/start":
                ctl.start_run(body)
            elif path == "/api/run/stop":
                if ctl.run:
                    ctl.run.stop("stopped from the page")
            elif path == "/api/caps":
                ctl.set_caps(body)
            else:
                return self._json({"error": "not found"}, 404)
        except Exception as exc:  # noqa: BLE001
            return self._json({"error": str(exc)}, 400)
        self._json({"ok": True})

    def log_message(self, *a):
        pass


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--port", type=int, default=8090)
    ap.add_argument("--replay", metavar="SESSION_DIR", help="use a recorded session instead of Neil (no driving)")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s: %(message)s")
    signal.signal(signal.SIGTERM, lambda *_: (_ for _ in ()).throw(KeyboardInterrupt))  # clean up on kill too
    ctl = Controller(args.replay)
    Handler.ctl = ctl
    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    server.daemon_threads = True
    print(f"Neil control panel: http://127.0.0.1:{args.port}" + (f"  (replaying {args.replay})" if args.replay else ""))
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        print("Stopping ...")
        ctl.estop()
        if ctl.run:
            ctl.run._stop_evt.set()
        ctl._release(("pi", "external", "motors"))
        ctl.model.stop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
