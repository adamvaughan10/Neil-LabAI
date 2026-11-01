"""Compare a new dataset's state and action ranges with pick_cup_pos2's, and write the stats for the
warm-start run.

    python stats_compare.py data/my_task
    python stats_compare.py data/my_task --rule pos2      (force pos2's mean/std)

A warm start from pos2 (train_v2.sh warm) keeps pos2's weights, but LeRobot normalizes the data with the
new dataset's meta/stats.json. The weights learned pos2's scale: a model output of +1.0 means pos2's mean
plus one pos2 std. So when the new data fits inside pos2's range, the warm run should use pos2's mean and
std, and then every number means what it meant in training.

--rule auto (default): if every state and action value of the new data lies inside pos2's min..max, use
pos2's mean/std; otherwise keep the new data's own mean/std and say which values are outside.

Writes, next to the dataset's stats.json (which is never changed):
    meta/stats_warm.json    the new stats.json with mean/std from the chosen source for observation.state
                            and action, and min/max covering both datasets (run_policy.py clips actions
                            to min/max). train_v2.sh warm uses it as the dataset's stats.json.
    meta/stats_warm_source.json   which mean/std were chosen, and why
    meta/stats_report.txt   the table printed below
"""
import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

KEYS = ["observation.state", "action"]
NAMES = {"observation.state": ["left speed", "right speed", "arm", "gripper"],
         "action": ["left deg to go", "right deg to go", "arm target", "gripper target"]}
GRIP_STATE = (-69, -3)  # pos2's gripper state range: far outside it means a formula or sign is wrong


def ref_stats(ref):
    """pos2's stats: from the model's normalizer, or from a dataset's meta/stats.json."""
    ref = Path(ref)
    norm = ref / "policy_preprocessor_step_5_normalizer_processor.safetensors"
    if norm.exists():
        from safetensors.numpy import load_file
        s = load_file(str(norm))
        return {k: {f: s[f"{k}.{f}"].astype(float) for f in ("min", "max", "mean", "std")} for k in KEYS}
    s = json.load(open(ref / "meta" / "stats.json"))
    return {k: {f: np.array(s[k][f], dtype=float) for f in ("min", "max", "mean", "std")} for k in KEYS}


def frames_outside(ds, key, lo, hi):
    """Per value: how many frames of the new data lie outside lo..hi."""
    x = np.concatenate([np.stack(pd.read_parquet(f, columns=[key])[key].to_numpy())
                        for f in sorted((ds / "data").glob("chunk-*/*.parquet"))])
    return ((x < lo) | (x > hi)).sum(0), len(x)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("dataset", help="the new LeRobot dataset folder (has meta/stats.json)")
    ap.add_argument("--ref", default=str(Path(__file__).parent.parent / "models/handoff_pick_cup_pos2/pretrained_model"),
                    help="pos2's model folder, or pos2's dataset folder")
    ap.add_argument("--rule", choices=["auto", "pos2", "new"], default="auto")
    args = ap.parse_args()

    ds = Path(args.dataset)
    new_json = json.load(open(ds / "meta" / "stats.json"))
    new = {k: {f: np.array(new_json[k][f], dtype=float) for f in ("min", "max", "mean", "std")} for k in KEYS}
    ref = ref_stats(args.ref)

    lines, outside, warnings = [], [], []
    lines.append(f"{'value':28s} {'pos2 min..max':>16s} {'pos2 mean+-std':>16s} | "
                 f"{'new min..max':>16s} {'new mean+-std':>16s}  inside  frames outside")
    for k in KEYS:
        n_out, n = frames_outside(ds, k, ref[k]["min"], ref[k]["max"])
        for i, name in enumerate(NAMES[k]):
            r, s = {f: v[i] for f, v in ref[k].items()}, {f: v[i] for f, v in new[k].items()}
            inside = r["min"] <= s["min"] and s["max"] <= r["max"]
            if not inside:
                outside.append(f"{k}[{i}] {name}")
            lines.append(f"{k.split('.')[-1] + '[' + str(i) + '] ' + name:28s} "
                         f"{r['min']:7.1f}..{r['max']:<7.1f} {r['mean']:7.1f}+-{r['std']:<7.1f} | "
                         f"{s['min']:7.1f}..{s['max']:<7.1f} {s['mean']:7.1f}+-{s['std']:<7.1f}  "
                         f"{'yes' if inside else 'NO':6s}  {n_out[i]} of {n}")
            if s["std"] == 0:
                warnings.append(f"{k}[{i}] {name} never changes (std 0): was it recorded?")
            no_overlap = s["max"] < r["min"] or s["min"] > r["max"]
            if no_overlap and s["mean"] * r["mean"] < 0:
                warnings.append(f"{k}[{i}] {name} lies on the other side of 0 from pos2: a flipped sign?")
    g = new["observation.state"]
    if g["min"][3] < GRIP_STATE[0] - 20 or g["max"][3] > GRIP_STATE[1] + 20:
        warnings.append(f"gripper state {g['min'][3]:.0f}..{g['max'][3]:.0f} is far outside pos2's "
                        f"{GRIP_STATE[0]}..{GRIP_STATE[1]}: check the gripper formula and sign")

    source = args.rule if args.rule != "auto" else ("new" if outside else "pos2")
    lines.append("")
    lines.append(f"Outside pos2's range: {', '.join(outside) if outside else 'nothing'}")
    lines += [f"Warning: {w}" for w in warnings]
    why = {"pos2": "every value fits inside pos2's range" if not outside else "forced with --rule pos2",
           "new": f"outside pos2's range: {', '.join(outside)}" if args.rule == "auto" else "forced with --rule new"}
    lines.append(f"Warm run uses {source}'s mean/std ({why[source]}); min/max cover both datasets.")

    warm = json.loads(json.dumps(new_json))
    for k in KEYS:
        src = ref[k] if source == "pos2" else new[k]
        warm[k]["mean"], warm[k]["std"] = src["mean"].tolist(), src["std"].tolist()
        warm[k]["min"] = np.minimum(ref[k]["min"], new[k]["min"]).tolist()
        warm[k]["max"] = np.maximum(ref[k]["max"], new[k]["max"]).tolist()
    # LeRobot turns every entry of stats.json into a tensor, so the note on the choice goes in its own file
    json.dump(warm, open(ds / "meta" / "stats_warm.json", "w"), indent=4)
    json.dump({"mean_std": source, "min_max": "union of pos2 and this dataset", "ref": str(args.ref),
               "outside": outside}, open(ds / "meta" / "stats_warm_source.json", "w"), indent=4)
    (ds / "meta" / "stats_report.txt").write_text("\n".join(lines) + "\n")
    print("\n".join(lines))
    print(f"\nWrote {ds / 'meta' / 'stats_warm.json'} and stats_report.txt")


if __name__ == "__main__":
    main()
