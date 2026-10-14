"""Judge a recorded attempt (teleop session, policy rollout or converted episode) with a VLM.

An attempt is loaded from either layout the project produces:
    logs/session_*/ or logs/run_*/   pi/ external/ steps.jsonl info.json [policy.json]
    episodes/<action>/ep_*/          episode.json frames.jsonl front.mp4 top.mp4

Frames are sampled evenly over the attempt from both cameras (always including the last one),
sent to Claude with the arm/gripper encoder trace, and the answer comes back as a fixed JSON verdict.
"""
from __future__ import annotations

import base64
import json
from dataclasses import dataclass, field
from pathlib import Path

import cv2
import numpy as np

DEFAULT_MODEL = "claude-opus-5-5"

# Kept short and fixed so the summary can count them. "none" is only for successes.
FAILURE_CATEGORIES = {
    "none": "the attempt succeeded",
    "did_not_reach_cup": "the robot never got the gripper to the cup",
    "misaligned_approach": "reached the cup but the jaws were not around it (off to one side, too high/low)",
    "pushed_cup_away": "the robot shoved the cup out of reach while approaching",
    "knocked_over_cup": "the cup tipped over",
    "gripper_not_closed": "the cup was between the jaws but the gripper never closed on it",
    "grasp_missed": "the gripper closed but did not catch the cup",
    "grasp_slipped": "the cup was held, then slipped or dropped",
    "stopped_early": "the attempt ended (or the robot stalled) before the task could finish",
    "view_unclear": "the cameras do not show enough to judge",
    "other": "a failure that fits none of the above (explain in reason)",
}

VERDICT_SCHEMA = {
    "type": "object",
    "properties": {
        "success": {"type": "boolean"},
        "confidence": {"type": "number", "description": "0 to 1"},
        "failure_category": {"type": "string", "enum": list(FAILURE_CATEGORIES)},
        "reason": {"type": "string", "description": "one or two sentences citing what the frames show"},
        "cup_final_state": {
            "type": "string",
            "enum": ["held_lifted", "held_on_table", "upright_free", "knocked_over", "out_of_view"],
        },
        "key_frame_s": {"type": "number", "description": "time in seconds of the frame that decided the verdict"},
    },
    "required": ["success", "confidence", "failure_category", "reason", "cup_final_state", "key_frame_s"],
    "additionalProperties": False,
}

SYSTEM = """You judge recorded attempts of a small LEGO robot (two drive wheels, an arm with a two-jaw gripper at the front) at a task such as "pick up the cup".

You get frames sampled evenly through the attempt, in time order, from two cameras:
- top: a fixed overhead camera looking down at the table, robot and cup.
- front: the robot's own camera, low on the robot and facing forward; when the cup is in the gripper it fills this view and the magenta gripper parts show at the bottom.
The last frames are the end of the attempt, so they decide the outcome. You also get the arm and gripper encoder readings.

Success for "pick up the cup" means that at the end the cup is held between the closed gripper jaws and stays there. Whether the arm also raised it off the table goes in cup_final_state (held_lifted or held_on_table), not in the success verdict.

If it failed, pick the single failure category that best explains why, the earliest thing that went wrong:
""" + "\n".join(f"- {k}: {v}" for k, v in FAILURE_CATEGORIES.items()) + """

Base the verdict on what is visible; do not assume an outcome the frames do not show. Confidence is your probability that the success verdict is right. Keep the reason short and specific (what happened and at which time)."""


@dataclass
class Attempt:
    path: Path
    kind: str                      # "session", "rollout" or "episode"
    task: str
    fps: float
    n_steps: int
    frames: dict = field(default_factory=dict)   # camera -> callable(i) -> BGR image
    arm: list = field(default_factory=list)      # per step, degrees (+ down)
    grip: list = field(default_factory=list)     # per step, degrees (+ open)
    label: bool | None = None      # recorded ground truth, if the episode has one

    @property
    def duration_s(self) -> float:
        return self.n_steps / self.fps if self.fps else 0.0


def find_attempts(root: Path) -> list[Path]:
    """Every attempt directory at or under root."""
    root = Path(root)
    if is_attempt(root):
        return [root]
    return sorted(p.parent for p in root.rglob("*") if p.name in ("steps.jsonl", "episode.json") and is_attempt(p.parent))


def is_attempt(d: Path) -> bool:
    return (d / "steps.jsonl").is_file() or ((d / "episode.json").is_file() and (d / "frames.jsonl").is_file())


def load_attempt(d: Path, task: str | None = None) -> Attempt:
    d = Path(d)
    return _load_episode(d, task) if (d / "episode.json").is_file() else _load_session(d, task)


def _read_jsonl(p: Path) -> list[dict]:
    return [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines() if l.strip()]


def _load_session(d: Path, task: str | None) -> Attempt:
    rows = _read_jsonl(d / "steps.jsonl")
    info = json.loads((d / "info.json").read_text()) if (d / "info.json").is_file() else {}
    policy = json.loads((d / "policy.json").read_text()) if (d / "policy.json").is_file() else None
    task = task or (policy or {}).get("task") or "pick up the cup"
    a = Attempt(d, "rollout" if policy is not None else "session", task, float(info.get("fps") or 10), len(rows))
    for cam, name in (("external", "top"), ("pi", "front")):
        files = [(r.get(cam) or {}).get("file") for r in rows]
        if any(files):
            a.frames[name] = lambda i, files=files: _imread(d, files, i)
    for r in rows:
        m = r.get("motors") or {}
        # Raw encoder degrees are flipped relative to the converted episodes' convention (+ down / + open).
        a.arm.append(_neg((m.get("arm") or {}).get("pos_deg")))
        a.grip.append(_neg((m.get("gripper") or {}).get("pos_deg")))
    return a


def _load_episode(d: Path, task: str | None) -> Attempt:
    meta = json.loads((d / "episode.json").read_text())
    rows = _read_jsonl(d / "frames.jsonl")
    a = Attempt(d, "episode", task or meta.get("task") or "pick up the cup", float(meta.get("fps") or 10), len(rows),
                label=meta.get("success"))
    for video, name in (("top.mp4", "top"), ("front.mp4", "front")):
        if (d / video).is_file():
            a.frames[name] = lambda i, v=d / video: _video_frame(v, i)
    for r in rows:
        s = r.get("state") or {}
        a.arm.append(s.get("arm_pos"))
        a.grip.append(s.get("grip_pos"))
    return a


def _neg(v):
    return -v if isinstance(v, (int, float)) else None


def _imread(d: Path, files: list, i: int):
    # Fall back to the nearest earlier step that saved a frame.
    for j in range(i, -1, -1):
        if files[j] and (d / files[j]).is_file():
            return cv2.imread(str(d / files[j]))
    return None


def _video_frame(path: Path, i: int):
    cap = cv2.VideoCapture(str(path))
    cap.set(cv2.CAP_PROP_POS_FRAMES, i)
    ok, img = cap.read()
    cap.release()
    return img if ok else None


def sample_indices(n_steps: int, n: int) -> list[int]:
    """n step indices spread evenly from the first to the last step."""
    if n_steps <= n:
        return list(range(n_steps))
    return sorted({round(x) for x in np.linspace(0, n_steps - 1, n)})


def _jpeg_b64(img, max_w: int) -> str:
    h, w = img.shape[:2]
    if w > max_w:
        img = cv2.resize(img, (max_w, round(h * max_w / w)), interpolation=cv2.INTER_AREA)
    ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 85])
    return base64.standard_b64encode(buf.tobytes()).decode()


def build_content(a: Attempt, n_frames: int = 8, max_w: int = 640) -> list[dict]:
    """The user turn: task, encoder trace, then each sampled moment with its camera frames."""
    idx = sample_indices(a.n_steps, n_frames)
    trace = "\n".join(
        f"  t={i / a.fps:5.1f}s  arm={_fmt(a.arm[i])}  gripper={_fmt(a.grip[i])}" for i in idx if i < len(a.arm)
    )
    content = [{"type": "text", "text": (
        f'Task: "{a.task}"\nAttempt: {a.duration_s:.1f} s, {a.n_steps} steps at {a.fps:g} fps.\n'
        f"Arm and gripper encoder degrees (arm + = lowered, gripper + = opened) at the sampled frames:\n{trace}\n"
        f"Final: arm={_fmt(_last(a.arm))} gripper={_fmt(_last(a.grip))}\n\nFrames follow in time order."
    )}]
    for i in idx:
        for cam, get in a.frames.items():
            img = get(i)
            if img is None:
                continue
            last = " (last frame)" if i == a.n_steps - 1 else ""
            content.append({"type": "text", "text": f"t={i / a.fps:.1f}s {cam} camera{last}:"})
            content.append({"type": "image", "source": {"type": "base64", "media_type": "image/jpeg",
                                                        "data": _jpeg_b64(img, max_w)}})
    content.append({"type": "text", "text": f'Did this attempt succeed at "{a.task}"? Answer with the JSON verdict.'})
    return content


def _fmt(v):
    return "n/a" if v is None else f"{v:g}"


def _last(xs):
    return next((x for x in reversed(xs) if x is not None), None)


def classify(client, a: Attempt, model: str = DEFAULT_MODEL, effort: str = "medium",
             n_frames: int = 8, max_w: int = 640) -> dict:
    """Ask Claude for a verdict on one attempt. Returns the verdict plus usage bookkeeping."""
    response = client.beta.messages.create(
        model=model,
        max_tokens=16000,
        system=SYSTEM,
        messages=[{"role": "user", "content": build_content(a, n_frames, max_w)}],
        output_config={"effort": effort, "format": {"type": "json_schema", "schema": VERDICT_SCHEMA}},
        # If a safety classifier ever declines a frame set, Anthropic re-runs it on its recommended fallback model.
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",
    )
    if response.stop_reason == "refusal":
        raise RuntimeError(f"model declined: {getattr(response.stop_details, 'category', None)}")
    text = next(b.text for b in response.content if b.type == "text")
    verdict = json.loads(text)
    verdict["model"] = response.model
    verdict["usage"] = {"input_tokens": response.usage.input_tokens, "output_tokens": response.usage.output_tokens}
    return verdict
