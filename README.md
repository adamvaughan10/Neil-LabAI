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
| `python scripts\stream_cameras.py` | no | Live window with the Pi camera and the external camera side by side. `r` records both, `s` saves a snapshot, `q` quits. `--record 10` records 10 s without a window. |
| `python scripts\sequence_test.py` | **yes** | Forward 0.5 s, backward 0.5 s, then arm up 30° and back down. Prints how far each motor turned. |
| `python scripts\arm_test.py` | **yes** | Lowers the arm 30° and raises it back while recording video. |
| `python scripts\motor_test.py` | **yes** | Turns each port 30° and back, asking before each. |

Before running anything that moves: lift the robot so the wheels spin freely (or give it about 30 cm of room)
and keep hands clear of the arm.

### External camera

A phone IP-camera app serving MJPEG at `http://132.68.34.87:8080/stream.mjpg` (plain **http**; https fails).
Keep the app open and in the foreground, with the phone unlocked and on the same Wi-Fi as the Pi:
the stream stops otherwise. Set `EXTERNAL_CAMERA_URL` if its address changes, and
`EXTERNAL_CAMERA_ROTATION` (0/90/180/270, clockwise) if its image comes out sideways.

The Pi camera has no stream of its own: `stream_cameras.py` starts a small MJPEG server on the Pi
(port 8765) for as long as it runs. Recordings from it are 640x480; `record_video.py` gives full 1296x972.

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
scripts/         the command-line tools above
```

To add a new robot action, write its Pi-side script and a function for it in `hardware.py`, following
`drive_and_arm_sequence`, then call it from a script.
