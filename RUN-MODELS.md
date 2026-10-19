# Run the Pick-Cup Models on Neil

This guide runs one of the three trained SmolVLA models on Neil, from the browser control panel
(`gui/`) or from the command line (`inference_kit/run_policy.py`). The model weights are not in
git: step 2 says where to put them.

> [!IMPORTANT]
> Stay next to Neil while a model drives it. In the panel, **EMERGENCY STOP** (or Space / Esc)
> stops it; on the command line, press Ctrl+C.

## 1. The three models

| Model | Weights folder | `--action-mode` | Spec (panel) | What it outputs |
|---|---|---|---|---|
| v1, job 181436 (50 episodes) | `inference_kit/model/` | `v1` | `specs/pick_cup_kit.json` | Wheel speeds, arm and gripper target angles |
| pos2, job 181719 (47 episodes) | `models/handoff_pick_cup_pos2/pretrained_model/` | `delta` | `specs/pick_cup_pos2.json` | Wheel degrees still to turn, arm and gripper targets |
| angle, job 182076 | `models/pick_cup_angle_182076/pretrained_model/` | `angle` | `specs/pick_cup_angle.json` | Wheel target angles, arm and gripper targets |

Each model only works with its own action mode and spec, because each was trained on differently
scaled motor values. In the panel, picking a model picks its spec for you. On the command line,
pass the matching `--action-mode` yourself.

## 2. Setup (once)

1. Two Python environments in the repo root, both Python 3.12:
   ```bash
   uv venv .venv --python 3.12
   ```
   ```bash
   uv pip install --python .venv -r requirements.txt
   ```
   ```bash
   uv venv .venv-vla --python 3.12
   ```
   ```bash
   uv pip install --python .venv-vla -r policy_server/requirements.txt
   ```
   `.venv` runs the panel; `.venv-vla` has LeRobot 0.6.1 (the training version) and runs the model.
   The panel finds `.venv-vla` by itself; set `NEIL_VLA_PYTHON` to use another Python.
2. Put the weights in the folders from the table. Each folder holds 7 files (about 900 MB),
   including `model.safetensors` and `config.json`. They are on Athena (Technion network, an
   account in `belinkov_prj`); put your username in place of `your.name`:
   ```bash
   O=/rg/belinkov_prj/qiu.qiqian/vla/outputs
   ```
   ```bash
   rsync -avP your.name@athena.technion.ac.il:$O/neil_181436/checkpoints/last/pretrained_model/ inference_kit/model/
   ```
   ```bash
   rsync -avP your.name@athena.technion.ac.il:$O/neil_181719/checkpoints/last/pretrained_model/ models/handoff_pick_cup_pos2/pretrained_model/
   ```
   ```bash
   rsync -avP your.name@athena.technion.ac.il:$O/neil_182076/checkpoints/last/pretrained_model/ models/pick_cup_angle_182076/pretrained_model/
   ```
   `models/`, `*.safetensors` and `inference_kit/model/` are in `.gitignore`, so the weights never
   get committed.
3. SSH to the Pi without a password. The panel uses `~/.ssh/id_ed25519_labpi` when it exists
   (or `RPI_SSH_KEY`). Check it:
   ```bash
   ssh -i ~/.ssh/id_ed25519_labpi rpi@132.68.34.107 echo ok
   ```

## 3. Before every session: Pi and cameras

- **One program on the Build HAT.** Only one program can hold Neil's motors and Pi camera at a
  time. Stop the gamepad, the recorder, Neil's MCP server and any other `run_policy.py` first. In
  the panel, press **Disconnect** before you start something else.
- **iPhone camera.** The top camera is the SimpleIPCamera app on the iPhone, streaming MJPEG over
  plain `http` on port 8080. Keep the app open and in front, with the screen on: the stream stops
  when the app goes to the background or the phone locks.
- **The iPhone address changes.** Read the address the app shows, and set it before you start:
  ```bash
  export EXTERNAL_CAMERA_URL=http://132.68.34.44:8080/stream.mjpg
  ```
  ```bash
  export NEIL_TOP_URL=$EXTERNAL_CAMERA_URL
  ```
  The panel reads `EXTERNAL_CAMERA_URL`, the command line reads `NEIL_TOP_URL`. Without them, both
  fall back to `132.68.34.44`, the last address used.
- **The Pi address** is `132.68.34.107`. If it changed, set `RPI_HOST` (panel) or `NEIL_PI` and
  `NEIL_FRONT_URL` (command line, below).
- **The scene** must look like the recordings: same table, light, iPhone position overhead, a paper
  cup at a recorded position, Neil in its start pose (arm low, gripper open).

## 4. Run from the control panel

```bash
.venv/bin/python gui/app.py
```

Then open http://127.0.0.1:8090.

1. **Connect** reads both cameras and the motors (read-only).
2. **Model**: pick one of the three models and press **Start server**. It loads the model in
   `policy_server/server.py` on port 8001, and selects the model's spec.
3. **Run**: keep the task "pick up the cup" and press **Start dry run**. The page shows what the
   model would do; nothing moves. Check that the commands look sensible.
4. **Drive Neil** uploads `inference_kit/pi_bridge.py` to the Pi and lets the model move Neil,
   within the caps set on the page and in `pi_bridge.py` (wheels 30, arm -25..10, gripper -80..5).

Without Neil, a recorded session stands in for it (dry run only):

```bash
.venv/bin/python gui/app.py --replay logs/session_20261014_113509
```

Each run is saved in `logs/gui_run_<date>_<time>/`, with a video to watch, `combined.mp4` (both
cameras, 30 frames a second). More detail: [gui/README.md](gui/README.md).

## 5. Run from the command line

This uses `.venv-vla`, and runs from `inference_kit/`.

1. Copy the motor program to the Pi, again after every change to it:
   ```bash
   scp -i ~/.ssh/id_ed25519_labpi inference_kit/pi_bridge.py rpi@132.68.34.107:~/
   ```
2. Tell the laptop where Neil is:
   ```bash
   export NEIL_PI=rpi@132.68.34.107 NEIL_FRONT_URL=http://132.68.34.107:8765/ NEIL_SSH_KEY=~/.ssh/id_ed25519_labpi
   ```
3. Optional: save one frame from each camera and print the start state, without moving Neil.
   Compare `preview_front.jpg` and `preview_top.jpg` with training frames.
   ```bash
   cd inference_kit && ../.venv-vla/bin/python preview.py
   ```
4. Run one model (from `inference_kit/`):
   ```bash
   ../.venv-vla/bin/python run_policy.py --model model --action-mode v1 --seconds 30
   ```
   ```bash
   ../.venv-vla/bin/python run_policy.py --model ../models/handoff_pick_cup_pos2/pretrained_model --action-mode delta --seconds 30
   ```
   ```bash
   ../.venv-vla/bin/python run_policy.py --model ../models/pick_cup_angle_182076/pretrained_model --action-mode angle --seconds 30
   ```

`run_policy.py` first moves the arm and gripper to the model's start pose, then runs at 10 steps a
second and plans again every `--replan` actions (default 10, every second). Useful options:
`--replay runs/run_<date>_<time>` dry-runs a saved run without Neil; `--no-record` does not save
the run in `runs/`; `--deadband` (delta and angle) ignores wheel moves under that many degrees.
`--help` lists the rest.

Each run is saved in `inference_kit/runs/run_<date>_<time>/`, with videos to watch:
`side_by_side.mp4` (both cameras), `front.mp4` and `top.mp4`. They have 30 frames a second while
the model runs at 10 (`--video-fps`; 0 = no video).

## 6. If something looks wrong

- **Wrong direction** (a wheel drives backwards, the gripper closes when it should open): stop, and
  check the motor signs at the top of `inference_kit/pi_bridge.py` and in `neil_robot/config.py`.
- **"Port in use" or the motors don't answer**: another program holds the Build HAT. Stop it, or
  press Disconnect in the panel.
- **No top camera**: the iPhone app was closed or its address changed. Reopen it and set
  `EXTERNAL_CAMERA_URL` / `NEIL_TOP_URL` again.
- **Model fails to load**: use the `.venv-vla` Python (LeRobot 0.6.1), and check that the weights
  folder has all 7 files.
