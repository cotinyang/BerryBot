"""Suppress noisy ALSA/JACK stderr output during tests on Linux."""

import ctypes
import sys


def _suppress_alsa_errors() -> None:
    """Replace ALSA's default error handler with a no-op to silence device-probe spam."""
    try:
        asound = ctypes.cdll.LoadLibrary("libasound.so.2")
        handler = ctypes.CFUNCTYPE(
            None,
            ctypes.c_char_p,
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_int,
            ctypes.c_char_p,
        )
        asound.snd_lib_error_set_handler(handler(lambda *_: None))
    except OSError:
        pass  # Not on Linux / libasound not available


if sys.platform == "linux":
    _suppress_alsa_errors()
