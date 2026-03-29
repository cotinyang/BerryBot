# BerryBot

[![Python](https://img.shields.io/badge/Python-3.11%2B-blue.svg)](https://www.python.org/)
[![Platform](https://img.shields.io/badge/Platform-Raspberry%20Pi%20%2B%20VPS-green.svg)](https://www.raspberrypi.com/)
[![Protocol](https://img.shields.io/badge/Realtime-WebSocket-orange.svg)](#架构)

BerryBot 是一个面向树莓派终端 + 云端 VPS 的实战语音助手项目。

它覆盖了完整的近实时语音交互闭环：

- 设备侧唤醒词检测
- 语音录制与上传
- 服务端 ASR 与 Agent 处理
- TTS 语音流式返回
- 播放中可语音打断

English documentation: [README.en.md](README.en.md)

## 功能亮点

- 中文语音助手端到端链路
- WebSocket 实时双向通信
- 流式 TTS 回放，降低首响延迟
- 会话状态管理与打断控制
- 适配树莓派与蓝牙音箱的可配置播放后端
- 克隆后可快速检查 `.env` 字段差异

## 架构

1. 客户端持续监听唤醒词。
2. 唤醒后录音并发送音频到服务端。
3. 服务端执行 ASR、Agent 推理、TTS 合成。
4. 服务端通过 WebSocket 流式推送音频 chunk。
5. 客户端边接收边播放。
6. 用户可在播放过程中打断并继续对话。

## 仓库结构

- [client](client): 设备侧运行时（唤醒词、录音、播放、WebSocket 客户端）
- [server](server): 服务端组件（ASR、Agent、TTS、WebSocket 服务）
- [scripts](scripts): 工具脚本（例如 env 字段比对）
- [openclaw](openclaw): 其他工作区内容

## 快速开始

### 前置依赖

- Python 3.11+
- [uv](https://docs.astral.sh/uv/)
- 树莓派可用的 Linux 音频后端

### 1. 安装依赖

```bash
cd client
uv sync

cd ../server
uv sync
```

### 2. 准备环境变量文件

```bash
cd ../client
cp .env.example .env

cd ../server
cp .env.example .env
```

### 3. 校验 env 字段（推荐）

```bash
# client
cd ../client
python3 ../scripts/compare_env_keys.py

# server
cd ../server
python3 ../scripts/compare_env_keys.py
```

### 4. 启动服务

```bash
# server
cd ../server
./start.sh start

# client
cd ../client
./start.sh start
```

## 树莓派音频说明

如果你使用蓝牙音箱（例如 Echo Dot），建议先在设备上验证本地播放：

```bash
mpg123 assets/wo_zai.mp3
aplay assets/end.wav
```

音频播放行为可在 [client/.env.example](client/.env.example) 中配置：

- `AUDIO_PLAYER_COMMAND`
- `AUDIO_OUTPUT_DEVICE`

## 测试

```bash
# server
cd server
uv run pytest

# client
cd ../client
uv run pytest
```

## 安全与部署建议

- 敏感信息仅保存在 `.env`，不要提交到仓库。
- 生产环境请启用 TLS。
- 使用认证 token 与网络策略限制服务访问范围。

## 许可证

本项目使用 [Apache License 2.0](LICENSE)。
