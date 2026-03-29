# BerryBot

[![Python](https://img.shields.io/badge/Python-3.11%2B-blue.svg)](https://www.python.org/)
[![Platform](https://img.shields.io/badge/Platform-Raspberry%20Pi%20%2B%20VPS-green.svg)](https://www.raspberrypi.com/)
[![Protocol](https://img.shields.io/badge/Realtime-WebSocket-orange.svg)](#architecture)

BerryBot is a practical voice assistant system built for Raspberry Pi clients and VPS-hosted AI services.

It supports a complete near real-time conversation loop:

- Wake word detection on device
- Speech recording and upload
- ASR + Agent response on server
- Streaming TTS back to client
- Interrupt while playback is running

An English introduction is also available in [README.en.md](README.en.md).

## Features

- End-to-end Chinese voice assistant workflow
- Low-latency audio response with streaming playback
- Configurable audio backend for Raspberry Pi and Bluetooth speakers
- Session management and interrupt handling
- Token + TLS ready deployment pattern
- Env key comparison helper after fresh clone

## Architecture

1. Client listens for wake word.
2. Client records speech and sends audio to server.
3. Server runs ASR, Agent processing, and TTS synthesis.
4. Server streams audio chunks over WebSocket.
5. Client plays chunks while receiving.
6. User interruption can stop playback and continue dialogue.

## Repository Layout

- [client](client): On-device runtime (wake word, recorder, player, websocket client)
- [server](server): ASR, Agent, TTS, websocket server
- [scripts](scripts): Utilities (for example env key diff checker)
- [openclaw](openclaw): Additional workspace content

## Quick Start

### Prerequisites

- Python 3.11+
- [uv](https://docs.astral.sh/uv/)
- Linux audio backend on Raspberry Pi

### 1. Install dependencies

```bash
cd client
uv sync

cd ../server
uv sync
```

### 2. Prepare env files

```bash
cd ../client
cp .env.example .env

cd ../server
cp .env.example .env
```

### 3. Validate env keys (recommended)

```bash
# client
cd ../client
python3 ../scripts/compare_env_keys.py

# server
cd ../server
python3 ../scripts/compare_env_keys.py
```

### 4. Start services

```bash
# server
cd ../server
./start.sh start

# client
cd ../client
./start.sh start
```

## Raspberry Pi Audio Notes

If you use a Bluetooth speaker (for example Echo Dot), verify local playback first:

```bash
mpg123 assets/wo_zai.mp3
aplay assets/end.wav
```

Audio behavior can be adjusted in [client/.env.example](client/.env.example):

- `AUDIO_PLAYER_COMMAND`
- `AUDIO_OUTPUT_DEVICE`

## Tests

```bash
# server
cd server
uv run pytest

# client
cd ../client
uv run pytest
```

## Security and Deployment

- Keep secrets in `.env` only.
- Use TLS for production websocket endpoints.
- Restrict server access with auth token and network rules.

## License

Add your preferred license file and update this section before public release.
