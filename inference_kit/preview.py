"""Start pi_bridge.py, save one frame from each camera and print the start state. Nothing moves:
the wheels get speed 0 and the arm and gripper hold where they are.

    python preview.py      -> preview_front.jpg, preview_top.jpg next to this file
Compare them with camera1 / camera2 frames of the training videos before running the model.
"""
import cv2

from neil_io import Bridge, open_cameras, state_vector

bridge = Bridge()
try:
    front, top = open_cameras()
    print("Start state (left, right, arm, grip):", state_vector(bridge.hold()).tolist())
    print("Recorded starts: arm -5..8, grip -67..-8 (median -19)")
    for name, cam in (("front", front), ("top", top)):
        img = cam.read()
        cv2.imwrite(f"preview_{name}.jpg", cv2.cvtColor(img, cv2.COLOR_RGB2BGR))
        print(f"preview_{name}.jpg {img.shape[1]}x{img.shape[0]}")
finally:
    bridge.stop()
