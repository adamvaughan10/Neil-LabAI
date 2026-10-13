"""
High-resolution wall clock for timestamps.

On Windows, time.time() only advances every ~4-16 ms, which is too coarse for
lining frames up at 15 fps. now() is anchored to time.time() once and then
advances with time.perf_counter() (sub-microsecond), so it reads like epoch
seconds but with fine resolution. Use it for every timestamp in a recording.
"""
import time

_WALL0 = time.time()
_PERF0 = time.perf_counter()


def now() -> float:
    """Epoch seconds with perf_counter resolution."""
    return _WALL0 + (time.perf_counter() - _PERF0)


def sleep_until(t: float) -> None:
    """Sleep until now() >= t: coarse sleep, then a short spin for precision."""
    while True:
        remaining = t - now()
        if remaining <= 0:
            return
        if remaining > 0.003:
            time.sleep(remaining - 0.002)
