# Dry-Run Guide: Test the Model on Neil Without Moving It

`scripts/run_policy.py` sends Neil's live camera images and motor state to the model 15 times a
second and logs the actions the model returns. **Nothing moves.** Use it to check the model's
inputs and outputs, and how fast it answers, before you let it drive Neil.

> [!IMPORTANT]
> To actually drive Neil with the model today, follow `INFERENCE-GUIDE.md` (Qiqian's pipeline).
> Its code is in this repo, in `inference_kit/`, and it drives the motors with `pi_bridge.py`.

---

## How it works

Two programs, in two terminals:

| Program | Env | What it does |
|---|---|---|
| `policy_server/server.py` | `neil_vla` | Loads the model once and answers each request with 50 future actions |
| `scripts/run_policy.py` | `neil_robot` | Reads Neil's cameras and motors, sends them to the server, logs the actions |

Each run is saved in `logs/run_<date>_<time>/`: the camera images, `steps.jsonl` (with the model's
action for each step), `inference.jsonl` (how long each request took) and the videos.

---

## Part A: Setup (once)

1. Get the newest code:
   ```bash
   git pull
   ```
2. Make the model env. lerobot must be exactly 0.6.1, the version Athena trains with, and it needs Python 3.12:
   ```bash
   conda create -n neil_vla python=3.12 -y
   conda activate neil_vla
   pip install -r policy_server/requirements.txt
   ```
3. The robot env (`neil_robot`, from `README.md`) needs nothing new.
4. Copy the trained model from Athena (see `INFERENCE-GUIDE.md`, Part A step 4) to `models/pick_cup/pretrained_model`.

---

## Part B: Run a dry run

1. Set Neil's addresses. The code's defaults are for the lab network, not Neil's Wi-Fi
   (`192.168.8.x`). Run this in the robot terminal, with the phone camera's real address:
   ```bash
   export RPI_HOST=rpi.local
   export EXTERNAL_CAMERA_URL=http://<phone IP>:8080/stream.mjpg
   ```
2. Terminal 1, the server (`neil_vla` env):
   ```bash
   python policy_server/server.py --checkpoint models/pick_cup/pretrained_model --device mps
   ```
   Use `--device mps` on an Apple M1 or newer, `--device cuda` with an NVIDIA GPU. Without a GPU
   (CPU) it works but takes about 14 s per answer, so the log will show mostly waiting.
3. Terminal 2, the robot side (`neil_robot` env):
   ```bash
   python scripts/run_policy.py --spec specs/pick_cup.json --task "pick up the cup" --mode async --seconds 30
   ```
4. At the end it prints how many answers came back and how long they took, and where the run was saved.

### Without the robot

Add `--replay logs/session_<date>_<time>` to step 3 to feed a recorded session instead of the
live robot. Without a trained model, test with the base model:
```bash
python policy_server/server.py --checkpoint lerobot/smolvla_base
python scripts/run_policy.py --spec specs/smolvla_base_test.json --allow-missing-images --replay logs/session_<date>_<time>
```
The base model was not trained on Neil, so its actions mean nothing; this only tests the pipeline.

---

## Known gaps

| Gap | What to do |
|---|---|
| `specs/pick_cup.json` doesn't exist yet | It must list the dataset's camera keys and state values in the same order as training. It needs the `pick_cup` dataset's `meta/info.json`. Until then, `run_policy.py` refuses to start with the real model (it compares the spec with the model). |
| The addresses in the code are for the lab network | Set `RPI_HOST` and `EXTERNAL_CAMERA_URL` (Part B step 1) |
| `README.md` commands use Windows paths (`scripts\run_policy.py`) | On a Mac, use forward slashes (`scripts/run_policy.py`) |

---

## Next steps

1. Write `specs/pick_cup.json` from the dataset's `meta/info.json`.
2. Use `pi_bridge.py` from Qiqian's pipeline as the part of `run_policy.py` that sends the actions
   to the motors. Then one program drives Neil and also has the replay, the logs, and the option to
   run the model on an Athena GPU.
