#!/bin/bash
# New-task training, cold or warm start. Runs on an Athena GPU node, started by train_v2.job:
#   sbatch train_v2.job <dataset_name> cold [steps]    from lerobot/smolvla_base: 10000 steps, LR 1e-4
#   sbatch train_v2.job <dataset_name> warm [steps]    from the pos2 weights: 5000 steps, LR 5e-5
#   TEST=1 sbatch --qos=2h_2g --time=00:30:00 train_v2.job <dataset_name> warm   200-step check
#   DRYRUN=1 bash train_v2.sh <dataset_name> warm      print the command, run nothing (works anywhere)
# The dataset must be in $VLA/data/<dataset_name>. The warm run also needs
#   $VLA/data/<dataset_name>/meta/stats_warm.json   (made by training/stats_compare.py)
#   $POS2/model.safetensors                          (our copy of the pos2 weights, README-v2.md)
# The warm run reads the dataset through data/<dataset_name>_warm: a copy of meta/ with stats_warm.json
# as stats.json, and links to data/ and videos/. So cold and warm jobs can run at the same time.
set -e
VLA=${VLA:-/rg/belinkov_prj/qiu.qiqian/vla}
POS2=${POS2:-$VLA/shared/lina/pos2_weights/pretrained_model}
umask 002                             # teammates can change new files
NAME=${1:?give the dataset name, for example: sbatch train_v2.job my_task warm}
INIT=${2:?give cold or warm}
JOB=${SLURM_JOB_ID:-local}

case $INIT in
  cold) POLICY=lerobot/smolvla_base; ROOT=$VLA/data/$NAME;      STEPS=${3:-10000}; SAVE=2000; LR=1e-4; LR_END=2.5e-6 ;;
  warm) POLICY=$POS2;                ROOT=$VLA/data/${NAME}_warm; STEPS=${3:-5000}; SAVE=1000; LR=5e-5; LR_END=1.25e-6 ;;
  *) echo "INIT must be cold or warm, not '$INIT'"; exit 1 ;;
esac
BATCH=32; EVAL=500; LOG=100
if [ -n "$TEST" ]; then STEPS=200; BATCH=8; EVAL=100; SAVE=200; LOG=20; fi
OUT=$VLA/outputs/lina_${NAME}_${INIT}_${JOB}

if [ -z "$DRYRUN" ]; then
  SRC=$VLA/data/$NAME
  [ -f $SRC/meta/info.json ] || { echo "No dataset in $SRC (copy it with README-v2.md step 2)"; exit 1; }
  if [ $INIT = warm ]; then
    [ -f $POS2/model.safetensors ] || { echo "No pos2 weights in $POS2 (README-v2.md step 1)"; exit 1; }
    [ -f $SRC/meta/stats_warm.json ] || { echo "No $SRC/meta/stats_warm.json: run stats_compare.py on the laptop first"; exit 1; }
    # (Re)build the warm view when it is missing or its meta differs from the dataset's
    if ! cmp -s $SRC/meta/stats_warm.json $ROOT/meta/stats.json || ! cmp -s $SRC/meta/info.json $ROOT/meta/info.json; then
      echo "Building $ROOT"
      rm -rf $ROOT && mkdir -p $ROOT
      cp -r $SRC/meta $ROOT/meta
      cp $SRC/meta/stats_warm.json $ROOT/meta/stats.json
      ln -s $SRC/data $ROOT/data
      ln -s $SRC/videos $ROOT/videos
    fi
  fi
fi

# The team's .venv/bin/python points into a home folder other users can't read, so run the same
# Python from the shared folder with the .venv's packages.
PY=$VLA/python/cpython-3.12.15-linux-x86_64-gnu/bin/python3.12
export PYTHONPATH=$VLA/.venv/lib/python3.12/site-packages
export HF_HOME=$VLA/hf
export HF_HUB_OFFLINE=1               # use only local files: no Hugging Face account, no upload
export WANDB_MODE=offline WANDB_DIR=$VLA/shared/lina/wandb/${NAME}_${INIT}_${JOB}

CMD=($PY -m lerobot.scripts.lerobot_train
  --policy.path=$POLICY
  --policy.push_to_hub=false
  --policy.device=cuda
  --policy.optimizer_lr=$LR
  --policy.scheduler_decay_lr=$LR_END
  --dataset.repo_id=local/$NAME
  --dataset.root=$ROOT
  --dataset.video_backend=pyav
  --dataset.image_transforms.enable=true
  --dataset.image_transforms.random_order=true
  --dataset.eval_split=0.1
  --eval_steps=$EVAL
  --batch_size=$BATCH
  --num_workers=8
  --seed=1000
  --steps=$STEPS
  --save_freq=$SAVE
  --log_freq=$LOG
  --output_dir=$OUT
  --job_name=lina_${NAME}_${INIT}_${JOB}
  --wandb.enable=true
  --wandb.mode=offline)

echo "INIT=$INIT steps=$STEPS batch=$BATCH lr=$LR output=$OUT"
if [ -n "$DRYRUN" ]; then printf '%s \\\n  ' "${CMD[@]}"; echo; exit 0; fi
mkdir -p $WANDB_DIR
cd $VLA
nvidia-smi
"${CMD[@]}"
