"""
Record a session with the gamepad, then play it back on the robot and report how
closely the replay matches. THIS MOVES THE ROBOT, twice.

    python scripts/record_replay.py                  record (Ctrl-C ends it), then replay
    python scripts/record_replay.py --no-external    record the Pi camera only
    python scripts/record_replay.py --speed 40       other options go to gamepad_drive.py

1. Runs scripts/gamepad_drive.py --record: drive as usual, Ctrl-C stops and saves.
2. Runs scripts/replay_session.py on the new session: put the robot back where the
   recording started and answer y. It re-sends the recorded Build HAT calls at their
   recorded times and compares the motors with the recording.
"""
import signal
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOGS = ROOT / "logs"


def main() -> int:
    if any(a in ("-h", "--help") for a in sys.argv[1:]):
        print(__doc__)
        return 0
    before = set(LOGS.glob("session_*")) if LOGS.exists() else set()
    # Ctrl-C reaches gamepad_drive.py too and ends the recording; this waits while it saves.
    drive = subprocess.Popen([sys.executable, str(ROOT / "scripts" / "gamepad_drive.py"), "--record", *sys.argv[1:]])
    signal.signal(signal.SIGINT, signal.SIG_IGN)
    drive.wait()
    signal.signal(signal.SIGINT, signal.default_int_handler)
    new = sorted(set(LOGS.glob("session_*")) - before)
    if not new:
        print("No new session was recorded.")
        return 1
    session = new[-1]
    print(f"\nRecorded {session}.")
    print("Put the robot back where the recording started; the replay asks before it moves.")
    return subprocess.run([sys.executable, str(ROOT / "scripts" / "replay_session.py"), str(session)]).returncode


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print()
        sys.exit(1)
