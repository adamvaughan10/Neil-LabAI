"""Name the pad's face buttons: press one, type what's printed on it, repeat.

Saves {"0": "A", ...} to gamepad_labels.json, which gamepad.py uses when printing.
"""
import json
from pathlib import Path

from gamepad import Gamepad

LABELS_FILE = Path(__file__).with_name("gamepad_labels.json")
NUM_BUTTONS = 4


def wait_for_press(pad: Gamepad) -> int:
    while any(pad.wait()["buttons"]):  # wait for release first
        pass
    while True:
        pressed = [i for i, b in enumerate(pad.wait()["buttons"]) if b]
        if pressed:
            return pressed[0]


def main() -> None:
    pad = Gamepad()
    labels = {}
    try:
        while len(labels) < NUM_BUTTONS:
            print(f"Press a button you haven't named yet ({len(labels)}/{NUM_BUTTONS} done)...", flush=True)
            i = wait_for_press(pad)
            if str(i) in labels:
                print(f"  button {i} is already '{labels[str(i)]}', press another one")
                continue
            labels[str(i)] = input(f"  button {i}: what's printed or coloured on it? ").strip() or str(i)
    finally:
        pad.close()
    LABELS_FILE.write_text(json.dumps(labels, indent=2) + "\n")
    print(f"Saved {labels} to {LABELS_FILE.name}")


if __name__ == "__main__":
    main()
