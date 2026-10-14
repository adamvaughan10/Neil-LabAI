"""
Turn one recorder step into the observation a VLA policy gets.

    spec = ObservationSpec.load("policy_spec.json")    # or ObservationSpec.default()
    obs = spec.build(row, files)                        # row/files from SyncRecorder's on_step

The spec is the single place that says how our recordings map to the policy's
inputs, so it must match the LeRobot dataset the policy was trained on:

    {
      "task": "pick up the cup",
      "images": {"observation.images.pi":       {"camera": "pi",       "rotation": 0},
                 "observation.images.external": {"camera": "external", "rotation": 0}},
      "state":  ["left_wheel.pos_deg", "right_wheel.pos_deg", "gripper.pos_deg", "arm.pos_deg"],
      "action": ["left_wheel.pos_deg", "right_wheel.pos_deg", "gripper.pos_deg", "arm.pos_deg"]
    }

"images" maps each policy image key to a camera in the recording. "rotation" is
applied by the policy server after decoding (clockwise degrees), because the
recorder stores each camera's JPEGs exactly as sent. "state" and "action" name
motor fields from the step's "motors" entry as "<role>.<field>"; "action" only
labels the policy's output dimensions in the logs. A state entry "const:<number>"
sends that fixed number, e.g. to pad the state for a policy trained on another robot.
A leading "-" negates a motor value ("-left_wheel.speed"), to apply the mounting sign
flips that session_to_episode.py applies when it makes the training data.
A trailing "+<number>" or "-<number>" adds that number after the sign is applied:
"-arm.abs_pos_deg+14" is -(abs_pos_deg - 14).

"action_mode" says how the GUI turns the policy's 4 action values into motor commands:
"v1" (default) = wheel speeds and arm/gripper target angles; "delta" = wheel degrees still
to turn and arm/gripper targets on the abs_pos_deg scale (models/handoff_pick_cup_pos2).
"action_range" ([min list, max list]) clips each action value to its training range,
"start_pose" ([arm, grip], robot terms) is where a drive run's warm-up puts the arm and
gripper, and "checkpoint" names the model the spec is for (the page picks it with that model).

Images go out as the camera's own JPEG bytes: nothing is decoded or re-encoded here.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from neil_robot import config


_STATE_ENTRY = re.compile(r"(?P<neg>-)?(?P<role>\w+)\.(?P<field>\w+)(?P<offset>[+-]\d+(?:\.\d+)?)?")


class ObservationError(ValueError):
    """The step lacks something the policy needs (a camera image, a motor reading)."""


@dataclass
class ObservationSpec:
    task: str
    images: dict[str, dict]           # policy key -> {"camera": name, "rotation": deg}
    state: list[str]                  # "<role>.<field>" per state dimension
    action: list[str] = field(default_factory=list)
    action_mode: str = "v1"
    action_range: list | None = None    # [mins, maxes] of the training actions
    start_pose: list | None = None      # [arm, grip] for the warm-up, robot terms
    checkpoint: str | None = None

    @classmethod
    def default(cls) -> "ObservationSpec":
        """Both cameras and the four motor positions. A placeholder until it is checked
        against the training dataset's meta/info.json."""
        motors = [f"{r}.pos_deg" for r in ("left_wheel", "right_wheel", "gripper", "arm")]
        return cls(
            task="pick up the cup",
            images={"observation.images.pi": {"camera": "pi", "rotation": 0},
                    "observation.images.external": {"camera": "external",
                                                    "rotation": config.EXTERNAL_CAMERA_ROTATION}},
            state=motors,
            action=list(motors),
        )

    @classmethod
    def load(cls, path) -> "ObservationSpec":
        d = json.loads(Path(path).read_text(encoding="utf-8"))
        return cls(task=d["task"], images=d["images"], state=d["state"], action=d.get("action", []),
                   action_mode=d.get("action_mode", "v1"), action_range=d.get("action_range"),
                   start_pose=d.get("start_pose"), checkpoint=d.get("checkpoint"))

    def to_dict(self) -> dict:
        return {"task": self.task, "images": self.images, "state": self.state, "action": self.action,
                "action_mode": self.action_mode, "action_range": self.action_range,
                "start_pose": self.start_pose, "checkpoint": self.checkpoint}

    @property
    def cameras(self) -> set[str]:
        return {v["camera"] for v in self.images.values()}

    def build(self, row: dict, files: dict[str, bytes], task: str | None = None) -> dict:
        """The observation for one recorder step. Raises ObservationError if anything is missing."""
        images = {}
        for key, src in self.images.items():
            cam = row.get(src["camera"])
            if not cam or cam["file"] not in files:
                raise ObservationError(f"no image from camera {src['camera']!r}")
            images[key] = {"jpeg": files[cam["file"]], "rotation": src.get("rotation", 0)}
        motors = row.get("motors")
        if not motors or "error" in motors:
            raise ObservationError(f"no motor reading ({(motors or {}).get('error', 'missing')})")
        state = []
        for name in self.state:
            if name.startswith("const:"):
                state.append(float(name[6:]))
                continue
            m = _STATE_ENTRY.fullmatch(name)
            if not m:
                raise ObservationError(f"bad state entry {name!r}")
            sign = -1.0 if m["neg"] else 1.0
            value = (motors.get(m["role"]) or {}).get(m["field"])
            if value is None:
                raise ObservationError(f"no motor value {name!r}")
            state.append(sign * float(value) + float(m["offset"] or 0))
        return {
            "step": row["step"], "t": row["t"], "task": task or self.task,
            "images": images, "state": state, "state_names": list(self.state),
            # How stale each input was at the tick, for the logs and for latency checks.
            "age_ms": {**{src["camera"]: row[src["camera"]]["age_ms"] for src in self.images.values()},
                       "motors": motors.get("age_ms")},
        }
