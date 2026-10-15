# LoopVLA lab dashboard

The LoopVLA dashboard for Neil: a scrolling **Overview** for the 4 minute talk, a **Live demo** of the loop, and **Analysis** and **Workflow** tabs for everyday work on real runs, labels, jobs and models.

Watch the 2.5 minute tour first: [`demo/LoopVLA_dashboard_demo.mp4`](demo/LoopVLA_dashboard_demo.mp4) (1080p).

## Run it

Nothing to install. It is plain HTML, CSS and JavaScript, and works offline.

1. Get the branch:
   ```bash
   git fetch origin
   git switch loopvla-dashboard-lab
   ```
2. Open `loopvla-dashboard/index.html` in Google Chrome (double-click it, or drag it into a Chrome window). No server is needed.
3. Go full screen: `F11` on Windows, `Ctrl+Cmd+F` on a Mac.

| To show | Do this |
|---|---|
| The pitch | Stay on **Overview** and press **Play story** (or `Space`). It scrolls through the five sections in about 50 seconds |
| The loop running | Press **Live demo** at the top right |
| Engineering detail | **Analysis** (Runs, Labels, Batch analysis) and **Workflow** (Jobs, Models) |

> [!TIP]
> Start the story without a click: open `index.html?story=1`. Open a tab directly with a link such as `index.html#runs`, `#analysis` or `#jobs`.

If Chrome blocks the videos when opened from a file (some company setups do), serve the folder instead and open http://127.0.0.1:8000:

```bash
cd loopvla-dashboard
python -m http.server 8000
```

## Controls

| Key or action | Result |
|---|---|
| `Space` or **Play story** | Plays the full story in about 50 seconds |
| `1` to `5` | Scroll Overview to Loop, Workflow, Data, Brain or Impact |
| Workflow switch | Flips between Today and With LoopVLA |
| Mouse over a demo card | Replays that demo |
| Click a demo card | Opens the demo with both cameras |
| `Esc` | Closes the demo or stops the story |

## What is real and what is mock

> [!IMPORTANT]
> Real: the 97 demos (frames, start spots, motor data) from 2026-10-14, the cup and Neil boxes, the loss 0.09 (final loss of training run 181719), Claude's verdicts and notes on the 50 Batch A demos, the $0.06 labeling cost per demo, and v2's 60% (3 of 5 VLA rollouts on 2026-10-15).
> Mock: the Base, v1 and v3 success rates, and the hours saved.

## Tabs

| Tab | What it is for |
|---|---|
| Overview | The talk: the five pitch sections (Loop, Workflow, Data, Brain, Impact) on one page that scrolls. **Play story** scrolls through them; keys `1` to `5` jump to a section |
| Live demo (button at the top right) | A live demonstration of the loop: Watch, Record, Label and Train with live counters, a VLA rollout with its motor log, and Claude's verdicts as they arrive |
| Analysis › Runs | One run at a time: both cameras, model output vs. what reached the motors vs. what they measured, control timing, and links to the original files and logs. Covers the 97 demos, the 5 VLA rollouts and the 9 pipeline tests |
| Analysis › Labels | Claude's 71 verdicts: by start spot, confidence, review table, and the curation rule for the next training set |
| Analysis › Batch analysis | Two groups of runs side by side: success, timing medians, time to close the gripper, every run's motor curves (optionally aligned at the gripper close), per-run table with CSV, and policy server speed |
| Workflow › Jobs | Queue recording, labeling, training, evaluation and dry-run jobs as the exact commands for this repo and Athena; suggestions from the data; history of jobs that already ran. The queue is saved in the browser |
| Workflow › Models | Model versions with deploy and roll back, and v2 on Neil vs. the human demos |

The demo counter and the overnight upgrade are shared between Overview and the Live demo.

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
