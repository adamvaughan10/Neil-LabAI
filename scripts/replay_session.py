"""
Replay a recorded session on the robot and report how closely it repeats.
THIS MOVES THE ROBOT: put it back where the recording started, keep hands clear.

    python scripts/replay_session.py logs/session_20261013_154547
    python scripts/replay_session.py logs/session_20261013_154547 --start 10 --end 25
    python scripts/replay_session.py logs/session_20261013_154547 --dry-run   just show the plan

It re-sends the session's "hat_commands" (the exact Build HAT calls the Pi made while
recording with gamepad_drive.py --record) at their recorded times. pi/replay_server.py
makes the calls, timed on the Pi, and streams the motors' measured speed and angle back.
Sessions recorded before hat_commands existed can't be replayed.

The replay is then compared with the recording's "motors" readings, motor by motor:
speed error, and angle error counted from where each motor started (the encoders
don't return to the same angles, and every command is relative). Results go to
<session>/replays/<date>_<time>/: report.json, plus the replay's states.jsonl and
calls.jsonl. --compare re-prints the report of a saved replay without the robot.
"""
import argparse
import bisect
import json
import shlex
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from neil_robot import config  # noqa: E402
from neil_robot.motor_stream import ROLES  # noqa: E402

WHEELS = (config.PORT_LEFT_WHEEL, config.PORT_RIGHT_WHEEL)
HOLD = (config.PORT_ARM, config.PORT_GRIPPER)


def load_session(session: Path, start: float, end: float | None):
    """The recorded calls and motor readings, timed in seconds from --start."""
    steps = [json.loads(line) for line in (session / "steps.jsonl").open()]
    t0 = steps[0]["t"] + start
    stop = steps[0]["t"] + end if end is not None else float("inf")
    calls = [{"t": round(c["ts"] - t0, 4), "port": c["port"], "call": c["call"],
              "speed": c["speed"], "degrees": c["degrees"]}
             for s in steps if s.get("hat_commands") for c in s["hat_commands"]["new"]
             if t0 <= c["ts"] < stop]
    samples, last_seq = [], None
    for s in steps:
        m = s.get("motors")
        if not m or m["seq"] == last_seq or not t0 <= m["ts"] < stop:
            continue  # the same reading repeats until a new one arrives
        last_seq = m["seq"]
        samples.append({"t": m["ts"] - t0, **{port: [m[role]["speed"], m[role]["pos_deg"]]
                                               for port, role in ROLES.items()}})
    return sorted(calls, key=lambda c: c["t"]), samples


def interp(samples: list[dict], port: str, i: int, t: float) -> float:
    """samples[port][i] at time t, linear between readings, held past either end."""
    j = bisect.bisect_left(samples, t, key=lambda s: s["t"])
    if j == 0:
        return samples[0][port][i]
    if j == len(samples):
        return samples[-1][port][i]
    a, b = samples[j - 1], samples[j]
    f = (t - a["t"]) / (b["t"] - a["t"]) if b["t"] > a["t"] else 1.0
    return a[port][i] + f * (b[port][i] - a[port][i])


def compare(recorded: list[dict], replayed: list[dict], lag: float = 0.0) -> dict:
    """Per motor: errors of the replay against the recording at each recorded reading.
    Angles count from each run's first reading. lag shifts the replay later in time."""
    out = {}
    for port, role in ROLES.items():
        rec0, rep0 = recorded[0][port][1], replayed[0][port][1]
        speed_err, pos_err = [], []
        for s in recorded:
            speed_err.append(interp(replayed, port, 0, s["t"] + lag) - s[port][0])
            pos_err.append((interp(replayed, port, 1, s["t"] + lag) - rep0) - (s[port][1] - rec0))
        rms = lambda e: (sum(x * x for x in e) / len(e)) ** 0.5
        out[role] = {"port": port,
                     "speed_rms": round(rms(speed_err), 2), "speed_max": round(max(map(abs, speed_err)), 2),
                     "angle_rms_deg": round(rms(pos_err), 2), "angle_max_deg": round(max(map(abs, pos_err)), 2),
                     "angle_end_deg": round(pos_err[-1], 2),
                     "recorded_travel_deg": round(recorded[-1][port][1] - rec0, 1),
                     "replayed_travel_deg": round(interp(replayed, port, 1, recorded[-1]["t"] + lag) - rep0, 1)}
    return out


def report(calls: list[dict], done_calls: list[dict], recorded: list[dict], replayed: list[dict]) -> dict:
    late = [c["t"] - c["planned"] for c in done_calls]
    # The lag that fits best, as a check on timing: wheel angle error over -0.5..+0.5 s.
    wheel_rms = lambda lag: sum(compare(recorded, replayed, lag)[ROLES[p]]["angle_rms_deg"] for p in WHEELS)
    best = min((round(x * 0.01, 2) for x in range(-50, 51)), key=wheel_rms)
    return {"calls_planned": len(calls), "calls_made": len(done_calls),
            "call_late_ms": {"mean": round(1000 * sum(late) / len(late), 2) if late else None,
                             "max": round(1000 * max(late), 2) if late else None},
            "recorded_readings": len(recorded), "replayed_readings": len(replayed),
            "motors": compare(recorded, replayed), "best_lag_s": best,
            "motors_at_best_lag": compare(recorded, replayed, best) if best else None}


def print_report(r: dict) -> None:
    print(f"\n{r['calls_made']}/{r['calls_planned']} calls made, late by {r['call_late_ms']['mean']} ms "
          f"on average (max {r['call_late_ms']['max']} ms).")
    print(f"{'motor':12} {'speed rms':>9} {'max':>6} | {'angle rms':>9} {'max':>6} {'at end':>7} | "
          f"{'recorded':>8} {'replayed':>8} travel (deg)")
    for role, m in r["motors"].items():
        print(f"{role:12} {m['speed_rms']:9.1f} {m['speed_max']:6.1f} | {m['angle_rms_deg']:9.1f} "
              f"{m['angle_max_deg']:6.1f} {m['angle_end_deg']:+7.1f} | "
              f"{m['recorded_travel_deg']:+8.1f} {m['replayed_travel_deg']:+8.1f}")
    if r["best_lag_s"]:
        print(f"Wheel angles fit best with the replay shifted {r['best_lag_s']:+.2f} s; "
              "motors_at_best_lag in report.json has the errors at that shift.")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("session", type=Path, help="a logs/session_<date>_<time> folder")
    ap.add_argument("--start", type=float, default=0.0, help="replay from this many seconds in")
    ap.add_argument("--end", type=float, help="replay up to this many seconds in (default: the end)")
    ap.add_argument("--tail", type=float, default=2.0, help="seconds to keep reading after the last call")
    ap.add_argument("--state-hz", type=float, default=config.MOTOR_STREAM_HZ, help="motor readings per second")
    ap.add_argument("--dry-run", action="store_true", help="print the calls and stop; the robot isn't touched")
    ap.add_argument("--yes", action="store_true", help="don't ask before moving the robot")
    ap.add_argument("--compare", type=Path, metavar="REPLAY_DIR",
                    help="re-print the report of a saved replay (no robot)")
    args = ap.parse_args()

    calls, recorded = load_session(args.session, args.start, args.end)
    if not calls or len(recorded) < 2:
        print(f"No hat_commands or motor readings in {args.session} (in that window): nothing to replay.")
        return 1
    if args.compare:
        r = json.loads((args.compare / "report.json").read_text())
        print_report(r)
        return 0
    span = calls[-1]["t"] - calls[0]["t"]
    print(f"{len(calls)} Build HAT calls from {calls[0]['t']:.2f} s to {calls[-1]['t']:.2f} s ({span:.1f} s), "
          f"{len(recorded)} recorded readings.")
    if args.dry_run:
        for c in calls:
            extra = f" speed {c['speed']}" if c["speed"] is not None else ""
            extra += f" degrees {c['degrees']}" if c["degrees"] is not None else ""
            print(f"  {c['t']:8.3f}  {c['port']} {c['call']}{extra}")
        return 0

    from neil_robot.rpi_client import RPiClient  # paramiko; not needed for --dry-run

    settings = {"ports": list(ROLES), "wheels": list(WHEELS), "hold": list(HOLD),
                "state_hz": args.state_hz, "tail": args.tail}
    code = (ROOT / "pi" / "replay_server.py").read_text()
    replayed, done_calls = [], []
    print(f"Connecting to {config.RPI_USER}@{config.RPI_HOST} ...")
    with RPiClient() as pi:
        stdin, stdout, _ = pi.connect().exec_command(
            f"python3 -u -c {shlex.quote(code)} {shlex.quote(json.dumps(settings))} 2>&1")
        for line in stdout:  # wait for the HAT (it may load firmware first)
            if line.startswith("ready "):
                now = json.loads(line[len("ready "):])
                break
            print("Pi:", line, end="")
        else:
            print("The Pi script stopped before it was ready.")
            return 1
        print("Angles now vs when the recording started (only the change is replayed):")
        for port in HOLD:
            print(f"  {ROLES[port]:8} now {now[port][1]:+5d}   recorded {recorded[0][port][1]:+5d}")
        if not args.yes and input("Replay on the robot? [y/N] ").strip().lower() != "y":
            stdin.channel.shutdown_write()
            return 1
        stdin.write(json.dumps(calls) + "\n")
        stdin.flush()
        print("Replaying. Ctrl-C stops the robot.")
        try:
            for line in stdout:
                kind, _, body = line.partition(" ")
                if kind == "state":
                    s = json.loads(body)
                    if "error" not in s:
                        replayed.append({"t": s["t"], **{p: s[p][:2] for p in ROLES}})
                elif kind == "hat":
                    done_calls.append(json.loads(body))
                    c = done_calls[-1]
                    print(f"  {c['t']:8.3f}  {c['port']} {c['call']}", flush=True)
                elif kind == "done":
                    break
                else:
                    print("Pi:", line, end="")
        except KeyboardInterrupt:
            print("\nStopping.")
        finally:
            stdin.channel.shutdown_write()

    if len(replayed) < 2:
        print("Too few motor readings came back to compare.")
        return 1
    out = args.session / "replays" / time.strftime("%Y%m%d_%H%M%S")
    out.mkdir(parents=True)
    (out / "states.jsonl").write_text("".join(json.dumps(s) + "\n" for s in replayed))
    (out / "calls.jsonl").write_text("".join(json.dumps(c) + "\n" for c in done_calls))
    r = {"session": str(args.session), "start": args.start, "end": args.end,
         "start_angles": {"recorded": {ROLES[p]: recorded[0][p][1] for p in ROLES},
                          "replay": {ROLES[p]: now[p][1] for p in ROLES}},
         **report(calls, done_calls, recorded, replayed)}
    (out / "report.json").write_text(json.dumps(r, indent=2) + "\n")
    print_report(r)
    print(f"Saved to {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
