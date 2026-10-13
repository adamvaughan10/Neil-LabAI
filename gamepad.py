"""Read the USB gamepad and print its sticks and buttons live.

The pad shows up on macOS as "usb gamepad" (USB 0810:E501). SDL/pygame does not
see it without Input Monitoring permission, so this reads the raw HID report
with hidapi instead.

Output matches the data contract's `gamepad` field:
    {"axes": [4 floats, -1..1], "buttons": [12 ints, 0 or 1]}

Raw report layout (8 bytes, report id 1):
    byte 0     report id (1)
    bytes 1-4  axes, 0..255 with ~128 at rest
    byte 5     low nibble: hat (15 = centred), high nibble: buttons 1-4
    byte 6     buttons 5-12
    byte 7     unused

Run:  .venv/bin/python gamepad.py          (live line, Ctrl-C to quit)
      .venv/bin/python gamepad.py --raw    (also show the raw bytes)
      .venv/bin/python gamepad.py --log    (one JSON line per change)
"""
import argparse
import json
import sys

import hid

VENDOR_ID = 0x0810
PRODUCT_ID = 0xE501
DEADZONE = 0.05  # rest values sit at 127/128, not exactly centre

HAT_NAMES = {0: "N", 1: "NE", 2: "E", 3: "SE", 4: "S", 5: "SW", 6: "W", 7: "NW", 15: "-"}


def _axis(raw: int) -> float:
    v = (raw - 127.5) / 127.5
    v = max(-1.0, min(1.0, v))
    return 0.0 if abs(v) < DEADZONE else round(v, 3)


def decode(report: list[int]) -> dict:
    """Turn one raw HID report into the contract's {"axes", "buttons"} dict."""
    axes = [_axis(b) for b in report[1:5]]
    bits = (report[5] >> 4) | (report[6] << 4)
    buttons = [(bits >> i) & 1 for i in range(12)]
    return {"axes": axes, "buttons": buttons}


def hat(report: list[int]) -> str:
    return HAT_NAMES.get(report[5] & 0x0F, "?")


class Gamepad:
    def __init__(self, vendor_id: int = VENDOR_ID, product_id: int = PRODUCT_ID):
        self._dev = hid.device()
        self._dev.open(vendor_id, product_id)
        self._dev.set_nonblocking(True)
        self.report = [1, 128, 128, 128, 128, 15, 0, 0]

    def poll(self) -> dict:
        """Drain pending reports and return the latest state (never blocks)."""
        while True:
            r = self._dev.read(64)
            if not r:
                break
            self.report = r
        return decode(self.report)

    def wait(self, timeout_ms: int = 100) -> dict:
        """Block until a new report arrives (or timeout), then return the state."""
        self._dev.set_nonblocking(False)
        r = self._dev.read(64, timeout_ms)
        self._dev.set_nonblocking(True)
        if r:
            self.report = r
        return self.poll()

    def close(self) -> None:
        self._dev.close()


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--raw", action="store_true", help="also show raw report bytes")
    p.add_argument("--log", action="store_true", help="print one JSON line per change instead of a live line")
    args = p.parse_args()

    try:
        pad = Gamepad()
    except OSError as e:
        sys.exit(f"Could not open gamepad {VENDOR_ID:04x}:{PRODUCT_ID:04x}: {e}")

    last = None
    try:
        while True:
            state = pad.wait()
            key = tuple(pad.report)
            if key == last:
                continue
            last = key
            if args.log:
                out = dict(state, hat=hat(pad.report))
                if args.raw:
                    out["raw"] = list(pad.report)
                print(json.dumps(out), flush=True)
                continue
            axes = " ".join(f"{a:+.2f}" for a in state["axes"])
            pressed = [str(i) for i, b in enumerate(state["buttons"]) if b]
            line = f"axes [{axes}]  hat {hat(pad.report):>2}  buttons [{' '.join(pressed) or '-'}]"
            if args.raw:
                line += f"  raw {list(pad.report)}"
            print("\r" + line.ljust(100), end="", flush=True)
    except KeyboardInterrupt:
        print()
    finally:
        pad.close()


if __name__ == "__main__":
    main()
