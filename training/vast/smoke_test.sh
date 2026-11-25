#!/bin/bash
# Quick end-to-end check of a rented Vast.ai GPU before a real training run (about 5 minutes,
# plus ~10 minutes the first time while it installs). Run it on your laptop from the repo folder:
#
#   bash training/vast/smoke_test.sh <PORT> <IP> /path/to/pick_cup_pos2
#
# <PORT> and <IP> come from the instance's SSH command on cloud.vast.ai (ssh -p PORT root@IP).
# It checks, in order: SSH works, the GPU is visible, the training software imports (and installs it
# if missing), the base model is downloaded, the dataset uploads and matches our checksums, and
# 20 training steps run. It stops at the first failure and says what to do.
# Works with macOS's built-in bash 3.2. See docs/setup.md, section 2.
set -euo pipefail

PORT=${1:?usage: smoke_test.sh <PORT> <IP> <dataset_folder>}
IP=${2:?usage: smoke_test.sh <PORT> <IP> <dataset_folder>}
DATA=${3:?usage: smoke_test.sh <PORT> <IP> <dataset_folder>}
DATA=${DATA%/}
NAME=$(basename "$DATA")
HERE=$(cd "$(dirname "$0")" && pwd)
SUMS="$HERE/../runs/pick_cup_pos2_181719/data_sha256.txt"
SSH=(ssh -p "$PORT" -o ConnectTimeout=15 -o StrictHostKeyChecking=accept-new "root@$IP")

step() { printf '\n== %s\n' "$1"; }
ok()   { printf 'PASS  %s\n' "$1"; }
fail() { printf 'FAIL  %s\n      %s\n' "$1" "$2"; exit 1; }

[[ -d "$DATA/meta" ]] || fail "dataset folder" "$DATA has no meta/ folder. Point it at the LeRobot dataset folder (e.g. pick_cup_pos2)."

step "1/6 SSH connection"
"${SSH[@]}" true 2>/dev/null \
  || fail "ssh root@$IP -p $PORT" "Check the port and IP on the Instances page, that the instance is running, and that your SSH key is on cloud.vast.ai/manage-keys."
ok "connected to $IP"

step "2/6 GPU"
GPU=$("${SSH[@]}" "nvidia-smi --query-gpu=name,memory.total,driver_version --format=csv,noheader" 2>/dev/null) \
  || fail "nvidia-smi" "No GPU visible. Destroy this instance and rent another."
ok "$GPU"

step "3/6 Training software (installs it the first time, ~10 min)"
"${SSH[@]}" 'bash -s' <<'EOF' || fail "install / import" "See the error above. Check the host's CUDA version is 12.8 or higher."
set -e
mkdir -p /workspace/data /workspace/outputs && cd /workspace
export PATH=$HOME/.local/bin:$PATH
if [[ ! -x .venv/bin/lerobot-train ]]; then
  echo "Installing (same versions as training/athena/setup_env.sh)..."
  command -v uv >/dev/null || curl -LsSf https://astral.sh/uv/install.sh | sh >/dev/null
  uv venv -q -p 3.12 .venv
  source .venv/bin/activate
  uv pip install -q torch==2.8.0 torchvision==0.23.0 --index-url https://download.pytorch.org/whl/cu128
  uv pip install -q "lerobot[smolvla,training]==0.6.1" torchcodec==0.7.0
fi
source .venv/bin/activate
python -c "import torch, lerobot; assert torch.cuda.is_available(), 'torch cannot see the GPU'; print('lerobot', lerobot.__version__, '| torch', torch.__version__, '| cuda OK')"
EOF
ok "lerobot imports and sees the GPU"

step "4/6 Base model"
"${SSH[@]}" 'bash -s' <<'EOF' || fail "hf download" "Could not download the base model. Check the instance has internet (try another host)."
set -e
cd /workspace && source .venv/bin/activate
hf download lerobot/smolvla_base >/dev/null
hf download HuggingFaceTB/SmolVLM2-500M-Video-Instruct >/dev/null
echo "smolvla_base and SmolVLM2 are in the cache"
EOF
ok "base model downloaded"

step "5/6 Upload dataset and check it"
rsync -a -e "ssh -p $PORT" "$DATA" "root@$IP:/workspace/data/" \
  || fail "rsync" "Upload failed. Run the script again; rsync continues where it stopped."
if [[ "$NAME" == "pick_cup_pos2" && -f "$SUMS" ]]; then
  "${SSH[@]}" "cd /workspace/data/$NAME && sha256sum -c --quiet" < "$SUMS" \
    || fail "checksums" "The uploaded dataset is not the same as the one job 181719 used. Get a fresh copy of pick_cup_pos2."
  ok "uploaded, all 7 files match job 181719's checksums"
else
  ok "uploaded $NAME (no checksums to compare for this dataset)"
fi

step "6/6 Train 20 steps (batch 8)"
"${SSH[@]}" "NAME=$NAME bash -s" <<'EOF' || fail "lerobot-train" "Training failed. The error above says why (out of memory: rent a bigger GPU; feature mismatch: wrong dataset format)."
set -e
cd /workspace && source .venv/bin/activate
export HF_HUB_OFFLINE=1
OUT=/workspace/outputs/smoke_test
rm -rf "$OUT"
START=$(date +%s)
lerobot-train \
  --policy.path=lerobot/smolvla_base \
  --policy.push_to_hub=false \
  --policy.device=cuda \
  --dataset.repo_id=local/$NAME \
  --dataset.root=/workspace/data/$NAME \
  --dataset.video_backend=pyav \
  --batch_size=8 \
  --steps=20 \
  --save_freq=20 \
  --output_dir=$OUT \
  --job_name=smoke_test \
  --wandb.enable=false > /workspace/outputs/smoke_test.log 2>&1 || { tail -30 /workspace/outputs/smoke_test.log; exit 1; }
END=$(date +%s)
test -d $OUT/checkpoints/last/pretrained_model || { echo "no checkpoint was saved"; exit 1; }
echo "20 steps + model load + checkpoint save took $((END-START)) s"
rm -rf "$OUT"
EOF
ok "training runs and saves a checkpoint"

printf '\nAll checks passed. Start the full run (docs/setup.md, section 2.5) with STEPS=10000 BATCH=32.\n'
printf 'Not training now? Destroy the instance on cloud.vast.ai so it stops billing.\n'
