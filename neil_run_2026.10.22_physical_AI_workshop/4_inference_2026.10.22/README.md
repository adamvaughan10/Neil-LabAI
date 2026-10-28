# Inference runs on Neil, 2026.10.22

Every time a model ran on Neil today, through the control panel. Each folder has 3 videos at 30 frames per second
(the model itself works at 10 steps per second): `combined.mp4` (both cameras side by side), `pi.mp4` (Neil's camera),
`external.mp4` (the phone above the table). The full recordings (every frame, motor readings, the model's actions and
commands) are in `logs/gui_run_20261022_<time>/` on the lab laptop (not in git).

- **drive:** the model's commands were sent to the motors. **dry run:** the model planned, nothing was sent.
- **laptop-CPU:** the model ran on the laptop's processor. One plan took more than 30 s, so the panel gave up waiting
  and **the model never sent a command**; the only movement is the panel moving the arm and gripper to the start pose.
- **GPU:** the model ran on an Athena GPU (about 130 to 280 ms per plan).
- Every drive run lasted 20 to 30 s.

| # | Time | Weights | Task sentence | Mode | Outcome |
|---|---|---|---|---|---|
| 01 | 14:20 | pos2 (job 181719) | pick up the cup | drive, laptop CPU | no model output (timed out) |
| 02 | 14:21 | pos2 | pick up the cup | dry run, laptop CPU | no model output (timed out) |
| 03 | 14:23 | pos2 | pick up the cup | drive, laptop CPU | no model output |
| 04 | 14:29 | pos2 | pick up the cup | dry run, GPU | 3 plans, nothing moved by the model |
| 05 | 14:30 | pos2 | pick up the cup | drive, GPU | cup already within reach: closed the gripper on it and lifted it |
| 06 | 14:33 | pos2 | pick up the cup | drive, GPU | cup within reach: grabbed, lifted, put down, grabbed and lifted again |
| 07 | 14:35 | warm, batch 1000 (job 267613) | pick up the green cup | dry run, GPU | 2 plans, nothing moved by the model |
| 08 | 14:36 | warm, batch 1000 | pick up the green cup | drive, GPU | drove to the cup, closed the gripper on it, lifted it |
| 09 | 14:38 | warm, batch 1000 | pick up the green cup | drive, GPU | cup further away and to the side: drove, then turned away; missed |
| 10 | 14:39 | warm, batch 1000 | pick up the green cup | drive, GPU | drove to the cup, gripped it and carried it |

The cold models were not tested on Neil.
