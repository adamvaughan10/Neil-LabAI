"""
Run a VLA policy on Neil in real time: cameras + motor state go to the policy server
at every step, action chunks come back. DRY RUN: actions are logged, nothing moves.

Start the policy server first (in the neil_vla env, see policy_server/README.md), then:

    python scripts/run_policy.py                                   # live robot, until Ctrl+C
    python scripts/run_policy.py --seconds 20                      # stop after 20 s
    python scripts/run_policy.py --replay logs/session_20261013_144751   # no robot: replay a recording
    python scripts/run_policy.py --mode async --refill-at 10       # ask early, keep acting meanwhile
    python scripts/run_policy.py --server http://127.0.0.1:8001 --task "pick up the cup"

Everything is recorded like stream_cameras.py does, into logs/run_<date>_<time>/:
    pi/ external/ steps.jsonl info.json *.mp4    as a normal recording, plus per step
                                                 "action" (or null while waiting) and "policy"
    inference.jsonl                              one line per request: latency, skipped actions
    policy.json                                  server info, observation spec, run settings
"""
import argparse
import json
import logging
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from neil_robot import clock, config  # noqa: E402
from neil_robot.motor_stream import MotorStateStream  # noqa: E402
from neil_robot.observation import ObservationSpec  # noqa: E402
from neil_robot.policy_client import DEFAULT_URL, PolicyClient, PolicyServerError  # noqa: E402
from neil_robot.policy_runner import PolicyRunner  # noqa: E402
from neil_robot.recorder import SyncRecorder  # noqa: E402
from neil_robot.replay import ReplaySession  # noqa: E402
from neil_robot.streams import ExternalCameraStream, PiCameraStream  # noqa: E402


def check_spec(spec: ObservationSpec, info: dict, allow_missing_images: bool = False) -> list[str]:
    """Differences between what we will send and what the policy was trained on."""
    feats = info.get("input_features") or {}
    if not feats:
        return []
    problems = []
    want_imgs = {k for k in feats if k.startswith("observation.images.")}
    if (missing := sorted(want_imgs - set(spec.images))) and not allow_missing_images:
        problems.append(f"policy needs images {missing}, spec sends {sorted(spec.images)}")
    if "observation.state" in feats and feats["observation.state"][0] != len(spec.state):
        problems.append(f"policy needs {feats['observation.state'][0]} state values, spec sends {len(spec.state)}")
    if spec.action and info.get("action_dim") != len(spec.action):
        problems.append(f"policy returns {info.get('action_dim')} action values, spec names {len(spec.action)}")
    return problems


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--server", default=DEFAULT_URL, help=f"policy server URL (default {DEFAULT_URL})")
    ap.add_argument("--spec", help="observation spec JSON (default: both cameras + 4 motor positions)")
    ap.add_argument("--task", help="language instruction (default: the spec's)")
    ap.add_argument("--mode", choices=("sync", "async"), default="sync")
    ap.add_argument("--refill-at", type=int, default=10, help="async: ask for a new chunk when this many actions are left")
    ap.add_argument("--actions-per-chunk", type=int, help="use only the first N actions of each chunk")
    ap.add_argument("--seconds", type=float, help="stop after this long (default: until Ctrl+C; replay: its length)")
    ap.add_argument("--fps", type=float, help="steps per second (default 15; replay: its own rate)")
    ap.add_argument("--replay", metavar="SESSION_DIR", help="use a recorded session instead of the robot")
    ap.add_argument("--no-videos", action="store_true", help="don't make mp4s at the end")
    ap.add_argument("--allow-missing-images", action="store_true",
                    help="run even if the policy has image inputs the spec doesn't fill (testing only)")
    args = ap.parse_args()
    sys.stdout.reconfigure(errors="replace")  # the repo path is Hebrew; some consoles can't print it
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")

    spec = ObservationSpec.load(args.spec) if args.spec else ObservationSpec.default()
    client = PolicyClient(args.server)
    print(f"Policy server {args.server} ...")
    try:
        info = client.wait_ready(wait_s=10)
    except PolicyServerError as exc:
        print(f"  {exc}\n  Start it first: python policy_server/server.py --dummy   (or --checkpoint ...)")
        return 1
    print(f"  {info['policy']} on {info['device']}: {info['chunk_size']} actions x {info['action_dim']} values"
          + (f", inputs {info['input_features']}" if info.get("input_features") else ""))
    if problems := check_spec(spec, info, args.allow_missing_images):
        print("  Observation spec doesn't match the policy:\n    " + "\n    ".join(problems))
        return 1

    if args.replay:
        session = ReplaySession(args.replay)
        streams = {n: c for n, c in session.cameras().items() if n in spec.cameras}
        motors = session.motors()
        args.fps = args.fps or session.fps
        args.seconds = args.seconds or len(session.rows) / session.fps
        print(f"Replaying {session.dir}: {len(session.rows)} steps at {session.fps:g} fps ({args.seconds:g} s)")
    else:
        streams = {}
        if "pi" in spec.cameras:
            streams["pi"] = PiCameraStream()
        if "external" in spec.cameras:
            streams["external"] = ExternalCameraStream()
        motors = MotorStateStream() if spec.state else None
    args.fps = args.fps or config.RECORD_FPS

    started = []
    runner = rec = None
    try:
        for name, s in streams.items():
            print(f"Connecting to {name} camera ({s.url}) ...")
            s.start()
            started.append(s)
        if motors:
            print("Connecting to the motors (read-only) ...")
            motors.start()
            motors.check_ready()

        def motor_step(t: float) -> dict | None:
            state = motors.latest()
            return None if state is None else state.as_step(t)

        runner = PolicyRunner(client, spec, mode=args.mode, refill_at=args.refill_at,
                              actions_per_chunk=args.actions_per_chunk, task=args.task)
        out_dir = config.LOGS_DIR / f"run_{time.strftime('%Y%m%d_%H%M%S')}"
        rec = SyncRecorder(streams, fps=args.fps, out_dir=out_dir, extras={"motors": motor_step} if motors else None,
                           make_videos=not args.no_videos, on_step=runner.on_step)
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "policy.json").write_text(json.dumps(
            {"server": args.server, "server_info": info, "spec": spec.to_dict(), "task": args.task or spec.task,
             "mode": args.mode, "refill_at": runner.refill_at, "actions_per_chunk": args.actions_per_chunk,
             "replay": args.replay, "dry_run": True}, indent=2))
        runner.start(out_dir)
        if args.replay:
            session.t0 = clock.now() + 0.05  # the recorder's first tick: replay from step 0
        rec.start()
        print(f"Running ({args.mode}, DRY RUN: nothing moves) -> {out_dir}   Ctrl+C stops")
        try:
            while args.seconds is None or rec.elapsed < args.seconds:
                end = clock.now() + 1.0
                clock.sleep_until(end if args.seconds is None else min(end, rec.t0 + args.seconds))
                lat = runner.latencies_ms[-1] if runner.latencies_ms else None
                print(f"  {rec.elapsed:6.1f} s  step {rec.steps:5d}  chunks {len(runner.latencies_ms):4d}  "
                      f"last round trip {'-' if lat is None else f'{lat:.0f} ms'}  errors {runner.errors}"
                      + (f"  ({runner.last_error[:80]})" if runner.last_error else ""))
        except KeyboardInterrupt:
            pass
        print("Stopping ...")
        rec, summary = None, rec.stop()  # first, so no steps are added after the end
        runner.stop()                    # waits for a request still in flight, to log it
        lats = sorted(runner.latencies_ms)
        held = sum(1 for l in (out_dir / "steps.jsonl").read_text(encoding="utf-8").splitlines()
                   if json.loads(l).get("action") is None)
        print(f"{summary['steps']} steps, {len(lats)} chunks, {runner.errors} failed requests; "
              f"round trip median {lats[len(lats) // 2]:.0f} ms, max {lats[-1]:.0f} ms; " if lats else
              f"{summary['steps']} steps, no chunk received ({runner.errors} failed requests); ",
              end="")
        print(f"{held} steps held while waiting.\nSaved to {out_dir}")
        return 0 if lats else 1
    except Exception as exc:  # noqa: BLE001
        print(f"Failed: {exc}")
        return 1
    finally:
        if runner:
            runner.stop()
        if rec:
            rec.stop()
        for s in started:
            s.stop()
        if motors:
            motors.stop()
        client.close()


if __name__ == "__main__":
    sys.exit(main())
