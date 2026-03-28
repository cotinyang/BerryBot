# BerryBot Client

语音助手客户端，运行在树莓派 3B 上。负责唤醒词检测、录音、播放和语音打断。

## 技术栈

- **唤醒词检测**: Sherpa-onnx（默认）或 Porcupine (pvporcupine)，可配置切换
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

## 安装

```bash
# 使用 sherpa-onnx 唤醒词引擎（推荐）
uv sync --extra sherpa

# 或使用 Porcupine 唤醒词引擎
uv sync --extra porcupine
```

## 唤醒词配置

支持两种唤醒词引擎，通过 `WAKE_WORD_ENGINE` 配置切换：

### Sherpa-onnx（默认，推荐）

开源免费，需要下载预训练模型并准备关键词文件：

```bash
# 1. 下载中文 KWS 模型
cd BerryBot/client
wget https://github.com/k2-fsa/sherpa-onnx/releases/download/kws-models/sherpa-onnx-kws-zipformer-wenetspeech-3.3M-2024-01-01.tar.bz2
tar xf sherpa-onnx-kws-zipformer-wenetspeech-3.3M-2024-01-01.tar.bz2

# 2. 准备关键词文件
echo "小艺小艺 @小艺小艺" > keywords_raw.txt
sherpa-onnx-cli text2token \
  --tokens sherpa-onnx-kws-zipformer-wenetspeech-3.3M-2024-01-01/tokens.txt \
  --tokens-type ppinyin \
  keywords_raw.txt \
  sherpa-onnx-kws-zipformer-wenetspeech-3.3M-2024-01-01/keywords.txt

# 3. 配置
WAKE_WORD_ENGINE=sherpa_onnx
WAKE_WORD_MODEL_PATH=sherpa-onnx-kws-zipformer-wenetspeech-3.3M-2024-01-01
```

安装：`uv sync --extra sherpa`

### Porcupine（可选）

需要 [Picovoice](https://console.picovoice.ai/) 账号（公司邮箱注册），训练 `.ppn` 模型文件：

1. 注册 Picovoice Console，获取 Access Key
2. 创建自定义唤醒词（"小艺小艺"），选择 Raspberry Pi 平台，训练并下载 `.ppn` 文件
3. 配置：

```
WAKE_WORD_ENGINE=porcupine
WAKE_WORD_ACCESS_KEY=your-access-key
WAKE_WORD_KEYWORD_PATH=/path/to/keyword.ppn
```

安装：`uv sync --extra porcupine`

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

唤醒词配置（根据引擎选择）：

| 配置项 | 说明 |
|--------|------|
| `WAKE_WORD_ENGINE` | 唤醒词引擎：`sherpa_onnx`（默认）或 `porcupine` |
| `WAKE_WORD_KEYWORDS` | sherpa_onnx 唤醒词，逗号分隔（默认: 小艺小艺） |
| `WAKE_WORD_ACCESS_KEY` | Porcupine Access Key（仅 porcupine 引擎） |
| `WAKE_WORD_KEYWORD_PATH` | Porcupine .ppn 模型路径（仅 porcupine 引擎） |

可选配置项：

| 配置项 | 默认值 | 说明 |
|--------|--------|------|
| `WAKE_PROMPT_AUDIO` | `assets/wo_zai.mp3` | 唤醒提示音文件（"我在"） |
| `WAKE_PROMPT_DELAY` | `0.3` | 唤醒后等待后续语音的窗口期（秒） |
| `SILENCE_THRESHOLD` | `1.5` | 静音检测阈值（秒） |
| `SAMPLE_RATE` | `16000` | 音频采样率 |
| `ENERGY_THRESHOLD` | `500.0` | 语音能量阈值 |
| `RECONNECT_INTERVAL` | `5.0` | 断线重连间隔（秒） |
| `MAX_RECONNECT_RETRIES` | `3` | 最大重连次数 |
| `SESSION_TIMEOUT` | `5.0` | 连续对话超时（秒），超时后结束会话 |
| `SESSION_END_AUDIO` | `assets/end.wav` | 会话结束提示音文件 |

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

1. 说出唤醒词（"小艺小艺"）
2. 听到"我在"提示音（如果你说完唤醒词后直接继续说话，会跳过提示音）
3. 说出你的问题
4. 等待回复播放
5. 播放完成后可以直接继续说话（连续对话，无需再次唤醒）
6. 播放过程中可以直接说话打断
7. 如果一段时间没说话（默认 5 秒），会听到"滴"结束音，会话结束，回到待机

## 结束会话

会话会在以下情况结束：
- 播放完成后用户超时未说话（`SESSION_TIMEOUT` 秒）
- 用户说"退出"、"不聊了"、"拜拜"等（Agent 识别后主动结束）
- 通信错误或异常

会话结束时播放结束提示音（`SESSION_END_AUDIO`），然后回到待机等待下次唤醒。

## 语音命令

除了普通对话，还支持以下语音命令：
- "有哪些模型" — 列出所有可用的 AI 模型
- "换成 deepseek" / "用 gemini-pro" — 切换当前使用的 AI 模型
- "退出" / "不聊了" / "拜拜" — 结束当前会话

## 提示音

将唤醒提示音文件（MP3 格式）放到 `assets/wo_zai.mp3`。已预生成，也可以自己录制或用 edge-tts 重新生成：

```bash
cd server && uv run edge-tts --voice zh-CN-XiaoxiaoNeural --text "我在" --write-media ../client/assets/wo_zai.mp3
```

## 测试

```bash
uv run pytest
```
