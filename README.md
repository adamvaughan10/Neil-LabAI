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

```powershell
python scripts/check_pi.py      # read-only: SSH, OS, serial, libraries, HAT voltage, ports, camera still
python scripts/motor_test.py    # MOVES motors: each port +30° and back, asks before each
```

Camera stills go to `output/`. All settings are in `neil_robot/config.py`.
