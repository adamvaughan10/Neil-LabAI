"""
Runs ON THE PI. neil_robot/dashboard.py sends this file over SSH and starts it when
no camera server is already running. The hardware MJPEG encoder hands over one JPEG
per frame and each goes out as one line: jpeg <base64>. Prints "ready" first.
When stdin closes (the laptop quit, or SSH dropped) it frees the camera and exits.
"""
import base64
import io
import json
import sys

from libcamera import Transform
from picamera2 import Picamera2
from picamera2.encoders import MJPEGEncoder
from picamera2.outputs import FileOutput

settings = json.loads(sys.argv[1])


class Frames(io.BufferedIOBase):
    def writable(self):
        return True

    def write(self, buf):
        print("jpeg " + base64.b64encode(bytes(buf)).decode(), flush=True)
        return len(buf)


cam = Picamera2()
try:
    flip = settings["rotation"] == 180
    cam.configure(cam.create_video_configuration(
        main={"size": (settings["width"], settings["height"])},
        controls={"FrameRate": settings["fps"]},
        transform=Transform(hflip=flip, vflip=flip),
    ))
    cam.start_recording(MJPEGEncoder(), FileOutput(Frames()))
    print("ready", flush=True)
    try:
        sys.stdin.read()  # until stdin closes
    finally:
        cam.stop_recording()
finally:
    cam.close()
