# Inference Guide: Run the Trained Model on Neil

This guide moved to [`inference_kit/INFERENCE.md`](inference_kit/INFERENCE.md).

The old version told you to copy the code from Athena (`/vla/code/`). That code is out of date: it ran at 15 frames per second and sent speeds to the arm and gripper. The trained `pick_cup` model (job 181436) was trained at 10 frames per second, with target angles for the arm and gripper. The code in `inference_kit/` matches the model.
