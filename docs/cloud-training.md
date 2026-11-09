# Training Neil's VLA on rented cloud GPUs

Prices checked on 2026-11-09. GPU rental prices move weekly, so treat every number here as a snapshot and re-check before you rent.

## Short answer

- A cloud GPU that can fine-tune SmolVLA costs about **$0.35 to $1.80 per hour**, not $0.0X. The cheapest usable cards (RTX 3090 / 4090 on marketplaces) start around $0.15 to $0.35 per hour; an A100 80GB is about $0.80 (Vast.ai median) to $1.80 (RunPod Secure).
- Because a full run is short, **one full training run (20k steps, batch 64) costs roughly $3 to $8**. The 200-step smoke test costs a few cents.
- Recommended: **RunPod (Community Cloud) or Vast.ai, one A100 80GB**, the closest match to what we run on Athena. Use an RTX 4090 if you want the cheapest option and accept a smaller batch and a longer run.

## What we need (our Athena spec)

From `training/athena/train_neil.job`, `train_v2.job` and `ATHENA-QUICK.md`:

| Resource | Athena job | Cloud equivalent |
|---|---|---|
| GPU | 1 GPU (`--gres=gpu:1`) | 1x A100 / H100 class, or 24 GB card with smaller batch |
| CPU | 8 cores | 8 vCPU |
| RAM | 48 to 64 GB | 32 to 64 GB |
| Run length | 20,000 steps at batch 64: about 4 h; 200-step test: about 10 min | same on A100 |
| Disk | dataset + base model + checkpoints | 50 GB is plenty |
| Software | Python 3.12, `lerobot[smolvla,training]==0.6.1`, CUDA | any PyTorch/CUDA image |

SmolVLA's own docs say the same thing: 20k steps take roughly 4 hours on a single A100 ([LeRobot SmolVLA docs](https://huggingface.co/docs/lerobot/smolvla)). The model is about 450M parameters, so it does not need more than one GPU. The docs give no VRAM minimum; batch 64 is comfortable on 40 to 80 GB. On a 24 GB card (RTX 3090/4090, A10G, L4), expect to drop to batch 16 to 32 (estimate, not tested on our data).

## Options and prices (on-demand, per GPU-hour, USD)

| Provider | GPU | $/hour | Est. hours for 20k steps | Est. cost per full run | Notes |
|---|---|---|---|---|---|
| Vast.ai (marketplace) | A100 SXM4 80GB | 0.80 median (0.40 to 1.55) | ~4 | **~$3** | Cheapest A100s; hosts vary in reliability. Interruptible instances are cheaper still. |
| Vast.ai | RTX 4090 24GB | 0.43 median (0.14 to 0.54) | ~6 to 8 (est.) | ~$3 | Smaller batch needed. |
| RunPod Community Cloud | A100 80GB | 1.19 (PCIe) to 1.39 (SXM) | ~4 | **~$5 to $6** | Easiest setup; no ingress/egress fees. Often out of stock, check availability. |
| RunPod Community Cloud | RTX 4090 24GB | 0.34 | ~6 to 8 (est.) | ~$2 to $3 | Cheapest overall option. |
| RunPod Community Cloud | L40S 48GB | 0.79 | ~5 (est.) | ~$4 | Fits batch 64; good fallback when A100s are gone. |
| RunPod Secure Cloud | A100 80GB | 1.79 | ~4 | ~$7 | More reliable datacenter hosts. |
| RunPod | H100 80GB | 2.69 (SXM, Community) | ~2.5 (est.) | ~$7 | Faster, not cheaper. |
| Lambda | A100 40GB | 1.99 | ~4 | ~$8 | Simple VMs, no egress fees; prices from table effective 2026-11-16. |
| Lambda | A100 80GB | 3.19 | ~4 | ~$13 | |
| AWS g5.xlarge (us-east-1) | A10G 24GB | 1.01 on-demand, 0.51 spot | ~10 (est.) | ~$5 spot / ~$10 on-demand | Only 4 vCPU / 16 GB RAM on xlarge; use g5.2xlarge or larger for 8 vCPU. Needs GPU quota request. |
| AWS g6.xlarge (us-east-1) | L4 24GB | 0.80 on-demand, 0.60 spot | ~10 (est.) | ~$6 spot | Same quota caveat. |
| GCP a2-highgpu-1g (us-central1) | A100 40GB | 3.67 on-demand, 2.09 spot | ~4 | ~$8 spot / ~$15 on-demand | Spot can be pre-empted; save checkpoints often. |
| GCP g2-standard-8 | L4 24GB | 0.85 on-demand, 0.51 spot | ~10 (est.) | ~$5 spot | |
| Colab Enterprise | A100 40GB | 3.52 | ~4 | ~$14 | Notebook-only; consumer Colab Pro prices were not available to check. HF has a SmolVLA Colab notebook. |

"Est." run times for non-A100 cards are my estimates from relative GPU speed, not measurements. Run the 200-step test first and multiply its time per step by 20,000 to get the real number for a given card.

Extra costs are small: RunPod storage is $0.10/GB/month while running ($0.20 idle), so a 50 GB volume is about $5/month if you keep it; delete it after copying checkpoints. Lambda and RunPod charge no egress.

## Why $0.0X per hour isn't realistic

No provider rents an A100-class or 24 GB GPU for a few cents an hour. The floor today is roughly $0.14 to $0.22 per hour for the cheapest consumer cards on marketplaces, and those are interruptible or low-reliability hosts. What *is* cheap is the run: at about 4 hours, a full fine-tune costs a few dollars, and each training step costs a fraction of a cent.

## How a cloud run would look (RunPod or Vast.ai)

1. Rent 1x A100 80GB with a PyTorch/CUDA template and a 50 GB volume.
2. `pip install "lerobot[smolvla,training]==0.6.1"`, then `hf download lerobot/smolvla_base` (cloud pods have internet, so `HF_HUB_OFFLINE` is not needed).
3. Copy the dataset up: `rsync -av data/pick_cup root@<pod>:/workspace/data/` (or push it to a private HF dataset).
4. Run the same `lerobot-train` command as `training/athena/train_neil.job`, with `STEPS=200 BATCH=8` first, then 20000 / 64.
5. Copy `outputs/.../checkpoints/last/pretrained_model` back to the Mac and **stop the pod** (billing runs until you stop it).

## Sources

- [joulemath: GPU rental prices, Oct 21 2026 (updated Nov 3)](https://joulemath.com/blog/gpu-rental-prices-h100-h200-a100-rtx-4090-october-2026/) for Vast.ai medians and RunPod tiers
- [computeprices.com: RunPod prices (collected 2026-11-09)](https://computeprices.com/providers/runpod)
- [RunPod cloud GPUs](https://www.runpod.io/product/cloud-gpus) for Secure Cloud prices and storage fees
- [Lambda pricing](https://lambda.com/pricing)
- [Vantage: AWS g5.xlarge](https://instances.vantage.sh/aws/ec2/g5.xlarge), [g6.xlarge](https://instances.vantage.sh/aws/ec2/g6.xlarge)
- [GCP accelerator-optimized VM pricing](https://cloud.google.com/products/compute/pricing/accelerator-optimized)
- [Colab Enterprise pricing](https://cloud.google.com/colab/pricing)
- [LeRobot SmolVLA docs](https://huggingface.co/docs/lerobot/smolvla)
