# Run the Pick-Cup Model on Neil

This guide lets a teammate run the trained model on Neil. The model looks at both cameras and the motor readings, and it drives Neil to pick up the cup.

> [!IMPORTANT]
> The model has never driven Neil before. Stay next to Neil for the first runs, and keep one hand ready to lift it. Press Ctrl+C in the terminal to stop it.

## 1. What is in this folder

| Item | What it is |
|---|---|
| `model/` | The trained model (7 files, about 900 MB). Training: 50 episodes, 10,000 steps, job 181436. Not in GitHub, because it is too large. Step 2.6 copies it from Athena. |
| `run_policy.py` | Drives Neil with the model. Runs on the laptop. |
| `neil_io.py` | Connects the laptop to Neil's motors and both cameras. Used by `run_policy.py`. |
| `run_video.py` | Saves a video of each run, for people to watch. Used by `run_policy.py`. |
| `pi_bridge.py` | Runs on Neil's Raspberry Pi. Moves the motors and sends the motor readings. |
| `check_model.py` | Tests the model on recorded frames, with no robot. |
| `data/pick_cup/` | The training data (94 MB). Only `check_model.py` needs it. Not in GitHub. Step 2.7 copies it from Athena. |
| `runs/` | Your runs, one folder for each run: what the model saw and did at each step, and the videos. Made by `run_policy.py`. Not in GitHub. |

## 2. Install Python (once)

Do this on the laptop that will run the model. A Mac with Apple M1 or newer, or a laptop with an NVIDIA GPU, works.

1. Install `uv`, a fast Python installer, if you do not have it:
   ```bash
   curl -LsSf https://astral.sh/uv/install.sh | sh
   ```
2. Go to this folder. Put the real path in place of `xxx`:
   ```bash
   cd xxx/inference_kit
   ```
3. Make a Python environment. Why: it keeps these packages apart from other projects.
   ```bash
   uv venv --python 3.12
   ```
4. Install LeRobot with SmolVLA. Use exactly this version, because the model was trained with it.
   ```bash
   uv pip install "lerobot[smolvla,dataset]==0.6.1"
   ```
5. Start the environment. Do this again in every new terminal window.
   ```bash
   source .venv/bin/activate
   ```
6. If the `model/` folder is missing, copy it from Athena. This needs the Technion network and an Athena account in the `belinkov_prj` group. Run the 2 lines one at a time, and put your Athena username in place of `your.name`:
   ```bash
   M=/rg/belinkov_prj/qiu.qiqian/vla/outputs/neil_181436/checkpoints/last
   ```
   ```bash
   rsync -avP your.name@athena.technion.ac.il:$M/pretrained_model/ model/
   ```
7. Optional, for step 3 only: copy the training data the same way.
   ```bash
   D=/rg/belinkov_prj/qiu.qiqian/vla/data/pick_cup
   ```
   ```bash
   rsync -avP your.name@athena.technion.ac.il:$D data/
   ```

## 3. Check the laptop (no robot needed)

```bash
python check_model.py --policy model
```

Why: it shows that the model loads, and how fast this laptop is.

Good result:
- The "model action" column is close to the "recorded action" column.
- The median time is under 100 ms.
- About every 50 frames, one frame takes 1 to 2 seconds. That is normal: the model plans the next 50 commands at once.

The first run downloads small SmolVLA helper files, so it needs internet once.

## 4. Prepare Neil

1. Connect the laptop to the same network as Neil and the iPhone.
2. Stop every other program that uses the robot: the team's recorder, the gamepad controller, and Neil's MCP server. Why: only one program can use the motors and the Pi camera at a time.
3. Check that you can log in to the Pi without a password. The recordings used the Pi address `132.68.34.107`. Check that it did not change.
   ```bash
   ssh rpi@132.68.34.107 echo ok
   ```
   If it asks for a password, run `ssh-copy-id rpi@132.68.34.107` once.
4. Copy the motor program to the Pi:
   ```bash
   scp pi_bridge.py rpi@132.68.34.107:~/
   ```
5. Tell the laptop where Neil and the iPhone are. The recordings used the iPhone address `132.68.34.85`. Run these 3 lines in the terminal where you will start the model:
   ```bash
   export NEIL_PI=rpi@132.68.34.107
   ```
   ```bash
   export NEIL_FRONT_URL=http://132.68.34.107:8765/
   ```
   ```bash
   export NEIL_TOP_URL=http://132.68.34.85:8080/stream.mjpg
   ```

## 5. Set up the scene like the recordings

The model only knows what it saw in the 50 recordings. So the scene must look the same.

1. Use the same table and the same light.
2. Keep the iPhone in the same place above the table, upright, as in the recordings.
3. Put a paper cup at one of the 5 recorded positions.
4. Put Neil in its start pose: arm at its normal low start height, gripper open.

## 6. Run the model

```bash
python run_policy.py --policy model --seconds 30
```

1. At the start, the program prints `Start state (left, right, arm, grip)`. In the recordings, the arm started between -5 and 8, and the gripper between -8 and -14. If the numbers are very different, press Ctrl+C, put Neil in the start pose, and start again.
2. While it runs, the last command is shown: left wheel, right wheel, arm target, gripper target.
3. About every 5 seconds, Neil stops for 1 to 2 seconds. That is normal: the model plans the next commands. A faster laptop makes this pause shorter.
4. To stop at any time, press Ctrl+C. The wheels stop, and the arm and gripper hold their position.
5. At the end, the program prints where it saved the video of the run, for example `runs/run_20261020_101500/side_by_side.mp4`. It shows both cameras side by side. `front.mp4` and `top.mp4` in the same folder show one camera each.
   The video has 30 frames per second, but the model still works at 10, like the recordings. Why: people watch the video, and 10 frames per second looks jerky. For no video, add `--video-fps 0`.

> [!WARNING]
> If Neil drives the wrong way, or the gripper opens when it should close, press Ctrl+C. Then tell the team which motor did it. The motor directions are set at the top of `pi_bridge.py`.

## 7. If the front camera looks different

The model learned from front images in one orientation. Before the first run, open `http://132.68.34.107:8765/` in a browser while `run_policy.py` runs, and compare it with a recorded image, for example `pi/000000.jpg` in any session folder. If the live image is upside down or mirrored, tell the team before you continue. Close the browser tab afterwards, because the camera stream serves one viewer at a time.
