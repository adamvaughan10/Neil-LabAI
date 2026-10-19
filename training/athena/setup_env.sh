#!/bin/bash
# One-time setup of a new project folder on Athena (10 to 15 minutes). Run it on a login node:
#   VLA=/path/to/vla bash setup_env.sh
# The team folder /rg/belinkov_prj/qiu.qiqian/vla already has all of this.
# Versions are the ones in SETUP-MANUAL step C7, used for job 181719.
set -e
VLA=${VLA:-/rg/belinkov_prj/qiu.qiqian/vla}
mkdir -p $VLA/jobs $VLA/data $VLA/outputs $VLA/hf
cd $VLA
command -v uv >/dev/null || curl -LsSf https://astral.sh/uv/install.sh | sh
export PATH=$HOME/.local/bin:$PATH
uv venv -p 3.12 .venv
source .venv/bin/activate
uv pip install torch==2.8.0 torchvision==0.23.0 --index-url https://download.pytorch.org/whl/cu128
uv pip install "lerobot[smolvla,training]==0.6.1" torchcodec==0.7.0
# train.sh runs offline (HF_HUB_OFFLINE=1), so the base model must be downloaded first
export HF_HOME=$VLA/hf
hf download lerobot/smolvla_base
hf download HuggingFaceTB/SmolVLM2-500M-Video-Instruct
python -c "import lerobot; print('lerobot', lerobot.__version__)"
