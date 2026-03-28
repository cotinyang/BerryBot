# BerryBot Client

语音助手客户端，运行在树莓派 3B 上。负责唤醒词检测、录音、播放和语音打断。

## 技术栈

- **唤醒词检测**: Porcupine (pvporcupine)
- **音频采集/播放**: PyAudio + 系统播放器 (mpg123/ffplay/aplay)
- **通信**: WebSocket (wss + token 认证)

## 前置条件

- 树莓派 3B (Raspberry Pi OS)
- Python 3.11+
- [uv](https://docs.astral.sh/uv/getting-started/installation/)
- 系统依赖:
  ```bash
  sudo apt install portaudio19-dev mpg123
  ```
- [Picovoice](https://console.picovoice.ai/) 账号 (获取 Access Key 和唤醒词模型)

## 安装

```bash
# 安装依赖（包含硬件相关库）
uv sync --extra hardware
```

## 唤醒词配置

1. 注册 [Picovoice Console](https://console.picovoice.ai/)，获取 Access Key
2. 在 Console 中创建自定义唤醒词（如"小莓"），选择 Raspberry Pi 平台，训练并下载 `.ppn` 文件
3. 将 `.ppn` 文件放到树莓派上

## 配置

```bash
cp .env.example .env
vim .env
```

必须修改的配置项：

| 配置项 | 说明 |
|--------|------|
| `SERVER_URL` | 服务端地址，如 `wss://your-domain.com:8765` |
| `AUTH_TOKEN` | 预共享认证 token，必须与服务端一致 |
| `WAKE_WORD_ACCESS_KEY` | Picovoice Access Key |
| `WAKE_WORD_KEYWORD_PATH` | 唤醒词 `.ppn` 模型文件路径 |

可选配置项：

| 配置项 | 默认值 | 说明 |
|--------|--------|------|
| `WAKE_PROMPT_AUDIO` | `assets/wo_zai.wav` | 唤醒提示音文件（"我在"） |
| `WAKE_PROMPT_DELAY` | `0.3` | 唤醒后等待后续语音的窗口期（秒） |
| `SILENCE_THRESHOLD` | `1.5` | 静音检测阈值（秒） |
| `SAMPLE_RATE` | `16000` | 音频采样率 |
| `ENERGY_THRESHOLD` | `500.0` | 语音能量阈值 |
| `RECONNECT_INTERVAL` | `5.0` | 断线重连间隔（秒） |
| `MAX_RECONNECT_RETRIES` | `3` | 最大重连次数 |

## 使用

```bash
./start.sh start    # 后台启动
./start.sh stop     # 停止
./start.sh restart  # 重启
./start.sh status   # 查看状态
./start.sh logs     # 实时查看日志
```

日志输出到 `client.log`。

## 交互流程

1. 说出唤醒词（如"小莓"）
2. 听到"我在"提示音（如果你说完唤醒词后直接继续说话，会跳过提示音）
3. 说出你的问题
4. 等待回复播放
5. 播放过程中可以直接说话打断

## 语音命令

除了普通对话，还支持以下语音命令：
- "有哪些模型" — 列出所有可用的 AI 模型
- "换成 deepseek" / "用 gemini-pro" — 切换当前使用的 AI 模型

## 提示音

将唤醒提示音文件（WAV 格式）放到 `assets/wo_zai.wav`。可以自己录制或用 TTS 生成。

## 测试

```bash
uv run pytest
```
