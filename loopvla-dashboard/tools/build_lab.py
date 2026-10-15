"""Build the Lab pages' data: VLA rollouts, Claude's verdicts and their summary.

    python tools/build_lab.py --src ../dashboard_sample_data

--src is Adam's dashboard_sample_data folder (branch claude/project-thread-4sp9ds).
Writes assets/lab.js and copies the rollout videos to assets/lab/<run>/{front,top}.mp4.
"""
import argparse
import glob
import json
import os
import re
import shutil

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "..", "assets")


def load(src, path):
    with open(os.path.join(src, path), encoding="utf-8") as f:
        return json.load(f)


def labels(src):
    out = []
    for f in sorted(glob.glob(os.path.join(src, "classifier_labels", "attempts", "*.json"))):
        with open(f, encoding="utf-8") as fh:
            a = json.load(fh)
        m = re.search(r"__([a-z]+)_position__session_(\d{8}_\d{6})", a["name"])
        s = re.search(r"session_(\d{8}_\d{6})", a["name"])
        out.append({
            "name": a["name"],
            "demo": s.group(1) if s else None,          # matches episodes[].id in data.js
            "spot": ["first", "second", "third", "fourth", "fifth"].index(m.group(1)) + 1 if m else 0,
            "group": "Spot sessions" if m else ("Early sessions" if "previous" in a["name"] else "Demo episodes"),
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


def rollouts(src):
    out = []
    for r in load(src, "vla_rollouts/index.json"):
        item = {"id": r["id"], "model": r["model"], "outcome": r["outcome"], "note": r["note"], "steps": r["steps"]}
        if r["steps"]:
            with open(os.path.join(src, r["path"], "steps.jsonl"), encoding="utf-8") as f:
                steps = [json.loads(line) for line in f]
            t0 = steps[0]["t"]
            item.update({
                "duration_s": r["duration_s"],
                "final_state": r["final_state"],
                "config": load(src, os.path.join(r["path"], "run.json")),
                # t, action[4] (model), sent[4] (to motors), state[4] (measured), new_plan, wheel_deg[2]
                "full": [[round(s["t"] - t0, 3), *[round(v, 2) for v in s["action"]], *s["sent"], *s["state"],
                          1 if s["new_plan"] else 0, *s["wheel_deg"]] for s in steps],
            })
            dst = os.path.join(OUT, "lab", r["id"])
            os.makedirs(dst, exist_ok=True)
            for cam in ("front", "top"):
                shutil.copyfile(os.path.join(src, r["path"], cam + ".mp4"), os.path.join(dst, cam + ".mp4"))
        out.append(item)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", required=True, help="dashboard_sample_data folder")
    src = ap.parse_args().src
    s = load(src, "classifier_labels/summary.json")
    data = {
        "summary": {k: s[k] for k in ("when", "model", "frames", "attempts", "successes", "mean_confidence", "label_agreement")},
        "labels": labels(src),
        "rollouts": rollouts(src),
    }
    with open(os.path.join(OUT, "lab.js"), "w", encoding="utf-8") as f:
        f.write("window.LAB_DATA = " + json.dumps(data, separators=(",", ":")) + ";\n")
    print(f"{len(data['labels'])} verdicts, {sum(1 for r in data['rollouts'] if r['steps'])} rollouts with video")


if __name__ == "__main__":
    main()
