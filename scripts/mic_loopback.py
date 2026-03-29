#!/usr/bin/env python3
"""Real-time microphone loopback monitor for debugging noise/false voice triggers.

Examples:
  python scripts/mic_loopback.py --list-devices
  python scripts/mic_loopback.py
  python scripts/mic_loopback.py --input-device 2 --output-device 5 --gain 1.5
"""

from __future__ import annotations

import argparse
import contextlib
import os
import signal
import struct
import sys
import time
from typing import Any


_RUNNING = True


def _apply_gain_pcm16(data: bytes, gain: float) -> bytes:
    """Apply gain on little-endian signed 16-bit PCM data with clipping."""
    if gain == 1.0 or not data:
        return data

    sample_count = len(data) // 2
    if sample_count == 0:
        return data

    samples = struct.unpack(f"<{sample_count}h", data[: sample_count * 2])
    scaled = []
    for sample in samples:
        value = int(sample * gain)
        if value > 32767:
            value = 32767
        elif value < -32768:
            value = -32768
        scaled.append(value)
    return struct.pack(f"<{sample_count}h", *scaled)


def _compute_rms_pcm16(data: bytes) -> float:
    """Compute RMS for little-endian signed 16-bit PCM bytes."""
    sample_count = len(data) // 2
    if sample_count == 0:
        return 0.0
    samples = struct.unpack(f"<{sample_count}h", data[: sample_count * 2])
    sum_squares = sum(sample * sample for sample in samples)
    return (sum_squares / sample_count) ** 0.5


def _compute_peak_pcm16(data: bytes) -> int:
    """Compute absolute peak for little-endian signed 16-bit PCM bytes."""
    sample_count = len(data) // 2
    if sample_count == 0:
        return 0
    samples = struct.unpack(f"<{sample_count}h", data[: sample_count * 2])
    return max(abs(sample) for sample in samples)


def _is_vad_speech(
    data: bytes,
    vad: Any | None,
    sample_rate: int,
) -> bool:
    """Return whether VAD detects speech in the chunk.

    Uses majority voting on 20ms frames.
    """
    if vad is None:
        return True

    samples_per_frame = sample_rate * 20 // 1000
    frame_bytes = samples_per_frame * 2
    if frame_bytes <= 0 or len(data) < frame_bytes:
        return False

    votes = 0
    total = 0
    offset = 0
    while offset + frame_bytes <= len(data):
        frame = data[offset : offset + frame_bytes]
        total += 1
        if vad.is_speech(frame, sample_rate):  # type: ignore[union-attr]
            votes += 1
        offset += frame_bytes

    if total == 0:
        return False
    return votes * 2 >= total


def _signal_handler(_signum: int, _frame: Any) -> None:
    global _RUNNING
    _RUNNING = False


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Loop microphone input to headphones/speaker in real time.",
    )
    parser.add_argument(
        "--list-devices",
        action="store_true",
        help="List audio devices and exit.",
    )
    parser.add_argument(
        "--input-device",
        type=int,
        default=None,
        help="Input device index (default: PortAudio default input).",
    )
    parser.add_argument(
        "--output-device",
        type=int,
        default=None,
        help="Output device index (default: PortAudio default output).",
    )
    parser.add_argument(
        "--sample-rate",
        type=int,
        default=16000,
        help="Sample rate (default: 16000).",
    )
    parser.add_argument(
        "--frames-per-buffer",
        type=int,
        default=512,
        help="Frames per audio callback buffer (default: 512).",
    )
    parser.add_argument(
        "--channels",
        type=int,
        default=1,
        choices=[1, 2],
        help="Audio channels (default: 1).",
    )
    parser.add_argument(
        "--gain",
        type=float,
        default=1.0,
        help="Software gain multiplier for mic signal (default: 1.0).",
    )
    parser.add_argument(
        "--energy-threshold",
        type=float,
        default=800.0,
        help="Voice energy threshold on RMS (default: 800.0).",
    )
    parser.add_argument(
        "--use-webrtc-vad",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Enable WebRTC VAD gating for diagnostics (default: enabled).",
    )
    parser.add_argument(
        "--webrtc-vad-mode",
        type=int,
        choices=[0, 1, 2, 3],
        default=2,
        help="WebRTC VAD aggressiveness: 0 (least) to 3 (most strict).",
    )
    parser.add_argument(
        "--min-voice-duration",
        type=float,
        default=0.3,
        help="Continuous voice duration to mark interrupt-like event (seconds).",
    )
    parser.add_argument(
        "--grace-period",
        type=float,
        default=0.8,
        help="Ignore interrupt-like event in initial playback grace period (seconds).",
    )
    parser.add_argument(
        "--meter-interval",
        type=float,
        default=1.0,
        help="Seconds between diagnostic logs (default: 1.0).",
    )
    parser.add_argument(
        "--log-meter",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Enable periodic RMS/Peak/VAD logs (default: enabled).",
    )
    parser.add_argument(
        "--suppress-native-logs",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Suppress noisy ALSA/JACK stderr emitted by native audio backends.",
    )
    return parser


@contextlib.contextmanager
def _suppress_native_stderr(enabled: bool):
    """Temporarily redirect process stderr to /dev/null.

    PortAudio backend probing may emit large ALSA/JACK noise on stderr. This
    context only affects the wrapped block.
    """
    if not enabled:
        yield
        return

    devnull_fd = os.open(os.devnull, os.O_WRONLY)
    saved_stderr_fd = os.dup(2)
    try:
        os.dup2(devnull_fd, 2)
        yield
    finally:
        os.dup2(saved_stderr_fd, 2)
        os.close(saved_stderr_fd)
        os.close(devnull_fd)


def _list_devices(pa: Any) -> None:
    host_info = pa.get_host_api_info_by_index(0)
    total = host_info.get("deviceCount", 0)
    default_in = pa.get_default_input_device_info().get("index", "N/A")
    default_out = pa.get_default_output_device_info().get("index", "N/A")
    print(f"Default input index: {default_in}")
    print(f"Default output index: {default_out}")
    print("\nDevices:")
    for idx in range(total):
        info = pa.get_device_info_by_host_api_device_index(0, idx)
        name = info.get("name", "<unknown>")
        max_in = int(info.get("maxInputChannels", 0))
        max_out = int(info.get("maxOutputChannels", 0))
        rate = int(info.get("defaultSampleRate", 0))
        print(
            f"  [{idx}] {name} | in={max_in} out={max_out} default_rate={rate}"
        )


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)

    # Reduce JACK reservation noise in common desktop/Pi setups.
    os.environ.setdefault("JACK_NO_AUDIO_RESERVATION", "1")

    try:
        with _suppress_native_stderr(args.suppress_native_logs):
            import pyaudio  # type: ignore[import-untyped]
    except ImportError:
        print("pyaudio is not installed. Install it first (e.g. uv sync --extra sherpa).")
        return 2

    signal.signal(signal.SIGINT, _signal_handler)
    signal.signal(signal.SIGTERM, _signal_handler)

    vad = None
    if args.use_webrtc_vad:
        try:
            import webrtcvad  # type: ignore[import-untyped]

            vad = webrtcvad.Vad()
            vad.set_mode(args.webrtc_vad_mode)
        except ImportError:
            print("webrtcvad not installed, fallback to RMS-only diagnostics")
        except Exception as exc:
            print(f"webrtcvad init failed ({exc}), fallback to RMS-only diagnostics")

    chunk_duration_sec = args.frames_per_buffer / args.sample_rate
    elapsed_sec = 0.0
    consecutive_voice_sec = 0.0
    last_meter_ts = time.monotonic()

    with _suppress_native_stderr(args.suppress_native_logs):
        pa = pyaudio.PyAudio()
    in_stream = None
    out_stream = None

    try:
        if args.list_devices:
            _list_devices(pa)
            return 0

        with _suppress_native_stderr(args.suppress_native_logs):
            in_stream = pa.open(
                format=pyaudio.paInt16,
                channels=args.channels,
                rate=args.sample_rate,
                input=True,
                frames_per_buffer=args.frames_per_buffer,
                input_device_index=args.input_device,
            )
            out_stream = pa.open(
                format=pyaudio.paInt16,
                channels=args.channels,
                rate=args.sample_rate,
                output=True,
                frames_per_buffer=args.frames_per_buffer,
                output_device_index=args.output_device,
            )

        print("Mic loopback started. Press Ctrl+C to stop.")
        print(
            f"input_device={args.input_device}, output_device={args.output_device}, "
            f"rate={args.sample_rate}, channels={args.channels}, "
            f"buffer={args.frames_per_buffer}, gain={args.gain}"
        )
        print(
            "diag: "
            f"threshold={args.energy_threshold}, vad_enabled={vad is not None}, "
            f"vad_mode={args.webrtc_vad_mode}, grace={args.grace_period}s, "
            f"min_voice={args.min_voice_duration}s"
        )

        while _RUNNING:
            data = in_stream.read(args.frames_per_buffer, exception_on_overflow=False)
            if args.gain != 1.0:
                data = _apply_gain_pcm16(data, args.gain)

            rms = _compute_rms_pcm16(data)
            peak = _compute_peak_pcm16(data)
            over_threshold = rms >= args.energy_threshold
            vad_voice = _is_vad_speech(data, vad, args.sample_rate)
            voice_frame = over_threshold and (not args.use_webrtc_vad or vad_voice)

            elapsed_sec += chunk_duration_sec
            if elapsed_sec < args.grace_period:
                consecutive_voice_sec = 0.0
            elif voice_frame:
                consecutive_voice_sec += chunk_duration_sec
            else:
                consecutive_voice_sec = 0.0

            now = time.monotonic()
            if args.log_meter and (now - last_meter_ts) >= args.meter_interval:
                print(
                    "meter: "
                    f"rms={rms:.1f}, peak={peak}, threshold={args.energy_threshold:.1f}, "
                    f"over_threshold={over_threshold}, vad_voice={vad_voice}, "
                    f"elapsed={elapsed_sec:.1f}s, consecutive_voice={consecutive_voice_sec:.1f}s"
                )
                last_meter_ts = now

            if elapsed_sec >= args.grace_period and consecutive_voice_sec >= args.min_voice_duration:
                print(
                    "event: interrupt-like condition met "
                    f"(rms={rms:.1f}, peak={peak}, consecutive_voice={consecutive_voice_sec:.1f}s)"
                )

            out_stream.write(data)

        return 0
    except KeyboardInterrupt:
        return 0
    except Exception as exc:
        print(f"Loopback failed: {exc}")
        return 1
    finally:
        if in_stream is not None:
            try:
                in_stream.stop_stream()
                in_stream.close()
            except Exception:
                pass
        if out_stream is not None:
            try:
                out_stream.stop_stream()
                out_stream.close()
            except Exception:
                pass
        pa.terminate()


if __name__ == "__main__":
    sys.exit(main())
