# Inference Guide: Run the Trained Model on Neil

Inference means that the trained model drives Neil live. It runs on a laptop next to Neil, not on Athena. Athena only trains the model.

The laptop repeats one loop 15 times each second:
1. Read the 2 camera images and the motor state from Neil.
2. Give them and the sentence "pick up the cup" to the model.
3. Send the model's motor command to Neil.

In the commands below, replace `your.name` with your own Athena username.

> [!IMPORTANT]
> The live input must look like the training data: the same camera positions, the same image orientation, and the same task sentence, "pick up the cup". If one of these is different, the model can fail.

---

## What you need

| Need | Why |
|---|---|
| A good laptop: Apple M1 or newer, or a laptop with an NVIDIA GPU | The model needs a GPU. An Apple M1 with 8 GB works, but Neil pauses about 1 s every 3 s. |
| An Athena account in the `belinkov_prj` group | To copy the code and the trained model |
| The Technion network or VPN (for Part A) | Athena works only from the Technion network |
| The Pi password (ask Michael), once | To let your laptop control Neil's motors |

---

## Part A: Prepare the laptop (once, with internet)

Do Part A with internet, before you join Neil's Wi-Fi. Neil's Wi-Fi has no internet.

1. Install uv, a fast Python installer. Then close Terminal and open a new one:
   ```bash
   curl -LsSf https://astral.sh/uv/install.sh | sh
   ```
2. Copy the code from Athena to your laptop:
   ```bash
   rsync -av your.name@athena.technion.ac.il:/rg/belinkov_prj/qiu.qiqian/vla/code/ ~/neil-vla/
   ```
3. Make the Python environment (5 to 10 minutes). Paste the whole block at once:
   ```bash
   cd ~/neil-vla
   uv venv -p 3.12 .venv
   source .venv/bin/activate
   uv pip install "lerobot[smolvla,dataset]==0.6.1"
   ```
   Use exactly version 0.6.1. Athena trains with this version, and another version may not load the model.
4. Copy the trained model from Athena. Ask the team for the job number (JOBID) of the final training:
   ```bash
   rsync -avP your.name@athena.technion.ac.il:/rg/belinkov_prj/qiu.qiqian/vla/outputs/neil_JOBID/checkpoints/last/pretrained_model ~/neil-vla/models/pick_cup/
   ```
   The model folder is about 900 MB.
5. Load the model once. This downloads the SmolVLA base files (about 2 GB) that the model needs. Paste the whole block at once:
   ```bash
   cd ~/neil-vla
   source .venv/bin/activate
   python -c "from lerobot.policies.smolvla.modeling_smolvla import SmolVLAPolicy; SmolVLAPolicy.from_pretrained('models/pick_cup/pretrained_model'); print('MODEL OK')"
   ```
   The result must end with `MODEL OK`.

---

## Part B: Connect to Neil (once, on Neil's Wi-Fi)

1. Join Neil's Wi-Fi. The addresses start with `192.168.8.`.
2. Copy your SSH key to the Pi. Type the Pi password once:
   ```bash
   ssh-copy-id rpi@rpi.local
   ```
   If it says that you have no key, run `ssh-keygen -t ed25519` first and press Enter at every question.
3. Test. It must print `ok` with no password:
   ```bash
   ssh rpi@rpi.local echo ok
   ```
4. Copy the motor program to the Pi:
   ```bash
   scp ~/neil-vla/pi_bridge.py rpi@rpi.local:~/
   ```

---

## Part C: Run the model

1. Stop all other programs that use Neil's motors or the iPhone camera (for example, the recorder or the MCP server). The iPhone camera accepts only one viewer at a time.
2. Put Neil on its start mark. Put the cup in front of it, in a place like in the recordings.
3. Keep one hand on the keyboard. Ctrl+C stops Neil at any time.
4. Run. Paste the whole block at once:
   ```bash
   cd ~/neil-vla
   source .venv/bin/activate
   HF_HUB_OFFLINE=1 python run_policy.py --policy models/pick_cup/pretrained_model --task "pick up the cup" --seconds 30
   ```
   `HF_HUB_OFFLINE=1` stops the laptop from looking for the internet, which Neil's Wi-Fi does not have.
5. Wait about 25 s before Neil moves. The model loads (15 s) and warms up (10 s).

> [!NOTE]
> On a laptop with an NVIDIA GPU, add `--device cuda` to the command in step 4.

---

## Problems and fixes

| Problem | Fix |
|---|---|
| `rsync` or `ssh` to Athena waits and fails | Connect to the Technion network or VPN |
| An error that says it cannot connect to `huggingface.co` | Do Part A step 5 again, with internet |
| `rpi.local` not found | Ask Michael for the Pi IP address. Run `export NEIL_PI=rpi@<IP>` before step 4. |
| No image from the iPhone camera | Close all other viewers of the iPhone stream. Check the address in `neil_io.py` (`TOP_URL`). |
| Neil moves in a strange way | Press Ctrl+C. Check that the cameras are in the same places as in the recordings. |
