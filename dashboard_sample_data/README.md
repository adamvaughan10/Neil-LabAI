# Dashboard sample data

Real data from Neil (the Lego Build HAT robot) for mocking up a dashboard. Task in every file: **"pick up the cup"**. About 26 MB, no model weights.

```
dashboard_sample_data/
  training_episodes/   5 teleoperated demos the VLA was trained on (2026-10-14)
  vla_rollouts/        7 runs of the trained VLA on the robot (2026-10-15 morning)
  classifier_labels/   71 attempts judged success/fail by a vision-language model (2026-10-14)
```

Each folder has an `index.json` (or `summary.json`) listing its items, so a dashboard can load that one file first.

## The robot's 4 numbers

Every state and action is the same 4 values, always in this order:

| # | Name | Meaning |
|---|---|---|
| 0 | `left` | left wheel speed, -100..100 (+ forward) |
| 1 | `right` | right wheel speed, -100..100 (+ forward) |
| 2 | `arm` | arm angle in degrees (+ down). About -24 is raised, about 0 to +10 is lowered |
| 3 | `grip` | gripper angle in degrees (+ open). About +33 is open, about -55 to -60 is closed on the cup |

Two cameras: **front** (Pi camera on the robot, 640x480) and **top** (iPhone looking down at the table, 640x360).

## training_episodes/

One folder per demo, plus `index.json`.

| File | What it is |
|---|---|
| `episode.json` | Summary: task, `success`, frame count, `fps` (10), date, and a `units` block describing every field |
| `frames.jsonl` | One JSON line per frame (10 per second): `i` frame index, `t` unix time, `state` (what the motors read), `action` / `target` (what the operator commanded), `hat` (raw motor calls), `buttons` (gamepad) |
| `front.mp4`, `top.mp4` | The two camera views, one video frame per line in `frames.jsonl` |
| `side_by_side.mp4` | Both views in one video, handy for a preview tile |

All 5 demos are successful pickups, each from a different starting spot.

## vla_rollouts/

One folder per run of the trained model (`handoff_pick_cup_pos2`, delta actions), plus `index.json`.

| File | What it is |
|---|---|
| `run.json` | Run settings: model, `action_mode`, task, length limit (`seconds`), how often it re-plans (`replan`) |
| `steps.jsonl` | One JSON line per control step (about 5 per second): `state` (motors, 4 numbers above), `action` (what the model predicted), `sent` (what was actually sent to the motors), `new_plan` (true when the model produced a fresh chunk of actions), `wheel_deg` (cumulative wheel encoder degrees) |
| `front.mp4`, `top.mp4` | The two camera views, one video frame per line in `steps.jsonl` |

Outcomes (in `index.json` as `success`, `outcome`, `note`):

| Run | Outcome | What happened |
|---|---|---|
| 094722 | aborted | stopped before the first step, no data |
| 094836 | aborted | stopped before the first step, no data |
| 094929 | grasped | drove to the cup and closed the gripper on it |
| 095041 | grasped | drove to the cup and closed the gripper on it |
| 095736 | missed | drove past the cup and off the table area |
| 095842 | missed | drove past the cup to the table edge, stopped early |
| 095947 | grasped | drove to the cup and closed the gripper on it |

These outcomes were **judged from the final camera frames and gripper reading**, not recorded at the time, so treat them as provisional.

## classifier_labels/

A vision-language model (Claude) watched 8 frames per camera from each of 71 earlier attempts (demos and logged sessions) and judged whether the cup was picked up.

| File | What it is |
|---|---|
| `summary.json` | Totals: `attempts`, `successes`, `success_rate`, failure categories with counts, per-folder breakdown |
| `summary.md` | The same as a readable table, with one line of reasoning per attempt |
| `attempts/*.json` | One file per attempt: `success`, `confidence` (0..1), `failure_category`, `reason` (plain-English explanation), `cup_final_state`, `key_frame_s` (the moment that decided it), and `label` (the human label, when there was one) |

Headline: 53 of 71 attempts succeeded (75%); every failure was `did_not_reach_cup`.
