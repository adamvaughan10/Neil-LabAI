# Team Guide: Our Project on Athena

This guide is for every teammate whose Athena account is in the Belinkov lab group (`belinkov_prj`).

In the commands below, replace `your.name` with your own Athena username.

> [!IMPORTANT]
> - Athena works only from the Technion network: Technion Wi-Fi (not techpublic), or the Technion VPN.
> - GPU hours are billed to the lab. Ask the team before you start a long training job.

---

## 1. Where the project is

The project folder is:
```
/rg/belinkov_prj/qiu.qiqian/vla
```

| Folder | Content | Can you change it? |
|---|---|---|
| `jobs/` | Training scripts and job logs | Yes |
| `data/` | Recorded datasets (one folder for each dataset) | Yes |
| `outputs/` | Trained models (one folder for each job) | Yes |
| `shared/` | Any other team files | Yes |
| `.venv/` | Python with LeRobot and SmolVLA | No (read only) |
| `hf/` | SmolVLA base model files | Do not change |

> [!WARNING]
> Do not delete files that other teammates made.

---

## 2. Log in and open the folder

On your Mac, run these 2 commands, one at a time:
```bash
ssh your.name@athena.technion.ac.il
cd /rg/belinkov_prj/qiu.qiqian/vla
```
Type `exit` to go back to your Mac.

---

## 3. Copy files and add files

Run these on your Mac, not on Athena. You do not need to log in first.

| What | Command (on the Mac) |
|---|---|
| Copy a folder from Athena to your Mac | `rsync -av your.name@athena.technion.ac.il:/rg/belinkov_prj/qiu.qiqian/vla/outputs/neil_JOBID ./` |
| Add a dataset from your Mac | `rsync -av data/xxx your.name@athena.technion.ac.il:/rg/belinkov_prj/qiu.qiqian/vla/data/` (put the dataset name here) |
| Add any other file | `rsync -av myfile your.name@athena.technion.ac.il:/rg/belinkov_prj/qiu.qiqian/vla/shared/` |

rsync copies only new and changed files. If the copy stops, run the same command again.

---

## 4. Update the scripts

The scripts are in our GitHub repo, in the folder `vla/athena/`. Change them on your Mac, not on Athena.

1. Get the newest code:
   ```bash
   git pull
   ```
2. Change the script on your Mac.
3. Send the change to the team:
   ```bash
   git add -A
   git commit -m "what you changed"
   git push
   ```
4. Copy the scripts to Athena. Run this from the repo folder on the Mac:
   ```bash
   rsync -av vla/athena/ your.name@athena.technion.ac.il:/rg/belinkov_prj/qiu.qiqian/vla/jobs/
   ```

---

## 5. Run a training job

1. Log in to Athena and go to the job folder:
   ```bash
   ssh your.name@athena.technion.ac.il
   cd /rg/belinkov_prj/qiu.qiqian/vla/jobs
   ```
2. Start a short test (200 steps, about 10 minutes):
   ```bash
   sbatch --qos=2h_2g --time=00:30:00 train_neil.job 200 8 xxx
   ```
   Put the dataset name in place of `xxx`. The dataset must be in `data/`.
3. Start the full training (20000 steps, about 4 hours) only after the test works:
   ```bash
   sbatch train_neil.job 20000 64 xxx
   ```
4. `sbatch` prints `Submitted batch job 123456`. Write down this job number (JOBID).

---

## 6. See the results

All these commands are on Athena, in the `jobs` folder.

| What | Command |
|---|---|
| Show your jobs (`PD` = waiting, `R` = running) | `tsqr -u $USER` |
| Watch the job log live (Ctrl+C stops watching, not the job) | `tail -f neil_smolvla_JOBID.log` |
| Stop a job | `scancel JOBID` |
| Show all trained models | `ls ../outputs` |

The trained model of a job is in:
```
/rg/belinkov_prj/qiu.qiqian/vla/outputs/neil_JOBID/checkpoints/last/pretrained_model
```
Copy it to your Mac with the first command in section 3. Then run it on Neil with `run_policy.py` (see `VLA-MANUAL.md`, section 10).
