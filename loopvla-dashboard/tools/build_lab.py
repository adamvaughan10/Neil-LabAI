"""Build the data for the engineering tabs: VLA rollouts, Claude's verdicts, pipeline tests.

    python tools/build_lab.py --src ../dashboard_sample_data --logs ../logs

--src  Adam's dashboard_sample_data folder (branch claude/project-thread-4sp9ds).
--logs a Neil-LabAI logs/ folder with run_* pipeline tests (policy.json, inference.jsonl, info.json).
Writes assets/lab.js and copies each run's original files to assets/lab/ so the dashboard can link them:
rollouts to lab/<run>/ (front.mp4, top.mp4, steps.jsonl, run.json), verdicts to lab/labels/<attempt>.json,
pipeline tests to lab/tests/<run>/ (policy.json, inference.jsonl, info.json).
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
        os.makedirs(os.path.join(OUT, "lab", "labels"), exist_ok=True)
        shutil.copyfile(f, os.path.join(OUT, "lab", "labels", a["name"] + ".json"))
        out.append({
            "name": a["name"],
            "source": a.get("path"),
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
            for name in ("front.mp4", "top.mp4", "steps.jsonl", "run.json"):
                shutil.copyfile(os.path.join(src, r["path"], name), os.path.join(dst, name))
        out.append(item)
    return out


def tests(logs):
    """Pipeline tests: the policy server answering on recorded sessions (dry run, the robot does not move)."""
    out = []
    for d in sorted(glob.glob(os.path.join(logs, "run_*"))):
        rid = os.path.basename(d)
        if not os.path.exists(os.path.join(d, "policy.json")):
            continue
        with open(os.path.join(d, "policy.json"), encoding="utf-8") as f:
            pol = json.load(f)
        info = {}
        if os.path.exists(os.path.join(d, "info.json")):
            with open(os.path.join(d, "info.json"), encoding="utf-8") as f:
                info = json.load(f)
        chunks = []
        if os.path.exists(os.path.join(d, "inference.jsonl")):
            with open(os.path.join(d, "inference.jsonl"), encoding="utf-8") as f:
                for line in f:
                    c = json.loads(line)
                    sm = c.get("server_ms") or {}
                    chunks.append({"round_trip_ms": c.get("round_trip_ms"), "infer_ms": sm.get("infer"), "decode_ms": sm.get("decode"),
                                   "obs_step": c.get("obs_step"), "reply_step": c.get("reply_step"), "chunk_size": c.get("chunk_size"),
                                   "obs_age_ms": c.get("obs_age_ms")})
        si = pol.get("server_info") or {}
        out.append({
            "id": rid, "mode": pol.get("mode"), "dry_run": pol.get("dry_run"), "task": pol.get("task"), "replay": pol.get("replay"),
            "checkpoint": si.get("checkpoint") or ("dummy server" if chunks else None), "device": si.get("device"),
            "steps": info.get("steps", 0), "duration_s": info.get("duration_s"), "fps": info.get("fps"), "late_ticks": info.get("late_ticks"),
            "cam_age_ms": {k: (v.get("age_ms") or {}).get("median") for k, v in (info.get("cameras") or {}).items()},
            "chunks": chunks,
        })
        dst = os.path.join(OUT, "lab", "tests", rid)
        os.makedirs(dst, exist_ok=True)
        for name in ("policy.json", "inference.jsonl", "info.json"):
            if os.path.exists(os.path.join(d, name)):
                shutil.copyfile(os.path.join(d, name), os.path.join(dst, name))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", required=True, help="dashboard_sample_data folder")
    ap.add_argument("--logs", help="Neil-LabAI logs/ folder with run_* pipeline tests")
    args = ap.parse_args()
    src = args.src
    s = load(src, "classifier_labels/summary.json")
    data = {
        "summary": {k: s[k] for k in ("when", "model", "frames", "attempts", "successes", "mean_confidence", "label_agreement")},
        "labels": labels(src),
        "rollouts": rollouts(src),
        "tests": tests(args.logs) if args.logs else [],
    }
    with open(os.path.join(OUT, "lab.js"), "w", encoding="utf-8") as f:
        f.write("window.LAB_DATA = " + json.dumps(data, separators=(",", ":")) + ";\n")
    print(f"{len(data['labels'])} verdicts, {sum(1 for r in data['rollouts'] if r['steps'])} rollouts with video, {len(data['tests'])} pipeline tests")


if __name__ == "__main__":
    main()
