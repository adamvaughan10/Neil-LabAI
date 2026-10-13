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
| `python scripts\sequence_test.py` | **yes** | Forward 0.5 s, backward 0.5 s, then arm up 30° and back down. Prints how far each motor turned. |
| `python scripts\arm_test.py` | **yes** | Lowers the arm 30° and raises it back while recording video. |
| `python scripts\motor_test.py` | **yes** | Turns each port 30° and back, asking before each. |
| `python gamepad.py` | no | Prints the USB gamepad's D-pad and buttons live. |
| `python scripts\gamepad_drive.py` | **yes** | Drives the robot from the gamepad: D-pad drives and rotates while held, X/B move the arm and Y/A the gripper a fixed angle per press. The Pi side is `pi/gamepad_server.py`. |

Before running anything that moves: lift the robot so the wheels spin freely (or give it about 30 cm of room)
and keep hands clear of the arm.

### Output

Each run saves to its own folder under `logs/` (not committed to git):

- `video.mp4` and `frames/frame_NNNN.jpg` for scripts that record
- `info.json` with the settings and the motors' encoder positions

### Conventions

- **Wheels:** the left motor is mounted reversed, so forward is left `-speed`, right `+speed`. The code handles it.
- **Arm:** the motor is mounted reversed (a positive motor turn raises the arm) and runs at speed 5–15.
  Its weight pulls it down, so moves hold position instead of going limp.
- **Camera:** mounted upside down; frames are flipped 180° on the sensor (`CAMERA_ROTATION`).
- **Motor positions** reset whenever the Build HAT restarts. Compare positions within a run, not across runs.

### Code layout

```
neil_robot/
  config.py      all settings (ports, speeds, camera); each can be overridden with an env var
  rpi_client.py  SSH connection; runs Python on the Pi and returns its result
  hardware.py    Pi-side scripts and the functions that call them (motors, camera, status)
  video.py       turns a raw recording into video.mp4 + frames
scripts/         the command-line tools above
```

To add a new robot action, write its Pi-side script and a function for it in `hardware.py`, following
`drive_and_arm_sequence`, then call it from a script.
