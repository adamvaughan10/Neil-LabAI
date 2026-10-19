# Neil control panel

A local web page for running the VLA on Neil: both camera feeds, the motor readings, the
model server, a dry-run / drive switch with caps, live model output, and an emergency stop.

```bash
.venv/bin/python gui/app.py
```

Then open http://127.0.0.1:8090. Without Neil, a recording stands in for it (dry run only):

```bash
.venv/bin/python gui/app.py --replay logs/session_20261014_113509
```

## Using it

1. **Connect** reads the Pi camera, the iPhone (`http://132.68.34.85:8080/stream.mjpg`) and the
   motors (read-only). First stop the gamepad, the recorder and `run_policy.py`: only one program
   can hold Neil's motors and Pi camera. **Disconnect** frees them again.
2. **Model**: pick a checkpoint and press **Start server**. It runs `policy_server/server.py` on
   port 8001 with the lerobot Python (`.venv-vla`; set `NEIL_VLA_PYTHON` to use another). Or open
   "use a server that is already running" and give its URL.
3. **Run**: the task (default "pick up the cup"), the observation spec (`specs/pick_cup_kit.json`
   for the inference-kit model), and **Start dry run**. The model's actions and the commands they
   would become are shown and logged; nothing moves.
4. **Drive Neil** runs `inference_kit/pi_bridge.py` on the Pi instead (uploaded to `/tmp`), which
   holds the motors and serves the front camera. It asks for confirmation first.

## Safety

- **EMERGENCY STOP** (or Space / Esc) stops the wheels at once and ends `pi_bridge.py`, which
  releases every motor.
- Each action is capped on the laptop (wheel speed, arm and gripper target ranges, or wheels / arm
  switched off) and again by `pi_bridge.py` (wheels 30, arm -25..10, gripper -80..5).
- The wheels stop when the model has no action ready, when the page is closed or stops polling
  for 1.5 s, when SSH drops, and 0.5 s after `pi_bridge.py`'s last command.

## What a run saves

`logs/gui_run_<date>_<time>/`, like `scripts/run_policy.py`: the images of both cameras,
`steps.jsonl` (motor state, the model's action, and the command it became), `inference.jsonl`
(each request's latency) and `policy.json` (server, spec, task, caps). Also videos to watch:
`pi.mp4`, `external.mp4` and `combined.mp4` (both side by side), at 30 fps while the model runs at
10 (`RUN_VIDEO_FPS`, 0 = none), with `video.json`.
