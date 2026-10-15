# LoopVLA lab dashboard (demo)

A mock dashboard for the 4 minute LoopVLA talk. Five clean pages for the talk (Loop, Workflow, Data, Brain, Impact), and a Lab mode with four pages for everyday engineering.

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

## Lab mode

The **Pitch | Lab** switch next to the logo opens four engineering pages in the same style. Keys `6` to `9` open them directly; `1` to `5` go back to the pitch.

| Page | What it shows |
|---|---|
| Live loop | Watch, Record, Label and Train with live counters, a VLA rollout with its motor log, and Claude's verdicts as they arrive |
| Runs | Every demo and VLA rollout: both cameras, a scrubber, the model output vs. what reached the motors vs. what the motors measured, timing and data-quality stats |
| Labels | Claude's 71 verdicts: by start spot, confidence, a table you can filter, sort and review, and the curation rule for the next training set |
| Models | Every model version with deploy and roll back, v2 on Neil vs. the human demos, and the Athena training jobs |

Both modes share one demo counter: the overnight upgrade in Brain and the Train card in Live loop are the same event.

Real in Lab mode: the 5 VLA rollouts of 15 Oct (videos, motor log, run settings), Claude's 71 verdicts with notes and costs, and v2's 3 of 5. In Pitch mode, Data shows Claude's real verdicts on the 50 Batch A demos (Batch B is not judged yet), and Brain's v2 point is measured. Marked as demo values: the Base, v1 and v3 grasp rates, and the Impact estimates.

Rebuild the Lab data from Adam's `dashboard_sample_data` (branch `claude/project-thread-4sp9ds`):

```bash
python tools/build_lab.py --src ../dashboard_sample_data
```

## Rebuild the assets

```bash
../vla/.venv/bin/python tools/build_assets.py
../vla/.venv/bin/python tools/boxes.py
```

`build_assets.py` makes the frames and `assets/data.js`. `boxes.py` finds the cup and Neil in the live frames.
