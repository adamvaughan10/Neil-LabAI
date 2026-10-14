"""
Judge recorded attempts with Claude: success or failure, and why, then count the common failures.

Works on teleop sessions, policy rollouts (logs/run_*) and converted episodes; give it single
attempts or folders to search:

    python scripts/classify_attempts.py logs/                          # every attempt under logs/
    python scripts/classify_attempts.py logs/run_20261014_153000 episodes/target
    python scripts/classify_attempts.py logs/ --task "pick up the cup" --frames 10
    python scripts/classify_attempts.py logs/ --dry-run                # no API calls: contact sheets only

Needs ANTHROPIC_API_KEY in the environment (pip install anthropic). Writes to output/classifier/<date>_<time>/:
    attempts/<attempt>.json   one verdict per attempt: success, confidence, failure_category, reason, ...
    summary.json, summary.md  success rate, failure categories by count, low-confidence attempts
    sheets/<attempt>.jpg      (--dry-run, or --sheets) the exact frames the model is shown
"""
import argparse
import json
import sys
import time
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from neil_robot.attempt_classifier import (  # noqa: E402
    DEFAULT_MODEL, FAILURE_CATEGORIES, classify, find_attempts, load_attempt, sample_indices)

ROOT = Path(__file__).resolve().parent.parent


def attempt_name(path: Path, roots: list[Path]) -> str:
    """A readable, unique file name: the attempt's path below the folder it was found in."""
    for r in roots:
        try:
            rel = path.resolve().relative_to(r.resolve().parent)
            return "__".join(rel.parts).replace(" ", "_")
        except ValueError:
            pass
    return path.name


def contact_sheet(a, n_frames: int, out: Path, w: int = 320):
    """One row per camera, the sampled frames left to right."""
    idx = sample_indices(a.n_steps, n_frames)
    rows = []
    for get in a.frames.values():
        ims = []
        for i in idx:
            img = get(i)
            if img is None:
                img = np.zeros((240, 320, 3), np.uint8)
            img = cv2.resize(img, (w, round(img.shape[0] * w / img.shape[1])))
            cv2.putText(img, f"{i / a.fps:.1f}s", (6, 22), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 255), 2)
            ims.append(img)
        h = max(i.shape[0] for i in ims)
        rows.append(np.hstack([np.pad(i, ((0, h - i.shape[0]), (0, 0), (0, 0))) for i in ims]))
    out.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(out), np.vstack(rows))


def summarize(results: list[dict], low_conf: float) -> dict:
    judged = [r for r in results if "error" not in r]
    succ = [r for r in judged if r["success"]]
    fails = Counter(r["failure_category"] for r in judged if not r["success"])
    groups = defaultdict(lambda: [0, 0])
    for r in judged:
        g = groups[str(Path(r["path"]).parent)]
        g[0] += r["success"]
        g[1] += 1
    labelled = [r for r in judged if r.get("label") is not None]
    return {
        "attempts": len(results),
        "judged": len(judged),
        "errors": [{"path": r["path"], "error": r["error"]} for r in results if "error" in r],
        "successes": len(succ),
        "success_rate": round(len(succ) / len(judged), 3) if judged else None,
        "lifted": sum(r.get("cup_final_state") == "held_lifted" for r in judged),
        "failure_categories": [{"category": c, "count": n, "meaning": FAILURE_CATEGORIES[c]} for c, n in fails.most_common()],
        "mean_confidence": round(sum(r["confidence"] for r in judged) / len(judged), 3) if judged else None,
        "low_confidence": [{"name": r["name"], "success": r["success"], "confidence": r["confidence"], "reason": r["reason"]}
                           for r in sorted(judged, key=lambda r: r["confidence"]) if r["confidence"] < low_conf],
        "by_folder": {k: {"successes": s, "attempts": n} for k, (s, n) in sorted(groups.items())},
        "label_agreement": ({"labelled": len(labelled), "agree": sum(r["success"] == r["label"] for r in labelled)}
                            if labelled else None),
        "tokens": {k: sum(r.get("usage", {}).get(k, 0) for r in judged) for k in ("input_tokens", "output_tokens")},
    }


def summary_md(s: dict, results: list[dict], meta: dict) -> str:
    L = [f"# Attempt classification: {meta['task'] or 'task from each attempt'}", "",
         f"{meta['when']}, {meta['model']} (effort {meta['effort']}), {meta['frames']} frames per camera.", ""]
    if s["judged"]:
        L += [f"**{s['successes']} of {s['judged']} succeeded ({s['success_rate']:.0%}).** "
              f"{s['lifted']} ended with the cup lifted. Mean confidence {s['mean_confidence']:.2f}.", ""]
    if s["errors"]:
        L += [f"{len(s['errors'])} attempts could not be judged (see summary.json).", ""]
    if s["label_agreement"]:
        la = s["label_agreement"]
        L += [f"Agrees with the recorded success label on {la['agree']} of {la['labelled']} labelled episodes.", ""]
    L += ["## Most common failures", ""]
    L += ([f"| Category | Count | Meaning |", "|---|---|---|"]
          + [f"| {f['category']} | {f['count']} | {f['meaning']} |" for f in s["failure_categories"]]
          if s["failure_categories"] else ["No failures."])
    L += ["", "## By folder", "", "| Folder | Succeeded |", "|---|---|"]
    L += [f"| {k} | {v['successes']} / {v['attempts']} |" for k, v in s["by_folder"].items()]
    if s["low_confidence"]:
        L += ["", "## Worth a human look (low confidence)", ""]
        L += [f"- {r['name']}: {'success' if r['success'] else 'failure'} at {r['confidence']:.2f}. {r['reason']}"
              for r in s["low_confidence"]]
    L += ["", "## Every attempt", "", "| Attempt | Result | Category | Conf. | Reason |", "|---|---|---|---|---|"]
    for r in sorted(results, key=lambda r: r["name"]):
        if "error" in r:
            L.append(f"| {r['name']} | error | | | {r['error']} |")
        else:
            L.append(f"| {r['name']} | {'success' if r['success'] else 'FAIL'} | {r['failure_category']} | "
                     f"{r['confidence']:.2f} | {r['reason'].replace('|', '/')} |")
    return "\n".join(L) + "\n"


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("paths", nargs="+", type=Path, help="attempt folders, or folders to search for them")
    ap.add_argument("--task", help='task the attempts were for (default: from policy.json/episode.json, else "pick up the cup")')
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--effort", default="medium", choices=["low", "medium", "high", "xhigh", "max"])
    ap.add_argument("--frames", type=int, default=8, help="frames sampled per camera, first to last (default 8)")
    ap.add_argument("--width", type=int, default=640, help="frames are shrunk to this width before sending")
    ap.add_argument("--workers", type=int, default=4, help="attempts judged in parallel")
    ap.add_argument("--low-confidence", type=float, default=0.7, help="flag verdicts below this confidence")
    ap.add_argument("--out", type=Path, help="output folder (default output/classifier/<date>_<time>)")
    ap.add_argument("--sheets", action="store_true", help="also save a contact sheet of the frames sent")
    ap.add_argument("--dry-run", action="store_true", help="find attempts and save contact sheets; no API calls")
    args = ap.parse_args()

    dirs = []
    for p in args.paths:
        found = find_attempts(p)
        if not found:
            print(f"warning: no attempts found under {p}", file=sys.stderr)
        dirs += [d for d in found if d not in dirs]
    if not dirs:
        sys.exit("No attempts found.")
    out = args.out or ROOT / "output" / "classifier" / time.strftime("%Y%m%d_%H%M%S")
    print(f"{len(dirs)} attempts -> {out}")

    client = None
    if not args.dry_run:
        import anthropic
        client = anthropic.Anthropic()

    def run(d: Path) -> dict:
        name = attempt_name(d, args.paths)
        r = {"name": name, "path": str(d)}
        try:
            a = load_attempt(d, args.task)
            r.update(kind=a.kind, task=a.task, duration_s=round(a.duration_s, 1), label=a.label)
            if args.dry_run or args.sheets:
                contact_sheet(a, args.frames, out / "sheets" / f"{name}.jpg")
            if not args.dry_run:
                r.update(classify(client, a, args.model, args.effort, args.frames, args.width))
        except Exception as e:  # one bad attempt should not stop the batch
            r["error"] = f"{type(e).__name__}: {e}"
        (out / "attempts").mkdir(parents=True, exist_ok=True)
        (out / "attempts" / f"{name}.json").write_text(json.dumps(r, indent=2))
        return r

    results = []
    with ThreadPoolExecutor(max_workers=max(1, args.workers)) as pool:
        for fut in as_completed([pool.submit(run, d) for d in dirs]):
            r = fut.result()
            results.append(r)
            if "error" in r:
                status = f"ERROR {r['error']}"
            elif args.dry_run:
                status = f"{r['kind']}, {r['duration_s']} s"
            else:
                status = (f"{'success' if r['success'] else 'FAIL ' + r['failure_category']} "
                          f"({r['confidence']:.2f}) {r['reason']}")
            print(f"[{len(results):3d}/{len(dirs)}] {r['name']}: {status}", flush=True)

    if args.dry_run:
        print(f"Dry run: contact sheets in {out / 'sheets'}")
        return
    meta = {"when": time.strftime("%Y-%m-%d %H:%M"), "model": args.model, "effort": args.effort,
            "frames": args.frames, "task": args.task}
    s = summarize(results, args.low_confidence)
    (out / "summary.json").write_text(json.dumps({**meta, **s}, indent=2))
    (out / "summary.md").write_text(summary_md(s, results, meta))
    print()
    if s["judged"]:
        print(f"{s['successes']}/{s['judged']} succeeded ({s['success_rate']:.0%}). Most common failures: "
              + (", ".join(f"{f['category']} x{f['count']}" for f in s["failure_categories"][:5]) or "none"))
    print(f"Report: {out / 'summary.md'}")


if __name__ == "__main__":
    main()
