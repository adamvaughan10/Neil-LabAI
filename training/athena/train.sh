#!/bin/bash
# Runs on an Athena GPU node. Started by train_neil.job.
# Usage (through sbatch): sbatch train_neil.job <steps> <batch_size> [dataset_name]
# The dataset must be in $VLA/data/<dataset_name> (copied from the Mac with rsync).
set -e
VLA=${VLA:-/rg/belinkov_prj/qiu.qiqian/vla}   # team folder, the same path for every teammate
umask 002                             # teammates can change new files
STEPS=${1:-20000}
BATCH=${2:-64}
NAME=${3:?give the dataset name, for example: sbatch train_neil.job 20000 64 pick_cup}

source $VLA/.venv/bin/activate
export HF_HOME=$VLA/hf
export HF_HUB_OFFLINE=1          # use only local files: no Hugging Face account, no upload
cd $VLA
nvidia-smi

lerobot-train \
  --policy.path=lerobot/smolvla_base \
  --policy.push_to_hub=false \
  --policy.device=cuda \
  --dataset.repo_id=local/$NAME \
  --dataset.root=$VLA/data/$NAME \
  --dataset.video_backend=pyav \
  --batch_size=$BATCH \
  --steps=$STEPS \
  --save_freq=$(( STEPS < 2000 ? STEPS : 2000 )) \
  --output_dir=$VLA/outputs/neil_${SLURM_JOB_ID} \
  --job_name=neil_${SLURM_JOB_ID} \
  --wandb.enable=false
