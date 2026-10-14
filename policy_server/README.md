# Policy server

Loads a trained VLA policy (SmolVLA, via LeRobot) once and answers
"observation → action chunk" requests over HTTP. The robot side is
`scripts/run_policy.py`; the two only share the wire format described in `server.py`.

This folder is standalone (no `neil_robot` imports), so the same `server.py` runs on the
laptop now and on an Athena GPU node later.

## Laptop (CPU, for testing the pipeline)

A separate env, because torch + lerobot are large and the robot env doesn't need them:

```powershell
conda create -n neil_vla python=3.12
conda activate neil_vla
pip install -r policy_server\requirements.txt
```

Two terminals:

```powershell
# 1. server (neil_vla env)
python policy_server\server.py --checkpoint path\to\pretrained_model
# or, without any model, to test the robot side:
python policy_server\server.py --dummy --dummy-latency 0.5

# 2. robot side (neil_robot env)
python scripts\run_policy.py                                         # live robot, dry run
python scripts\run_policy.py --replay logs\session_20261013_144751   # no robot needed
```

`--checkpoint` takes the `pretrained_model` folder an Athena training job writes
(`outputs/neil_JOBID/checkpoints/last/pretrained_model`), or a Hub id such as
`lerobot/smolvla_base`. lerobot is pinned to 0.6.1, the version Athena trains with
(INFERENCE-GUIDE.md); it needs Python 3.12. A checkpoint from another version may not load.

## Athena (GPU, later)

Run `server.py --device cuda` in a GPU job on Athena, and tunnel its port to the laptop:

```bash
ssh -N -L 8000:<node>:8000 your.name@athena.technion.ac.il
```

The robot side keeps using `http://127.0.0.1:8000`. Use `--mode async` there: the
network round trip is longer, and async keeps the robot acting while it waits.
