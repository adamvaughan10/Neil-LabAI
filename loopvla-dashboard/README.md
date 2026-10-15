# LoopVLA lab dashboard (demo)

A mock dashboard for the 4 minute LoopVLA talk. Five clean pages: Loop, Workflow, Data, Brain, Impact.

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
> Real: the 97 demos (frames, start spots, motor data) from 2026-10-14, the cup and Neil boxes, and the loss 0.09 (final loss of training run 181719).
> Mock: the success rates of versions 2 to 4, and the hours saved.

## Rebuild the assets

```bash
../vla/.venv/bin/python tools/build_assets.py
../vla/.venv/bin/python tools/boxes.py
```

`build_assets.py` makes the frames and `assets/data.js`. `boxes.py` finds the cup and Neil in the live frames.
