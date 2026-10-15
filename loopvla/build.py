"""Build the LoopVLA mock dashboard from dashboard_sample_data/.

    python loopvla/build.py                      # writes loopvla/index.html + loopvla/data.js (offline copy)
    python loopvla/build.py --artifact OUT_DIR   # writes OUT_DIR/page.html + OUT_DIR/data.js for publishing

The page source is loopvla/body.html. Videos are not copied: the offline copy points at
../dashboard_sample_data/, the artifact copy at media/ (published alongside the page).
"""
import argparse
import glob
import json
import os
import re

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "..", "dashboard_sample_data")

FONTS = ('<link rel="stylesheet" href="https://fonts.googleapis.com/css2?'
         'family=Archivo:wdth,wght@62..125,400..800&family=IBM+Plex+Mono:wght@400;500'
         '&family=IBM+Plex+Sans:wght@400;500;600&display=swap">')


def load(path):
    with open(os.path.join(DATA, path), encoding="utf-8") as f:
        return json.load(f)


def labels():
    out = []
    for f in sorted(glob.glob(os.path.join(DATA, "classifier_labels", "attempts", "*.json"))):
        with open(f, encoding="utf-8") as fh:
            a = json.load(fh)
        m = re.search(r"__([a-z]+)_position__session_(\d{8})_(\d{6})", a["name"])
        if m:
            where = m.group(1).capitalize() + " spot"
            hhmmss = m.group(3)
        else:
            where = "Early session" if "previous" in a["name"] else "Demo episode"
            t = re.search(r"_(\d{6})$", a["name"])
            hhmmss = t.group(1) if t else ""
        out.append({
            "name": a["name"],
            "where": where,
            "time": f"{hhmmss[:2]}:{hhmmss[2:4]}" if hhmmss else "",
            "success": a["success"],
            "confidence": a["confidence"],
            "category": a["failure_category"],
            "cup": a["cup_final_state"],
            "reason": a["reason"].replace("�", "–"),
            "duration_s": a["duration_s"],
            "key_frame_s": a["key_frame_s"],
            "cost_usd": round(a["usage"]["cost_usd"], 4),
            "human_label": a.get("label"),
        })
    return out


def rollouts(video_base):
    out = []
    for r in load("vla_rollouts/index.json"):
        if not r["steps"]:
            out.append({"id": r["id"], "outcome": r["outcome"], "note": r["note"], "steps": 0})
            continue
        with open(os.path.join(DATA, r["path"], "steps.jsonl"), encoding="utf-8") as f:
            steps = [json.loads(line) for line in f]
        t0 = steps[0]["t"]
        out.append({
            "id": r["id"],
            "model": r["model"],
            "outcome": r["outcome"],
            "success": r["success"],
            "note": r["note"],
            "duration_s": r["duration_s"],
            "steps": len(steps),
            "final_state": r["final_state"],
            # t, left/right wheel command (sent), arm/grip angle (state), new action chunk
            "series": [[round(s["t"] - t0, 2), s["sent"][0], s["sent"][1], s["state"][2], s["state"][3],
                        1 if s["new_plan"] else 0] for s in steps],
            # engineer view: t, action[4] (model), sent[4] (to motors), state[4] (measured), new_plan, wheel_deg[2]
            "full": [[round(s["t"] - t0, 3), *[round(v, 2) for v in s["action"]], *s["sent"], *s["state"],
                      1 if s["new_plan"] else 0, *s["wheel_deg"]] for s in steps],
            "config": load(os.path.join(r["path"], "run.json")),
            "front": video_base + r["path"] + "/front.mp4",
            "top": video_base + r["path"] + "/top.mp4",
        })
    return out


def episodes(video_base):
    out = []
    for e in load("training_episodes/index.json"):
        meta = load(os.path.join(e["path"], "episode.json"))
        with open(os.path.join(DATA, e["path"], "frames.jsonl"), encoding="utf-8") as f:
            frames = [json.loads(line) for line in f]
        t0 = frames[0]["t"]
        st = lambda d: [d["left_speed"], d["right_speed"], d["arm_pos"], d["grip_pos"]]
        tg = lambda d: [d["left"], d["right"], d["arm"], d["grip"]]
        out.append({**e, "position": meta.get("position"), "source": meta.get("source"),
                    "action_kind": meta.get("action"),
                    # t, target[4] (operator), state[4] (measured)
                    "full": [[round(fr["t"] - t0, 3), *tg(fr["target"]), *st(fr["state"])] for fr in frames],
                    "video": video_base + e["path"] + "/side_by_side.mp4",
                    "front": video_base + e["path"] + "/front.mp4",
                    "top": video_base + e["path"] + "/top.mp4"})
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--artifact", help="output folder for the publishable copy")
    args = ap.parse_args()

    video_base = "media/" if args.artifact else "../dashboard_sample_data/"
    summary = load("classifier_labels/summary.json")
    data = {
        "summary": {k: summary[k] for k in ("when", "model", "frames", "attempts", "successes",
                                             "success_rate", "failure_categories", "mean_confidence",
                                             "label_agreement", "by_folder")},
        "labels": labels(),
        "rollouts": rollouts(video_base),
        "episodes": episodes(video_base),
    }
    js = "window.LOOPVLA = " + json.dumps(data, separators=(",", ":")) + ";\n"
    with open(os.path.join(HERE, "body.html"), encoding="utf-8") as f:
        body = f.read()

    out_dir = args.artifact or HERE
    os.makedirs(out_dir, exist_ok=True)
    with open(os.path.join(out_dir, "data.js"), "w", encoding="utf-8") as f:
        f.write(js)
    if args.artifact:
        page, name = FONTS + "\n" + body, "page.html"
    else:
        page = ('<!doctype html>\n<html lang="en">\n<head>\n<meta charset="utf-8">\n'
                '<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">\n'
                + FONTS + '\n</head>\n<body>\n' + body + '\n</body>\n</html>\n')
        name = "index.html"
    with open(os.path.join(out_dir, name), "w", encoding="utf-8") as f:
        f.write(page)
    print(f"wrote {name} and data.js ({len(js) // 1024} KB)")


if __name__ == "__main__":
    main()
