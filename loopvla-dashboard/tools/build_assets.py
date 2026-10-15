"""Build the dashboard assets from the recorded pick_cup sessions.

Output (in ../assets):
  eps/<id>/t00.jpg ... top camera filmstrip
  eps/<id>/f00.jpg ... front (Pi) camera filmstrip
  live/<n>/000.jpg ... denser frame sequences for the "live" feed
  data.js          ... window.LOOP_DATA with one record per session
"""
import json
import sys
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parents[1] / "assets"

SETS = [
    # (folder, batch, {subfolder: position number})
    ("episodes/all sessions", "Batch A", {
        "first position": 1, "second position": 2, "third position": 3,
        "fourth position": 4, "fifth position": 5}),
    ("all poistions 2", "Batch B", {
        "first_spot": 1, "second": 2, "third position": 3,
        "fourth": 4, "fifht": 5}),
]
STRIP = 10          # frames per filmstrip
LIVE = ["all poistions 2/fourth/session_20261014_161923",
        "all poistions 2/second",
        "episodes/all sessions/third position"]


def thumb(src, dst, width, q=62):
    im = Image.open(src).convert("RGB")
    h = round(im.height * width / im.width)
    im.resize((width, h), Image.LANCZOS).save(dst, quality=q, optimize=True)


def series(steps, n=48):
    """Downsample the motor readings to n points per signal."""
    idx = [round(i * (len(steps) - 1) / (n - 1)) for i in range(n)]
    out = {"grip": [], "arm": [], "left": [], "right": []}
    for i in idx:
        m = steps[i].get("motors") or {}
        g = (m.get("gripper") or {}).get("abs_pos_deg")
        a = (m.get("arm") or {}).get("abs_pos_deg")
        lw = (m.get("left_wheel") or {}).get("speed")
        rw = (m.get("right_wheel") or {}).get("speed")
        out["grip"].append(None if g is None else -(g + 93))
        out["arm"].append(None if a is None else -(a - 14))
        out["left"].append(None if lw is None else -lw)
        out["right"].append(rw)
    return out


def main():
    (OUT / "eps").mkdir(parents=True, exist_ok=True)
    records = []
    for folder, batch, posmap in SETS:
        for sub, pos in posmap.items():
            for s in sorted((ROOT / folder / sub).glob("session_*")):
                info = json.loads((s / "info.json").read_text())
                steps = [json.loads(l) for l in (s / "steps.jsonl").open()]
                n = len(steps)
                sid = s.name.replace("session_", "")
                d = OUT / "eps" / sid
                d.mkdir(exist_ok=True)
                for k in range(STRIP):
                    i = round(k * (n - 1) / (STRIP - 1))
                    st = steps[i]
                    if not (d / f"t{k:02d}.jpg").exists():
                        thumb(s / st["external"]["file"], d / f"t{k:02d}.jpg", 400)
                        thumb(s / st["pi"]["file"], d / f"f{k:02d}.jpg", 280)
                cams = info.get("cameras", {})
                records.append({
                    "id": sid,
                    "batch": batch,
                    "pos": pos,
                    "time": f"{sid[9:11]}:{sid[11:13]}:{sid[13:15]}",
                    "steps": n,
                    "dur": info.get("duration_s"),
                    "fps": info.get("fps"),
                    "skew": (info.get("skew_ms") or {}).get("median"),
                    "camAge": (cams.get("pi", {}).get("age_ms") or {}).get("median"),
                    "missing": sum(c.get("missing_steps", 0) for c in cams.values()),
                    "sig": series(steps),
                })
                print(batch, pos, sid, n, file=sys.stderr)

    live = []
    for k, p in enumerate(LIVE):
        p = ROOT / p
        s = p if p.name.startswith("session_") else sorted(p.glob("session_*"))[0]
        files = sorted((s / "external").glob("*.jpg"))[::2]
        d = OUT / "live" / str(k)
        d.mkdir(parents=True, exist_ok=True)
        for j, f in enumerate(files):
            if not (d / f"{j:03d}.jpg").exists():
                thumb(f, d / f"{j:03d}.jpg", 720, q=58)
        live.append({"id": s.name.replace("session_", ""), "n": len(files)})

    (OUT / "data.js").write_text(
        "window.LOOP_DATA = " + json.dumps({"episodes": records, "live": live}) + ";\n")
    print(len(records), "episodes", file=sys.stderr)


if __name__ == "__main__":
    main()
