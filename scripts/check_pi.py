"""
Read-only health check of the robot. Nothing moves.

    python scripts/check_pi.py            # system + Build HAT + camera
    python scripts/check_pi.py --no-hat   # skip the Build HAT
    python scripts/check_pi.py --no-camera

Checks SSH, the Pi's OS and serial setup, the Python libraries, the Build HAT's
input voltage and what is plugged into each port (with motor positions), and
saves one camera still to output/.
"""
import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from neil_robot import config, hardware  # noqa: E402
from neil_robot.rpi_client import RPiClient, RPiError  # noqa: E402

OK, WARN, FAIL = "OK  ", "WARN", "FAIL"


def line(status: str, label: str, detail="") -> None:
    print(f"[{status}] {label:<22} {detail}")


def check_system(pi: RPiClient) -> bool:
    info = hardware.system_info(pi)
    line(OK, "Pi", f"{info['model']} | {info['os']} | host {info['hostname']} | python {info['python']}")
    good = True
    if info["enable_uart"] and not info["serial_console_on_uart"]:
        line(OK, "serial port", f"enabled, {info['serial0']}")
    else:
        good = False
        line(FAIL, "serial port",
             f"enable_uart={info['enable_uart']}, login console on UART={info['serial_console_on_uart']} "
             "-> sudo raspi-config: Interface Options > Serial Port > login shell No, hardware Yes; reboot")
    for grp in ("dialout", "video"):
        if grp not in info["groups"]:
            line(WARN, f"group {grp}", f"user {info['user']} is not in it")
    for pkg, apt in (("buildhat", "python3-build-hat"), ("picamera2", "python3-picamera2")):
        ver = info["packages"][pkg]
        if ver:
            line(OK, pkg, ver)
        else:
            good = False
            line(FAIL, pkg, f"missing -> sudo apt install {apt}")
    return good


def check_hat(pi: RPiClient) -> bool:
    print("       (connecting to the Build HAT; the first time can take ~10 s while it loads firmware)")
    st = hardware.hat_status(pi)
    vin = st["vin"]
    if vin >= 7.0:
        line(OK, "HAT input voltage", f"{vin:.1f} V")
    else:
        line(WARN, "HAT input voltage", f"{vin:.1f} V -- motors need the 8 V barrel jack plugged in")
    for port in config.PORTS:
        d = st["ports"].get(port, {})
        if not d.get("connected"):
            line(WARN, f"port {port}", "nothing connected")
            continue
        detail = f"{d.get('name')} ({d.get('description')})"
        if "position" in d:
            detail += f" | position {d['position']}°, absolute {d['absolute_position']}°"
        line(FAIL if "error" in d else OK, f"port {port}", detail + (f" | {d['error']}" if "error" in d else ""))
    return vin >= 7.0


def check_camera(pi: RPiClient) -> bool:
    model, jpeg = hardware.capture_still(client=pi)
    config.OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    path = config.OUTPUT_DIR / f"camera_{time.strftime('%Y%m%d_%H%M%S')}.jpg"
    path.write_bytes(jpeg)
    line(OK, "camera", f"{model}, saved {path} ({len(jpeg) // 1024} KB)")
    return True


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--no-hat", action="store_true")
    ap.add_argument("--no-camera", action="store_true")
    ap.add_argument("-v", "--verbose", action="store_true", help="print full Pi-side tracebacks")
    args = ap.parse_args()

    print(f"Connecting to {config.RPI_USER}@{config.RPI_HOST} ...")
    try:
        pi = RPiClient()
        pi.connect()
    except Exception as exc:  # noqa: BLE001
        line(FAIL, "ssh", exc)
        return 1
    line(OK, "ssh", "connected with key")

    all_good = True
    steps = [("system", check_system)]
    if not args.no_hat:
        steps.append(("Build HAT", check_hat))
    if not args.no_camera:
        steps.append(("camera", check_camera))
    with pi:
        for name, fn in steps:
            try:
                all_good &= fn(pi)
            except RPiError as exc:
                all_good = False
                line(FAIL, name, str(exc).splitlines()[0])
                if args.verbose:
                    print(exc)
    print("\nAll checks passed." if all_good else "\nSome checks need attention (see above).")
    return 0 if all_good else 1


if __name__ == "__main__":
    sys.exit(main())
