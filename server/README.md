# BerryBot Server

语音助手服务端，运行在 VPS (Debian) 上。接收客户端语音，经过语音识别 → AI Agent → 语音合成后返回语音回复。

## 技术栈

- **语音识别**: whisper.cpp (pywhispercpp)
- **AI Agent**: AWS strands-agents，带 Soul 人格和 Memory 记忆
- **语音合成**: edge-tts
- **通信**: WebSocket (wss + token 认证)

## 前置条件

- Python 3.11+
- [uv](https://docs.astral.sh/uv/getting-started/installation/)
- whisper.cpp 编译安装 (pywhispercpp 依赖)
- TLS 证书 (Let's Encrypt 或自签)
- LLM API Key (Gemini / DeepSeek / 通义千问等)

## 安装

```bash
# 安装依赖
uv sync
```

国内网络如果 uv sync 慢，pyproject.toml 已配置清华镜像源，也可以手动指定：

```bash
uv sync --index-url https://pypi.tuna.tsinghua.edu.cn/simple
```

whisper.cpp 需要单独编译，参考 [pywhispercpp 文档](https://github.com/abarber/pywhispercpp)。

## 配置

```bash
cp .env.example .env
cp models.json.example models.json
vim .env
vim models.json
```

### .env 必须修改的配置项

| 配置项 | 说明 |
|--------|------|
| `TLS_CERT` | TLS 证书路径，如 `/etc/letsencrypt/live/your-domain.com/fullchain.pem` |
| `TLS_KEY` | TLS 私钥路径，如 `/etc/letsencrypt/live/your-domain.com/privkey.pem` |
| `AUTH_TOKEN` | 预共享认证 token，用 `openssl rand -hex 32` 生成，两端必须一致 |

### models.json 模型配置

配置多个 LLM 模型，支持运行时语音切换：

```json
{
  "default_model": "gemini-flash",
  "models": [
    {
      "name": "gemini-flash",
      "provider": "gemini",
      "model_id": "gemini-2.5-flash",
      "api_key": "your-gemini-api-key"
    },
    {
      "name": "deepseek",
      "provider": "openai_compatible",
      "model_id": "deepseek-chat",
      "api_key": "your-deepseek-api-key",
      "base_url": "https://api.deepseek.com"
    }
  ]
}
```

支持的 provider:
- `gemini` — Google Gemini 系列
- `openai_compatible` — 所有 OpenAI 兼容接口（DeepSeek、通义千问、智谱等）

### .env 可选配置项

| 配置项 | 默认值 | 说明 |
|--------|--------|------|
| `HOST` | `0.0.0.0` | 监听地址 |
| `PORT` | `8765` | 监听端口 |
| `WHISPER_MODEL` | `base` | Whisper 模型大小: tiny/base/small/medium/large |
| `TTS_VOICE` | `zh-CN-XiaoxiaoNeural` | edge-tts 语音角色 |
| `TTS_SENTENCE_STREAM` | `1` | 按句分段进行 TTS 流式合成，减轻长段中途卡顿 |
| `TTS_SENTENCE_MAX_CHARS` | `80` | 按句模式下单段最大字符数，超长句会继续切块 |
| `SOUL_PATH` | `SOUL.md` | Agent 人格定义文件 |
| `MEMORY_PATH` | `MEMORY.md` | Agent 记忆文件 |
| `DEBUG_BYPASS_AGENT` | `0` | 调试开关：为 `1` 时跳过 Agent，ASR 文本直接 TTS 回传 |

### Debug 链路联调模式

当你只想验证语音链路是否通畅（ASR -> TTS -> 客户端）时，可在 `.env` 里开启：

```bash
DEBUG_BYPASS_AGENT=1
```

然后重启服务。此模式下服务端不会调用 LLM/Agent，而是把识别到的文本直接做语音合成再返回。

## 使用

```bash
./start.sh start    # 后台启动
./start.sh stop     # 停止
./start.sh restart  # 重启
./start.sh status   # 查看状态
./start.sh logs     # 实时查看日志
```

日志输出到 `server.log`。

## Soul、Memory 和模型切换

- `SOUL.md` — 定义 Agent 的人格、语气、行为准则。可以自定义，比如改名字、调整回复风格
- `MEMORY.md` — Agent 的持久化记忆。Agent 会自动记录用户偏好、重要事实等，跨对话保持连续性
- `models.json` — 多模型配置。用户可以通过语音说"换成 deepseek"或"有哪些模型"来切换和查看模型

## Agent 工具

Agent 内置以下工具，会根据对话内容自主调用：

| 工具 | 说明 |
|------|------|
| `read_memory` | 读取 MEMORY.md 中的记忆 |
| `update_memory` | 更新 MEMORY.md，记录用户偏好/事实 |
| `list_models` | 列出所有可用模型 |
| `switch_model` | 切换当前使用的 AI 模型 |
| `end_session` | 结束当前会话（用户说"退出"时触发） |

## 测试

```bash
uv run pytest
```
