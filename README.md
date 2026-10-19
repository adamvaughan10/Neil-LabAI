# Neil-LabAI

LEGO robot driven from a laptop: a Raspberry Pi 4 with a Build HAT and a Pi Camera v1 (OV5647).
The approach follows [f1ren/lego-robot-mcp](https://github.com/f1ren/lego-robot-mcp): the laptop keeps one
SSH connection to the Pi and runs short Python scripts there with the Pi's own `buildhat` and `picamera2`,
so nothing has to be deployed to the Pi.

## From setup to a running model

1. **Set up** the Pi and the laptop, and tell the code where the Pi and the phone camera are:
   [Setup](#setup).
2. **Record demos** by driving the robot with the gamepad: [Recording demos](#recording-demos).
3. **Make a LeRobot dataset** from the recordings: [Making the dataset](#making-the-dataset).
4. **Fine-tune SmolVLA** on Athena (needs an Athena account): [`training/README.md`](training/README.md)
   and [`ATHENA-QUICK.md`](ATHENA-QUICK.md).
5. **Run the model** on the robot, from the command line (`inference_kit/run_policy.py`) or the browser
   panel (`gui/`), with a dry run first: [`RUN-MODELS.md`](RUN-MODELS.md). Put your model in
   `models/<name>/pretrained_model/` and run it like `pick_cup_pos2`: `--action-mode delta` on the
   command line, or the spec `specs/pick_cup_pos2.json` in the panel.

> [!NOTE]
> `gamepad_drive.py` turns the wheels in degree steps, and the dataset's action is the degrees each wheel
> still has to turn. That is the format of `pick_cup_pos2` (job 181719), the run `training/README.md`
> reproduces, which is why your model runs like it. The first model, `pick_cup` (job 181436), was recorded
> with wheel speeds, a mode the controller no longer has, and runs with `--action-mode v1`.

## Hardware

| Build HAT port | Default role  | Env var to change it |
|----------------|---------------|----------------------|
| A              | left wheel    | `PORT_LEFT_WHEEL`    |
| B              | right wheel   | `PORT_RIGHT_WHEEL`   |
| C              | gripper       | `PORT_GRIPPER`       |
| D              | arm           | `PORT_ARM`           |

Motors need the Build HAT's 8 V barrel-jack supply.

Also needed:
- **A phone** above the table as the second camera, running an IP-camera app that serves MJPEG
  ([External camera](#external-camera)).
- **A USB gamepad** on the laptop, with a D-pad and four face buttons. The code looks for the team's pad
  (USB ID `0810:E501`). For another pad, change `VENDOR_ID` / `PRODUCT_ID` in `gamepad.py`, and check its
  button and axis numbers with `python gamepad.py` against the ones at the top of `scripts/gamepad_drive.py`.

## Setup

### Pi (once)

1. Put the Pi, the phone and the laptop on the same Wi-Fi. On the Pi: `sudo raspi-config` →
   System Options → Wireless LAN.
2. Install your laptop's SSH key on the Pi (asks for the Pi password once; no key yet: `ssh-keygen -t ed25519`).
   macOS / Linux:
   ```bash
   ssh-copy-id rpi@<pi address>
   ```
   Windows (PowerShell):
   ```powershell
   Get-Content $env:USERPROFILE\.ssh\id_ed25519.pub | ssh rpi@<pi address> "mkdir -p ~/.ssh && chmod 700 ~/.ssh && cat >> ~/.ssh/authorized_keys && chmod 600 ~/.ssh/authorized_keys"
   ```
   Then this must print `ok` without asking for a password:
   ```bash
   ssh -o BatchMode=yes rpi@<pi address> echo ok
   ```
3. Serial port for the Build HAT: `sudo raspi-config` → Interface Options → Serial Port →
   login shell **No**, serial hardware **Yes**, reboot.
4. Libraries: `sudo apt install python3-build-hat python3-picamera2`

`scripts/check_pi.py` verifies all of this.

### Laptop

Two Python 3.12 environments in the repo folder, made with [uv](https://docs.astral.sh/uv/):
`.venv` drives and records the robot, and `.venv-vla` has LeRobot 0.6.1 (the training version) for
converting recordings and running models. [`RUN-MODELS.md`](RUN-MODELS.md) and the panel use the same two.
No uv yet: `curl -LsSf https://astral.sh/uv/install.sh | sh` (macOS / Linux), or on Windows
`powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"`.

```bash
uv venv .venv --python 3.12
uv pip install --python .venv -r requirements.txt
uv venv .venv-vla --python 3.12
uv pip install --python .venv-vla -r policy_server/requirements.txt
```

### Addresses

Most defaults are addresses in the lab the team used before (`132.68.34.x`). In another lab, set these in
every new terminal:

| What | Default | Env var | Used by |
|------|---------|---------|---------|
| Pi | `132.68.34.107`, user `rpi` | `RPI_HOST`, `RPI_USER` | `scripts/`, `gui/` |
| Phone camera | `http://132.68.34.85:8080/stream.mjpg` | `EXTERNAL_CAMERA_URL` | `scripts/`, `gui/` |
| Pi | `rpi@rpi.local` | `NEIL_PI` | `inference_kit/` |
| Pi camera | `http://rpi.local:8765/` (the Pi's address, port 8765) | `NEIL_FRONT_URL` | `inference_kit/` |
| Phone camera | `http://132.68.34.44:8080/stream.mjpg` | `NEIL_TOP_URL` | `inference_kit/` |

All five from the Pi's and the phone's address. macOS / Linux:

```bash
export RPI_HOST=<pi address> EXTERNAL_CAMERA_URL=http://<phone address>:8080/stream.mjpg
export NEIL_PI=rpi@$RPI_HOST NEIL_FRONT_URL=http://$RPI_HOST:8765/ NEIL_TOP_URL=$EXTERNAL_CAMERA_URL
```

Windows (PowerShell):

```powershell
$env:RPI_HOST = "<pi address>"; $env:EXTERNAL_CAMERA_URL = "http://<phone address>:8080/stream.mjpg"
$env:NEIL_PI = "rpi@$env:RPI_HOST"; $env:NEIL_FRONT_URL = "http://$($env:RPI_HOST):8765/"; $env:NEIL_TOP_URL = $env:EXTERNAL_CAMERA_URL
```

The phone's URL is the one its camera app shows. On networks that allow it, the Pi also answers to
`rpi.local`; otherwise find its address on the router, or run `hostname -I` on the Pi. If ssh doesn't
find your key by itself, set `RPI_SSH_KEY` (`scripts/`, `gui/`) and `NEIL_SSH_KEY` (`inference_kit/`) to it.

### Every new terminal

```bash
cd Neil-LabAI                # this repo
source .venv/bin/activate    # Windows: .venv\Scripts\activate
```

Then set the addresses, and run any script. Add `--help` to see its options.

## Recording demos

Each demo is one run of `gamepad_drive.py --record`: drive the robot through the task once,
then press Ctrl-C. Each run is saved in its own `logs/session_<date>_<time>/` folder, and each folder
becomes one episode of the dataset.

Before the first demo:
1. `python scripts/check_pi.py` checks the Pi, the Build HAT and the camera (nothing moves).
2. `python gamepad.py` shows the D-pad and buttons as you press them. Quit it with Ctrl-C before the next
   step: only one program can read the pad.
3. Practise without recording: `python scripts/gamepad_drive.py`.

| Control | What it does |
|---------|--------------|
| D-pad up / down | both wheels forward / backward, while held: 200 degrees a second (`--wheel-deg-s`) |
| D-pad left / right | turn on the spot, counter-clockwise / clockwise, while held |
| X | raise the arm 20 degrees above its resting angle (`--arm-raise`) |
| B | lower the arm to its resting angle (`--arm-down-abs`) |
| Y / A | open / close the gripper, 10 degrees per press (`--grip-step`) |
| Ctrl-C (laptop) | stop and save. The motors go limp, so the arm drops. |

The arm's resting angle is the arm motor's absolute angle with the arm down (12, measured on Neil), so it
is the same in every run. If the arm is rebuilt, measure it again: `abs_pos_deg` of `arm` in `steps.jsonl`.

Record one demo:

```bash
python scripts/gamepad_drive.py --record
```

- **10 fps** (the default `--fps`). The dataset keeps the recording's rate, and the models and
  `inference_kit/` run at 10 fps. All episodes of one dataset must have the same rate.
- **Start every demo from the same pose:** arm lowered (B), gripper open. `run_policy.py` later moves the
  arm and gripper to the pose the team's demos started in (`abs_pos_deg` 12 for the arm, about -70 for the
  gripper) before the model starts. Check the first step of a demo's `steps.jsonl` against it.
- **Keep the scene fixed:** the same table, light and phone position in every demo, and later in every
  model run. The team's datasets had about 50 demos, with the cup at 5 positions.
- **Delete the folder of a failed demo,** or leave it out when converting. Pauses at the start and end
  are fine: the converter trims quiet frames, keeping 1 s.

## Making the dataset

`training/convert_episodes.py` turns session folders into one LeRobot dataset. Run it in `.venv-vla`,
from the `training` folder:

```bash
source .venv-vla/bin/activate    # Windows: .venv-vla\Scripts\activate
cd training
python convert_episodes.py --name my_dataset --task "pick up the cup" ../logs/session_*
```

Windows PowerShell doesn't expand `*`: pass `(Get-ChildItem ../logs -Directory -Filter "session_*").FullName`
in place of `../logs/session_*`.

The dataset is written to `training/data/my_dataset` (not committed to git; a folder with that name is
replaced). Give the model the same task sentence later. Then train it on Athena: `training/README.md`,
steps 2 to 6, with your dataset name in place of `pick_cup_pos2`.

Each frame gets:
- `observation.state`: the motors' readings: left and right wheel speed, arm and gripper angle
- `action`: what the controller asked for: the degrees each wheel still has to turn, and the arm and
  gripper target angles
- `observation.images.camera1`: the Pi camera (640x480), and `camera2`: the phone (640x360)

The arm and gripper angles are the motors' absolute angles on a fixed zero, the same in every session.
The converter's docstring has the units and signs. It also converts older recordings with wheel speeds
(`left_wheel.vel` in `steps.jsonl`) into `pick_cup`'s format, but won't mix them with new ones in one
dataset.

## Scripts

| Script | Moves the robot? | What it does |
|--------|------------------|--------------|
| `python scripts/check_pi.py` | no | Checks SSH, OS, serial port, libraries, HAT voltage, what's on each port, and saves a camera still to `output/`. Run this first. |
| `python scripts/record_video.py` | no | Records 5 s from the Pi camera (`--seconds` to change). |
| `python scripts/stream_cameras.py` | no | Live window with both cameras side by side. `r` starts/stops a **synced recording** (15 fps), `s` saves a snapshot, `q` quits. `--record 10` records 10 s without a window; `--fps` changes the rate. |
| `python scripts/sequence_test.py` | **yes** | Forward 0.5 s, backward 0.5 s, then arm up 30° and back down. Prints how far each motor turned. |
| `python scripts/arm_test.py` | **yes** | Lowers the arm 30° and raises it back while recording video. |
| `python scripts/motor_test.py` | **yes** | Turns each port 30° and back, asking before each. |
| `python gamepad.py` | no | Prints the USB gamepad's D-pad and buttons live. |
| `python scripts/gamepad_drive.py` | **yes** | Drives the robot from the gamepad: D-pad drives and rotates while held, turning the wheels in degree steps (200 a second, `--wheel-deg-s`); X/B move the arm and Y/A the gripper a fixed angle per press. The Pi side is `pi/gamepad_server.py`. |
| `python scripts/gamepad_drive.py --record` | **yes** | Same, and records the whole run as a synced recording (below) with the controller's target as `"action"` on every step, at 10 fps (`--fps`). Ctrl-C stops and saves. |
| `python scripts/record_replay.py` | **yes** | Records a session with `gamepad_drive.py --record` (Ctrl-C ends it), then replays it with `replay_session.py` and prints how closely it matched. |
| `python scripts/replay_session.py logs/session_<date>_<time>` | **yes** | Re-sends a recorded session's Build HAT calls at their recorded times (`pi/replay_server.py` times them on the Pi), then compares the motors' measured speed and angle with the recording and saves `report.json` under `<session>/replays/`. `--dry-run` only lists the calls. |
| `python scripts/run_policy.py` | no (dry run) | Runs a VLA policy in real time: every step's images and motor state go to the policy server, action chunks come back and are logged. `--replay <session>` runs it on a recording, without the robot. See below. |

Before running anything that moves: lift the robot so the wheels spin freely (or give it about 30 cm of room)
and keep hands clear of the arm.

### External camera

A phone IP-camera app serving MJPEG at `http://132.68.34.85:8080/stream.mjpg` (plain **http**; https fails).
Keep the app open and in the foreground, with the phone unlocked and on the same Wi-Fi as the Pi:
the stream stops otherwise. Set `EXTERNAL_CAMERA_URL` if its address changes, and
`EXTERNAL_CAMERA_ROTATION` (0/90/180/270, clockwise) if its image comes out sideways.

The Pi camera has no stream of its own: `stream_cameras.py` starts a small MJPEG server on the Pi
(port 8765) for as long as it runs. Recordings from it are 640x480; `record_video.py` gives full 1296x972.

### Synced recording (for VLA data)

`stream_cameras.py` records through `neil_robot/recorder.py`. It ticks at a fixed rate (15 fps by
default, `RECORD_FPS`) on a high-resolution clock (`neil_robot/clock.py`; Windows' `time.time()` only
ticks every 4-16 ms). On each tick it takes the newest frame from each camera and writes it to disk
immediately, so every step has one image per camera:

```
logs/session_<date>_<time>/
  pi/000000.jpg ...  external/000000.jpg ...
  steps.jsonl      one line per step: t, and per camera: file, frame number, capture ts, age_ms, new
  info.json        rate, repeated-frame %, image age and camera skew statistics
  pi.mp4  external.mp4  combined.mp4   made when the recording stops
```

15 fps is the highest rate where both cameras deliver a new frame on nearly every step (the external
camera tops out around 26 fps and stalls now and then on Wi-Fi). `new: false` marks a step whose image
repeats the previous one. Frame timestamps are arrival time minus each camera's delay
(`PI_CAMERA_LATENCY_S`, `EXTERNAL_CAMERA_LATENCY_S`, both 0 until calibrated).

**Motors are recorded too (read-only).** A reader on the Pi streams all four motors ~50 times a
second without driving them, and every step gets a `"motors"` entry:
`left_wheel`, `right_wheel`, `gripper`, `arm`, each with `pos_deg` (encoder position since the HAT
powered up), `abs_pos_deg` (-180..180) and `speed`, plus the reading's `age_ms`. `--no-motors`
records cameras only. Only one program can use the Build HAT at a time: recording with motors
fails with "HAT not found" while anything else (a gamepad driver, a motor test) has it open.

**Recording while driving: `gamepad_drive.py --record`.** Same recording, but the motor readings come
from the gamepad driver itself (`pi/gamepad_server.py`, 50 a second), and every step also gets
`"action"`: the target the controller has set, formatted exactly like `"motors"` (same keys, raw motor
terms, `seq` counts the controller's changes, `age_ms` is how long ago it last changed). Every motor is
angle controlled (the wheels in steps while the D-pad is held, the arm and gripper a move per press), so
the action has `pos_deg` (the target encoder angle) and `speed: null`; `abs_pos_deg` is always null in the
action. `"action"` also has `vector`: the same target as four numbers in robot terms (+ = forward / arm
down / gripper open), named in `names` (`left_wheel.pos`, `right_wheel.pos`, `arm.pos`, `grip.pos`; the
wheel angles wrap to -180..180); `convert_episodes.py` makes the dataset's action from it.
Every step also gets `"hat_commands"`: the Build HAT calls the Pi actually made, after the arm's sag
correction, in the `"motors"` format plus `degrees` and `call`: `degrees` sums every `run_for_degrees`
made since the previous step (0 when none). `"new"` lists each call with its time.
And every step has `"gamepad"`: `vector` = `[dpad_x, dpad_y, X, A, B, Y]` (D-pad -1/0/1, + = right / up;
a button is 1 if pressed at any moment since the previous step).

`scripts/session_to_episode.py` turns sessions into episode folders for a separate SmolVLA pipeline
(`vla-learning/smolvla-pipeline` and its `DATA-CONTRACT.md`, not in this repo), at 10 fps (sessions at
another rate are resampled), with `--action target`, `hat` or `buttons` choosing the action (for
`buttons`, set the pipeline's `ACTION_FIELDS` to `dpad_x, dpad_y, x, a, b, y`). `training/` doesn't use
it: `convert_episodes.py` reads the sessions directly.

### Running a VLA policy in real time

The recorder's 15 Hz tick doubles as the control loop. At every step, `scripts/run_policy.py`
takes the same images and motor readings the recorder saves, turns them into the policy's
observation (`neil_robot/observation.py`), and sends them to the **policy server**
(`policy_server/`, its own env, see its README) over HTTP. The server returns an *action
chunk* (SmolVLA: 50 future actions), which is played out one action per step.

- `--mode sync` (default): play the whole chunk, then ask again; the robot holds while waiting.
- `--mode async --refill-at 10`: ask for the next chunk when 10 actions are left and keep
  going meanwhile, skipping the actions that went stale in flight. Use this when inference is slow.

Each run is also a recording, in `logs/run_<date>_<time>/`: the usual files, plus `"action"`
and `"policy"` in every `steps.jsonl` line, `inference.jsonl` (one line per request: latency,
skipped actions) and `policy.json` (server, spec and settings).

**A run's videos** (`pi.mp4`, `external.mp4`, `combined.mp4`) are at 30 fps (`RUN_VIDEO_FPS`,
`--video-fps`), not one frame per step (15 fps, or the `pick_cup` data's 10 with `--fps 10`), which
is too choppy to watch. `video.json` says how many frames each camera repeated. They're H.264 if
the OpenCV build has it, else MPEG-4. The policy's inputs are still the per-step images.
`inference_kit/run_policy.py` does the same, into `inference_kit/runs/run_<date>_<time>/`.
Recordings for training ([Recording demos](#recording-demos)) keep one video frame per step.

**Dry run only:** `run_policy.py` logs the actions and never sends them to the motors. To let a
model drive the robot, use `inference_kit/run_policy.py` or the panel ([`RUN-MODELS.md`](RUN-MODELS.md)):
both run `inference_kit/pi_bridge.py` on the Pi, which owns the Build HAT and sends back the motor state.

The **observation spec** says which camera feeds which policy image key and which motor
values form the state vector. It must match the LeRobot dataset the policy was trained on.
The default (both cameras, the four `pos_deg` values) is a placeholder; pass your own with
`--spec spec.json` (format in `neil_robot/observation.py`). On startup the script compares it
with the policy's inputs and stops if they disagree.

### Output

Each run saves to its own folder under `logs/` (not committed to git):

- `video.mp4` and `frames/frame_NNNN.jpg` for scripts that record
  (`stream_cameras.py`: one folder per camera, plus `combined.mp4` with both side by side)
- `info.json` with the settings and the motors' encoder positions

### Conventions

- **Wheels:** the left motor is mounted reversed, so forward is left `-speed`, right `+speed`. The code handles it.
- **Arm:** the motor is mounted reversed (a positive motor turn raises the arm) and runs at speed 5–15.
  Its weight pulls it down, so moves hold position instead of going limp.
- **Pi camera:** always flipped 180° on the sensor (`CAMERA_ROTATION`, default 180; 0 = as mounted).
  The flip is fixed: it never changes while running, so the image only turns if the camera or robot
  physically turns. The external camera is not flipped (`EXTERNAL_CAMERA_ROTATION`, default 0).
- **Motor positions** reset whenever the Build HAT restarts. Compare positions within a run, not across runs.

### Code layout

```
gamepad.py       USB gamepad reader (hidapi), used by scripts/gamepad_drive.py
neil_robot/
  config.py      all settings (ports, speeds, camera); each can be overridden with an env var
  rpi_client.py  SSH connection; runs Python on the Pi and returns its result
  hardware.py    Pi-side scripts and the functions that call them (motors, camera, status)
  streams.py     live MJPEG streams: Pi camera (server started on the Pi) and the external camera
  video.py       turns frames into video.mp4 + frames/
  recorder.py    synced recording at a fixed rate; on_step lets a live consumer see every step
  run_video.py   a policy run's videos: the cameras at 30 fps, apart from the policy's step rate
  observation.py recorder step -> policy observation (the observation spec)
  policy_client.py   HTTP client for the policy server
  policy_runner.py   real-time loop: observations out, action chunks back, queue + logging
  replay.py      a recorded session served as if it were the live robot
pi/              scripts the laptop runs on the Pi over SSH: gamepad_server.py (the motors, for
                 gamepad_drive.py) and replay_server.py (for replay_session.py)
policy_server/   standalone policy server (LeRobot / SmolVLA, or --dummy), runs in .venv-vla
scripts/         the command-line tools above
specs/           observation specs for scripts/run_policy.py and the panel, one per model
training/        recordings -> LeRobot dataset, and the Athena training job (training/README.md)
inference_kit/   runs a trained model on the robot (RUN-MODELS.md)
gui/             browser control panel for running a model (gui/README.md)
models/          trained models, not in git (RUN-MODELS.md says where to get them)
```

To add a new robot action, write its Pi-side script and a function for it in `hardware.py`, following
`drive_and_arm_sequence`, then call it from a script.
