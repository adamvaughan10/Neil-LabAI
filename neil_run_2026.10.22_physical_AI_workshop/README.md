# Neil run, 2026.10.22: Physical AI workshop

SmolVLA on Neil, new task "pick up the green cup": everything from the workshop day. We recorded the demos,
turned them into a LeRobot dataset, trained a cold and a warm model on Athena, and ran the models on Neil.
Results and explanations: `result_run_physical_AI_WS.ipynb` (`result_run_physical_AI_WS.html` is the same notebook
with its outputs, so you can open it in a browser).

The videos and camera frames (`*.mp4`, `*.jpg`) are stored with Git LFS. Run `git lfs install` before cloning, or
`git lfs pull` after.

| Folder | What | Made by |
|---|---|---|
| `1_raw_demos_2026.10.22_green_cup` | The 50 recorded demos (gamepad teleop, 10 Hz): per demo `pi/` and `external/` JPEGs, `steps.jsonl` (motors, gamepad target, buttons), `info.json`, and MP4 previews. `session_20261022_124142` was not used for training (Neil never moved). | the recorder (`logs/session_*`) |
| `1b_dataset_2026.10.22_green_cup` | The 49 used demos turned into a LeRobot dataset: 5128 frames, 2 cameras as AV1 videos, 4 state values, 4 action values, task "pick up the green cup". | `training/convert_episodes.py` |
| `2_warm_start_weights` | Warm run (Athena job 267613, started from pos2, 5000 batches). `warm_batch1000_chosen`: lowest `eval_loss` of the saved checkpoints (0.901), the one tested on Neil. `warm_batch5000_final`: the last one (`eval_loss` 1.037). | `training/athena/train_v2.job` |
| `3_cold_start_weights` | Cold run (Athena job 267612, started from `lerobot/smolvla_base`, 10000 batches). `cold_batch2000_chosen`: lowest `eval_loss` of the saved checkpoints (0.934). `cold_batch10000_final`: the last one (`eval_loss` 1.441). | `training/athena/train_v2.job` |
| `4_inference_2026.10.22` | Videos of all 10 times a model ran on Neil that day, one folder per run, named by number, time, weights, mode and outcome. Its README has the table. | the control panel (`logs/gui_run_20261022_*`) |
| `result_run_physical_AI_WS.ipynb` / `.html` | The results notebook: data, training curves, cold vs warm, inference runs, the chosen weights. | |

## The weights are not in git

Each `model.safetensors` is 900 MB, so the weight folders here hold only the small files: `config.json`,
`train_config.json`, and the pre/post-processor files with the normalizer stats. The full checkpoints are on Athena:

- warm: `/rg/belinkov_prj/qiu.qiqian/vla/outputs/lina_green_cup_warm_267613/checkpoints/<step>/pretrained_model`
- cold: `/rg/belinkov_prj/qiu.qiqian/vla/outputs/lina_green_cup_cold_267612/checkpoints/<step>/pretrained_model`

To use one, put its `model.safetensors` into the matching folder here. A complete `pretrained_model` folder (7 files)
loads with LeRobot 0.6.1, or serves with `policy_server/server.py --checkpoint <folder>` (on a GPU:
`training/athena/serve_policy.job <folder>`). Run it with the task "pick up the green cup" and the spec
`specs/green_cup_warm.json` (warm) or `specs/green_cup_cold.json` (cold). The two specs differ only in
`action_range`, which is each model's own training min/max.
