# Neil-LabAI

LEGO robot driven from a laptop: a Raspberry Pi 4 with a Build HAT and a Pi Camera v1 (OV5647).
The approach follows [f1ren/lego-robot-mcp](https://github.com/f1ren/lego-robot-mcp): the laptop keeps one
SSH connection to the Pi and runs short Python scripts there with the Pi's own `buildhat` and `picamera2`,
so nothing has to be deployed to the Pi.

## Hardware

| Build HAT port | Default role  | Env var to change it |
|----------------|---------------|----------------------|
| A              | left wheel    | `PORT_LEFT_WHEEL`    |
| B              | right wheel   | `PORT_RIGHT_WHEEL`   |
| C              | gripper       | `PORT_GRIPPER`       |
| D              | arm           | `PORT_ARM`           |

Motors need the Build HAT's 8 V barrel-jack supply.

## Setup

### Pi (once)

1. Install your laptop's SSH key on the Pi (PowerShell; asks for the Pi password once):
   ```powershell
   Get-Content $env:USERPROFILE\.ssh\id_ed25519.pub | ssh rpi@132.68.34.107 "mkdir -p ~/.ssh && chmod 700 ~/.ssh && cat >> ~/.ssh/authorized_keys && chmod 600 ~/.ssh/authorized_keys"
   ssh -o BatchMode=yes rpi@132.68.34.107 echo ok    # must print ok without a password
   ```
2. Serial port for the Build HAT: `sudo raspi-config` → Interface Options → Serial Port →
   login shell **No**, serial hardware **Yes**, reboot.
3. Libraries: `sudo apt install python3-build-hat python3-picamera2`

`scripts/check_pi.py` verifies all of this.

### Laptop

```powershell
conda create -n neil_robot python=3.11
conda activate neil_robot
pip install -r requirements.txt
```

The Pi's address and user default to `132.68.34.107` / `rpi`. If the Pi gets a new IP, set `RPI_HOST`.

## Usage

Every time, in a new PowerShell window:

```powershell
cd robot\Neil-LabAI          # this repo
conda activate neil_robot
```

Then run any script. Add `--help` to see its options.

| Script | Moves the robot? | What it does |
|--------|------------------|--------------|
| `python scripts\check_pi.py` | no | Checks SSH, OS, serial port, libraries, HAT voltage, what's on each port, and saves a camera still to `output/`. Run this first. |
| `python scripts\record_video.py` | no | Records 5 s from the Pi camera (`--seconds` to change). |
| `python scripts\stream_cameras.py` | no | Live window with both cameras side by side. `r` starts/stops a **synced recording** (15 fps), `s` saves a snapshot, `q` quits. `--record 10` records 10 s without a window; `--fps` changes the rate. |
| `python scripts\sequence_test.py` | **yes** | Forward 0.5 s, backward 0.5 s, then arm up 30° and back down. Prints how far each motor turned. |
| `python scripts\arm_test.py` | **yes** | Lowers the arm 30° and raises it back while recording video. |
| `python scripts\motor_test.py` | **yes** | Turns each port 30° and back, asking before each. |
| `python scripts\run_policy.py` | no (dry run) | Runs a VLA policy in real time: every step's images and motor state go to the policy server, action chunks come back and are logged. `--replay <session>` runs it on a recording, without the robot. See below. |

Before running anything that moves: lift the robot so the wheels spin freely (or give it about 30 cm of room)
and keep hands clear of the arm.

### External camera

A phone IP-camera app serving MJPEG at `http://132.68.34.87:8080/stream.mjpg` (plain **http**; https fails).
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

**Dry run for now:** actions are logged, never sent to the motors. Driving them needs a
Pi-side controller that owns the Build HAT and streams motor state at the same time.

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
neil_robot/
  config.py      all settings (ports, speeds, camera); each can be overridden with an env var
  rpi_client.py  SSH connection; runs Python on the Pi and returns its result
  hardware.py    Pi-side scripts and the functions that call them (motors, camera, status)
  streams.py     live MJPEG streams: Pi camera (server started on the Pi) and the external camera
  video.py       turns frames into video.mp4 + frames/
  recorder.py    synced recording at a fixed rate; on_step lets a live consumer see every step
  observation.py recorder step -> policy observation (the observation spec)
  policy_client.py   HTTP client for the policy server
  policy_runner.py   real-time loop: observations out, action chunks back, queue + logging
  replay.py      a recorded session served as if it were the live robot
policy_server/   standalone policy server (LeRobot / SmolVLA, or --dummy), runs in the neil_vla env
scripts/         the command-line tools above
```

To add a new robot action, write its Pi-side script and a function for it in `hardware.py`, following
`drive_and_arm_sequence`, then call it from a script.
