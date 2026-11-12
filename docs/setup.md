# Setup: replicate Neil

This page is for someone who wants to rebuild Neil and train their own copy of our SmolVLA model without access to Technion's Athena cluster. It has two parts: what to buy, and how to train on a rented A100 on Vast.ai.

The robot setup itself (Pi, cameras, gamepad, recording demos) is in the main [README](../README.md#setup). Training on Athena is in [`training/README.md`](../training/README.md).

## 1. What you need (bill of materials)

<!-- Prices marked "approx." are typical list prices, not what we paid. TODO cells are for the team to fill in. -->

### Robot

| Item | What we used | Qty | Approx. price | Link |
|---|---|---|---|---|
| Single-board computer | Raspberry Pi 4 (2 GB or more) | 1 | ~$45–55 | [raspberrypi.com](https://www.raspberrypi.com/products/raspberry-pi-4-model-b/) |
| Motor controller | Raspberry Pi Build HAT | 1 | ~$25 | [raspberrypi.com](https://www.raspberrypi.com/products/build-hat/) |
| Build HAT power supply | 8 V barrel-jack PSU (the motors need it) | 1 | ~$15 | [raspberrypi.com](https://www.raspberrypi.com/products/build-hat-power-supply/) |
| Robot camera | Pi Camera v1 (OV5647) | 1 | ~$15–25 | |
| microSD card | 32 GB, Raspberry Pi OS Bookworm | 1 | ~$10 | |
| LEGO motors | TODO: model (Build HAT-compatible, with encoders). Ports A/B wheels, C gripper, D arm | 4 | TODO | |
| LEGO parts | TODO: chassis, gripper and arm parts (set number or parts list) | – | TODO | |

### Data collection and control

| Item | What we used | Qty | Approx. price | Notes |
|---|---|---|---|---|
| Laptop | MacBook (Apple M4) | 1 | – | Runs the gamepad driver, recorder and policy server. Any laptop with Python 3.12 works; a GPU or Apple silicon makes inference faster. |
| Top camera | Any phone with an MJPEG IP-camera app | 1 | – | Mounted above the table, same Wi-Fi as the Pi |
| Phone mount | Tripod or clamp arm | 1 | ~$15–25 | |
| USB gamepad | D-pad and four face buttons (ours: USB ID `0810:E501`) | 1 | ~$15 | Other pads need their IDs set in `gamepad.py` |
| Task objects | Cups | a few | ~$5 | |
| Wi-Fi network | Pi, phone and laptop on the same network | – | – | |

### Compute

| Item | Unit | Per training run | Notes |
|---|---|---|---|
| A100 80GB on Vast.ai | GPU-hour, ~$0.80 | ~$3–5 | One `pick_cup_pos2` run (10k steps, batch 32) is about 4–6 hours. See [cloud-training.md](cloud-training.md) for other providers. |
| Vast.ai prepaid credit | – | $10 to start | Covers two or three full runs plus tests |

**Rough total:** about $150–200 for the electronics and accessories, plus the LEGO parts, plus about $3–5 per training run.

## 2. Train on a rented A100 (Vast.ai)

This reproduces our `pick_cup_pos2` run (Athena job 181719: 10,000 steps, batch 32, final loss 0.091) on a single rented A100. You need the dataset folder `pick_cup_pos2` (86 MB, ask the team) or your own dataset made with `scripts/session_to_episode.py`.

Time: about 15 minutes of setup the first time, then 4 to 6 hours of training you don't need to watch.

### 2.1 One-time account setup

1. Create an account at [vast.ai](https://vast.ai) and open the console at [cloud.vast.ai](https://cloud.vast.ai/).
2. Add credit under **Billing**. $10 is enough to start.
3. Add your SSH public key on the [Keys page](https://cloud.vast.ai/manage-keys/) (SSH Keys section). No key yet? Run `ssh-keygen -t ed25519` and paste the contents of `~/.ssh/id_ed25519.pub`.

Vast.ai's own guides: [Quickstart](https://docs.vast.ai/quickstart), [SSH connection](https://docs.vast.ai/instances/sshscp), [Billing](https://docs.vast.ai/guides/reference/billing), [Finding and renting](https://docs.vast.ai/guides/instances/choosing/find-and-rent).

### 2.2 Rent an A100

1. Go to **Search** (Templates → pick **PyTorch (Vast)** or another PyTorch + CUDA template).
2. Set the filters:
   - GPU: **A100 SXM4** or **A100 PCIe**, 1x
   - Disk space: **50 GB** or more
   - Reliability: **above 99%**
   - CUDA version (the machine's max supported, `cuda_vers` in the CLI): **12.8 or higher**, because our PyTorch build is for CUDA 12.8
   - Download speed: 200 Mbps or more
3. Sort by price and pick a host around **$0.70–1.00 per hour**. Before renting, check the host's bandwidth price. Some hosts charge per GB for transfers, and we move about 3 GB (base model plus checkpoints).
4. Click **Rent**. After a minute or two the instance shows as running on the **Instances** page. Click its SSH button to copy the command, which looks like `ssh -p 41234 root@203.0.113.7`.

### 2.3 Install the training software (on the instance, ~10 minutes)

These are the same versions as `training/athena/setup_env.sh`, which trained job 181719.

```bash
ssh -p <PORT> root@<IP>
mkdir -p /workspace && cd /workspace
curl -LsSf https://astral.sh/uv/install.sh | sh && export PATH=$HOME/.local/bin:$PATH
uv venv -p 3.12 .venv && source .venv/bin/activate
uv pip install torch==2.8.0 torchvision==0.23.0 --index-url https://download.pytorch.org/whl/cu128
uv pip install "lerobot[smolvla,training]==0.6.1" torchcodec==0.7.0
hf download lerobot/smolvla_base
hf download HuggingFaceTB/SmolVLM2-500M-Video-Instruct
python -c "import lerobot, torch; print('lerobot', lerobot.__version__, 'cuda', torch.cuda.is_available())"
```

The last line must print `cuda True`.

### 2.4 Upload the dataset (from your laptop)

Run this in the repo's `training` folder. First check your copy against our checksums (all 7 lines must say `OK`), then upload it:

```bash
(cd /path/to/pick_cup_pos2 && shasum -a 256 -c "$OLDPWD/runs/pick_cup_pos2_181719/data_sha256.txt")
rsync -av -e "ssh -p <PORT>" /path/to/pick_cup_pos2 root@<IP>:/workspace/data/
```

Don't put a `/` after `pick_cup_pos2`, or rsync copies the folder's contents instead of the folder.

### 2.5 Train

Start a `tmux` session so training keeps going if your SSH connection drops (`tmux attach` brings it back):

```bash
tmux new -s train
cd /workspace && source .venv/bin/activate
export HF_HUB_OFFLINE=1
NAME=pick_cup_pos2 STEPS=200 BATCH=8      # first a 200-step test, a few minutes
lerobot-train \
  --policy.path=lerobot/smolvla_base \
  --policy.push_to_hub=false \
  --policy.device=cuda \
  --dataset.repo_id=local/$NAME \
  --dataset.root=/workspace/data/$NAME \
  --dataset.video_backend=pyav \
  --batch_size=$BATCH \
  --steps=$STEPS \
  --save_freq=$(( STEPS < 2000 ? STEPS : 2000 )) \
  --output_dir=/workspace/outputs/neil_${NAME}_${STEPS} \
  --job_name=neil_${NAME} \
  --wandb.enable=false
```

This is the same command as `training/athena/train.sh`. When the test finishes without errors, run it again with `STEPS=10000 BATCH=32` for the full run. Leave tmux with Ctrl-B then D.

If the 200-step test takes much longer than about 5 minutes, the host is slow. Destroy the instance and rent another.

### 2.6 Download the model and stop paying

From your laptop:

```bash
rsync -av -e "ssh -p <PORT>" \
  root@<IP>:/workspace/outputs/neil_pick_cup_pos2_10000/checkpoints/last/pretrained_model \
  models/my_pick_cup/
```

Then **Destroy** the instance on the Instances page. **Stop** is not enough: a stopped instance still bills for its disk.

Run the model on the robot as described in [`RUN-MODELS.md`](../RUN-MODELS.md), with `--action-mode delta` like `pick_cup_pos2`.

### Things to know

- **Cost:** a full run is about $3–5. The 200-step test costs a few cents. You pay per second while the instance runs.
- **Hosts vary.** Vast.ai is a marketplace of individual hosts. Stick to reliability above 99%, and switch hosts if the test runs slowly.
- **Your data sits on someone else's machine** while the instance runs. That's fine for cup demos; think twice for anything sensitive.
- **Results won't match ours to the last digit.** The seed is fixed (1000), but GPU training isn't fully deterministic. Compare your `train_config.json` with `training/runs/pick_cup_pos2_181719/train_config.json`.
- **Scripting it:** Vast.ai has a [CLI](https://docs.vast.ai/cli/get-started) (`pip install vastai`). `vastai search offers 'gpu_name=A100_SXM4 num_gpus=1 reliability>0.99 disk_space>=50 cuda_vers>=12.8' -o 'dph'` lists matching machines, cheapest first.
