# LoopVLA lab dashboard (demo)

A mock dashboard for the 4 minute LoopVLA talk. Five clean pages for the talk (Loop, Workflow, Data, Brain, Impact), and six engineering tabs for everyday work.

## Open it

1. Open `index.html` in Google Chrome. No server is needed.
2. Use full screen (`Ctrl+Cmd+F`).

> [!TIP]
> Start the story without a click: open `index.html?story=1`.

## Controls

| Key or action | Result |
|---|---|
| `Space` or **Play story** | Plays the full story in about 50 seconds |
| `1` to `5` | Loop, Workflow, Data, Brain, Impact |
| Workflow switch | Flips between Today and With LoopVLA |
| Mouse over a demo card | Replays that demo |
| Click a demo card | Opens the demo with both cameras |
| `Esc` | Closes the demo or stops the story |

## What is real and what is mock

> [!IMPORTANT]
> Real: the 97 demos (frames, start spots, motor data) from 2026-10-14, the cup and Neil boxes, the loss 0.09 (final loss of training run 181719), Claude's verdicts and notes on the 50 Batch A demos, the $0.06 labeling cost per demo, and v2's 60% (3 of 5 VLA rollouts on 2026-10-15).
> Mock: the Base, v1 and v3 success rates, and the hours saved.

## Tabs

One tab bar. **Overview** is the talk: the five pitch pages (Loop, Workflow, Data, Brain, Impact) under it, keys `1` to `5`, and **Play story**. The other tabs are for everyday engineering work:

| Tab | What it is for |
|---|---|
| Live | Watch, Record, Label and Train with live counters, a VLA rollout with its motor log, Claude's verdicts as they arrive |
| Runs | One run at a time: both cameras, model output vs. what reached the motors vs. what they measured, control timing, and links to the original files and logs. Covers the 97 demos, the 5 VLA rollouts and the 9 pipeline tests (inference latency per chunk) |
| Analysis | Two groups of runs side by side: success, timing medians, time to close the gripper, every run's motor curves (optionally aligned at the gripper close), per-run table with CSV, and policy server speed |
| Labels | Claude's 71 verdicts: by start spot, confidence, review table, and the curation rule for the next training set |
| Jobs | Queue recording, labeling, training, evaluation and dry-run jobs as the exact commands for this repo and Athena; suggestions from the data; history of jobs that already ran. The queue is saved in the browser |
| Models | Model versions with deploy and roll back, and v2 on Neil vs. the human demos |

The demo counter and the overnight upgrade are shared between Overview and Live.

Real: the 5 VLA rollouts of 15 Oct (videos, motor log, run settings), Claude's 71 verdicts with notes and costs, v2's 3 of 5, and the 9 pipeline tests of 14 Oct (inference.jsonl). In Overview, Data shows Claude's real verdicts on the 50 Batch A demos (Batch B is not judged yet) and Brain's v2 point is measured. Marked as demo values: the Base, v1 and v3 grasp rates, and the Impact estimates.

Rebuild the engineering data from Adam's `dashboard_sample_data` (branch `claude/project-thread-4sp9ds`) and a `logs/` folder with pipeline tests:

```bash
python tools/build_lab.py --src ../dashboard_sample_data --logs ../logs
```

## Rebuild the assets

```bash
../vla/.venv/bin/python tools/build_assets.py
../vla/.venv/bin/python tools/boxes.py
```

`build_assets.py` makes the frames and `assets/data.js`. `boxes.py` finds the cup and Neil in the live frames.
