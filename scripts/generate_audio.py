#!/usr/bin/env python3
"""生成客户端音频资源文件。

需要在 server/ 目录的 venv 中运行（依赖 edge-tts 和 pydub）：
  cd server && uv run python ../scripts/generate_audio.py

生成文件：
  - client/assets/wo_zai.mp3  唤醒提示音（"我在"，前置 0.5s 静音）
  - client/assets/end.wav     会话结束音（高低两声，0.5s）
"""

import asyncio
import math
import os
import struct
import tempfile
import wave
from pathlib import Path

ASSETS_DIR = Path(__file__).resolve().parent.parent / "client" / "assets"
TTS_VOICE = "zh-CN-XiaoxiaoNeural"


async def generate_wo_zai() -> None:
    """生成唤醒提示音：0.5s 静音 + "我在"。"""
    import edge_tts
    from pydub import AudioSegment

    # 1. 用 edge-tts 生成 "我在"
    communicate = edge_tts.Communicate("我在", TTS_VOICE)
    audio = b""
    async for chunk in communicate.stream():
        if chunk["type"] == "audio":
            audio += chunk["data"]

    # 2. 写临时文件给 pydub 读
    tmp = tempfile.NamedTemporaryFile(suffix=".mp3", delete=False)
    tmp.write(audio)
    tmp.close()

    # 3. 前置 0.5s 静音
    speech = AudioSegment.from_mp3(tmp.name)
    silence = AudioSegment.silent(duration=500)
    result = silence + speech

    # 4. 导出
    out = ASSETS_DIR / "wo_zai.mp3"
    result.export(str(out), format="mp3")
    os.unlink(tmp.name)
    print(f"生成: {out} ({len(result)}ms, {out.stat().st_size} bytes)")


def generate_end_sound() -> None:
    """生成会话结束音：高音 + 低音两声。"""
    sr = 16000

    def tone(freq: float, dur: float, volume: int = 12000) -> list[int]:
        samples = []
        for i in range(int(sr * dur)):
            t = i / sr
            envelope = max(0, 1 - (t / dur) ** 0.5)
            amp = int(volume * math.sin(2 * math.pi * freq * t) * envelope)
            samples.append(amp)
        return samples

    # 高音 880Hz 0.2s + 间隔 0.05s + 低音 660Hz 0.25s
    high = tone(880, 0.2)
    gap = [0] * int(sr * 0.05)
    low = tone(660, 0.25)

    all_samples = high + gap + low
    pcm = struct.pack(f"<{len(all_samples)}h", *all_samples)

    out = ASSETS_DIR / "end.wav"
    with wave.open(str(out), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sr)
        wf.writeframes(pcm)
    print(f"生成: {out} ({len(all_samples) / sr:.2f}s, {out.stat().st_size} bytes)")


def main() -> None:
    ASSETS_DIR.mkdir(parents=True, exist_ok=True)

    print("生成唤醒提示音 (wo_zai.mp3)...")
    asyncio.run(generate_wo_zai())

    print("生成会话结束音 (end.wav)...")
    generate_end_sound()

    print("完成!")


if __name__ == "__main__":
    main()
