# Training: reproduce the pick_cup_pos2 model

This folder has everything to train the `pick_cup_pos2` SmolVLA model again on Athena.
The only thing that is not in Git is the dataset folder `pick_cup_pos2` (86 MB). You get it separately.

The original run is Athena job 181719 (2026-10-14): 10000 steps, batch 32, final loss 0.091.

## What is in this folder

| File | What it does |
|---|---|
| `athena/setup_env.sh` | One-time setup of a new project folder: Python 3.12, LeRobot 0.6.1, SmolVLA base model. |
| `athena/train_neil.job` | The Slurm job file. You start it with `sbatch`. |
| `athena/train.sh` | The training command (`lerobot-train`). The job file runs it. |
| `runs/pick_cup_pos2_181719/train_config.json` | The full settings that LeRobot saved for job 181719. Use it to compare a new run. |
| `runs/pick_cup_pos2_181719/data_sha256.txt` | Checksums of the 7 dataset files. Use it to check that your dataset copy is the same. |
| `convert_episodes.py`, `neil_io.py` | The converter that made `pick_cup_pos2` from the raw recordings. You do not need it to train. It is here as a record. |

## The dataset

- Name: `pick_cup_pos2`. Task sentence: "pick up the cup".
- 47 episodes, 5083 frames, 10 fps. Source: the second recording batch ("all poistions 2", 5 cup positions).
- Action: left wheel and right wheel = degrees the wheel still has to turn; arm and gripper = target angle.
- Arm and gripper use `abs_pos_deg` on one fixed zero (arm = abs - 14, gripper = abs + 93, then sign flipped). The docstring of `convert_episodes.py` explains it.

## Reproduce the run

Run these steps from this `training` folder on your Mac. Replace `your.name` with your Athena username.

1. Check the dataset copy. All 7 lines must say `OK`:
   ```bash
   (cd /path/to/pick_cup_pos2 && shasum -a 256 -c "$OLDPWD/runs/pick_cup_pos2_181719/data_sha256.txt")
   ```
2. Copy the scripts to Athena:
   ```bash
   rsync -av athena/ your.name@athena.technion.ac.il:/rg/belinkov_prj/qiu.qiqian/vla/jobs/
   ```
3. Copy the dataset to Athena. Do not put a `/` after `pick_cup_pos2`:
   ```bash
   rsync -av /path/to/pick_cup_pos2 your.name@athena.technion.ac.il:/rg/belinkov_prj/qiu.qiqian/vla/data/
   ```
4. Log in and go to the job folder:
   ```bash
   ssh your.name@athena.technion.ac.il
   cd /rg/belinkov_prj/qiu.qiqian/vla/jobs
   ```
5. Start a short test (200 steps, about 4 minutes):
   ```bash
   sbatch --qos=2h_2g --time=00:30:00 train_neil.job 200 8 pick_cup_pos2
   ```
6. When the test works, start the full run (about 4 to 6 hours):
   ```bash
   sbatch --qos=12h_4g --time=12:00:00 train_neil.job 10000 32 pick_cup_pos2
   ```

The model is then in `/rg/belinkov_prj/qiu.qiqian/vla/outputs/neil_JOBID/checkpoints/last/pretrained_model`.
`ATHENA-QUICK.md` shows how to watch the job and copy the model back.

> [!NOTE]
> To use a different project folder (for example, an Athena account outside the Belinkov group):
> 1. Run `VLA=/your/folder bash athena/setup_env.sh` once on Athena.
> 2. Put the scripts in `/your/folder/jobs` and the dataset in `/your/folder/data`.
> 3. Start every job with `VLA=/your/folder sbatch ...`.

> [!WARNING]
> The result will be close to job 181719, but not the same to the last digit. The seed is fixed (1000), but GPU training is not fully deterministic.
