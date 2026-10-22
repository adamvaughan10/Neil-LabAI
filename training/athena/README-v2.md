# New-task training: cold vs warm start

`train_v2.sh` trains a new task twice, so the two runs can be compared:

| Run | Starts from | Steps | LR | Stats |
|---|---|---|---|---|
| `cold` | `lerobot/smolvla_base` | 10000, checkpoint every 2000 (as pos2) | 1e-4 | the dataset's own `stats.json` |
| `warm` | the pos2 weights (job 181719) | 5000, checkpoint every 1000 | 5e-5 | `stats_warm.json` from `stats_compare.py` |

Both use image augmentation, hold out 10% of the episodes (`eval_loss` every 500 steps), and log to
wandb offline. Our files go in our own folders: `jobs/lina/`, `data/<name>`, `outputs/lina_*`,
`shared/lina/`. The team's files are never touched.

Commands run in PowerShell on the laptop, from the repo folder, unless they say Athena. `athena` is the
SSH shortcut (`~/.ssh/config`).

## 1. Once: copy the pos2 weights to Athena

The team's copy on Athena can only be read by its owner, so we use ours from `models/`:
```powershell
ssh athena "mkdir -p /rg/belinkov_prj/qiu.qiqian/vla/shared/lina/pos2_weights /rg/belinkov_prj/qiu.qiqian/vla/jobs/lina"
scp -r models/handoff_pick_cup_pos2/pretrained_model athena:/rg/belinkov_prj/qiu.qiqian/vla/shared/lina/pos2_weights/
```

## 2. For each new dataset

1. Convert the recordings (in `.venv-vla`, from `training/`). Use the task sentence you will use on the robot:
   ```powershell
   python convert_episodes.py --name my_task --task "your task sentence" (Get-ChildItem ../logs -Directory -Filter "session_*").FullName
   ```
2. Compare its ranges with pos2's and write `meta/stats_warm.json`. Read the table: a `Warning` line means
   a sign or formula may be wrong in the recordings.
   ```powershell
   python stats_compare.py data/my_task
   ```
3. Copy the dataset and the scripts:
   ```powershell
   scp -r training/data/my_task athena:/rg/belinkov_prj/qiu.qiqian/vla/data/
   scp training/athena/train_v2.sh training/athena/train_v2.job athena:/rg/belinkov_prj/qiu.qiqian/vla/jobs/lina/
   ```

## 3. Train (on Athena)

```bash
ssh athena
cd /rg/belinkov_prj/qiu.qiqian/vla/jobs/lina
TEST=1 sbatch --qos=2h_2g --time=00:30:00 train_v2.job my_task cold     # 200-step checks first
TEST=1 sbatch --qos=2h_2g --time=00:30:00 train_v2.job my_task warm
sbatch train_v2.job my_task cold                                          # then both full runs together
sbatch train_v2.job my_task warm
```

In the test logs (`lina_v2_JOBID.log`), check that:
- the warm run's first `loss` is clearly lower than the cold run's (the pos2 weights were loaded),
- `eval_loss` lines appear,
- `data_s` is much smaller than `updt_s` (if not, data loading slows the GPU down).

`squeue -u $USER` shows your jobs, `scancel JOBID` stops one. The models are in
`/rg/belinkov_prj/qiu.qiqian/vla/outputs/lina_<name>_<cold|warm>_<JOBID>/checkpoints/`. The wandb logs
are in `shared/lina/wandb/`: copy one back and run `wandb sync <folder>` on a machine with internet to see
the curves.
