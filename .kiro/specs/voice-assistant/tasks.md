# 实现计划：语音助手系统

## 概述

按照客户端-服务端架构，从基础设施（项目结构、数据模型、通信协议）开始，逐步实现各功能模块，最后集成联调。客户端和服务端各自独立的 uv 项目，使用 Python 3.11+。

## 任务

- [ ] 1. 初始化项目结构与核心数据模型
  - [ ] 1.1 创建客户端和服务端 uv 项目结构
    - 创建 `client/` 和 `server/` 目录，分别运行 `uv init` 初始化
    - 创建 `client/pyproject.toml`，添加依赖：pvporcupine, pyaudio, websockets
    - 创建 `server/pyproject.toml`，添加依赖：pywhispercpp, strands-agents, edge-tts, websockets
    - 创建 `client/src/client/__init__.py` 和 `server/src/server/__init__.py`
    - _需求：全局_

  - [ ] 1.2 实现客户端和服务端数据模型与配置
    - 在 `client/src/client/config.py` 中实现 `ClientConfig` 数据类
    - 在 `server/src/server/config.py` 中实现 `ServerConfig` 数据类
    - 在 `client/src/client/models.py` 中实现 `AudioData`、`WSMessage`、`WSAudioMessage`、`WSErrorMessage`、`WSStatusMessage` 数据类
    - 在 `server/src/server/models.py` 中复用或引用相同的消息模型
    - _需求：2.3, 8.1_

- [ ] 2. 实现客户端状态机
  - [ ] 2.1 实现 StateMachine 类
    - 在 `client/src/client/state_machine.py` 中实现 `ClientState` 枚举和 `StateMachine` 类
    - 实现 `state` 属性、`transition` 方法、`on_state_change` 回调注册
    - 初始状态为 STANDBY
    - 实现合法状态转换校验：STANDBY→RECORDING, RECORDING→WAITING_RESPONSE, WAITING_RESPONSE→PLAYING, PLAYING→STANDBY, PLAYING→RECORDING, STANDBY→OFFLINE_STANDBY, OFFLINE_STANDBY→STANDBY, RECORDING→STANDBY, WAITING_RESPONSE→STANDBY
    - _需求：1.2, 2.5, 6.3, 7.3, 8.5_

  - [ ]* 2.2 编写状态转换正确性属性测试
    - **属性 2：状态转换正确性**
    - 使用 hypothesis 生成随机状态和事件序列，验证转换结果符合设计规则
    - 不在合法列表中的状态-事件组合不应导致状态变化
    - **验证需求：1.2, 2.5, 6.3, 7.3, 8.5**

  - [ ]* 2.3 编写状态-组件激活不变量属性测试
    - **属性 1：状态-组件激活不变量**
    - 使用 hypothesis 生成随机状态，验证各状态下活跃组件集合正确
    - **验证需求：1.1, 2.1, 6.2, 7.1**

- [ ] 3. 实现 WebSocket 通信层
  - [ ] 3.1 实现 WebSocketClient
    - 在 `client/src/client/ws_client.py` 中实现 `WebSocketClient` 类
    - 实现 `connect`、`disconnect`、`send_audio`、`send_interrupt`、`receive_audio` 方法
    - 实现自动重连逻辑：每 5 秒重试，最多 3 次
    - 实现 `on_disconnect`、`on_reconnect` 回调
    - 3 次重连失败后触发连接失败回调
    - _需求：8.1, 8.2, 8.3, 8.4, 8.5_

  - [ ] 3.2 实现 WebSocketServer
    - 在 `server/src/server/ws_server.py` 中实现 `WebSocketServer` 类
    - 实现 `start`、`stop`、`handle_client` 方法
    - 实现 `handle_interrupt` 方法处理客户端打断通知
    - 按照消息协议解析 JSON 消息和二进制帧
    - _需求：8.1_

  - [ ]* 3.3 编写重连间隔属性测试
    - **属性 7：重连间隔**
    - 使用 hypothesis 生成随机断连场景，验证重连间隔等于配置值
    - **验证需求：8.3**

- [ ] 4. 检查点 - 确保基础设施测试通过
  - 确保所有测试通过，如有问题请询问用户。

- [ ] 5. 实现客户端音频模块
  - [ ] 5.1 实现 AudioRecorder
    - 在 `client/src/client/audio_recorder.py` 中实现 `AudioRecorder` 类
    - 实现 `start_recording`、`stop_recording` 异步方法
    - 实现 `encode_wav` 方法将 PCM 数据编码为 WAV 格式
    - 实现 `detect_silence` 方法检测静音（基于能量阈值和持续时间）
    - 使用 pyaudio 进行音频采集，采样率 16000，单声道，16-bit
    - _需求：2.1, 2.2, 2.3_

  - [ ]* 5.2 编写 WAV 编码往返属性测试
    - **属性 4：WAV 编码往返**
    - 使用 hypothesis 生成随机 PCM 数据，验证编码-解码往返一致性
    - **验证需求：2.3**

  - [ ]* 5.3 编写静音检测阈值属性测试
    - **属性 3：静音检测阈值**
    - 使用 hypothesis 生成随机音频块和能量值，验证检测结果
    - **验证需求：2.2**

  - [ ] 5.4 实现 AudioPlayer
    - 在 `client/src/client/audio_player.py` 中实现 `AudioPlayer` 类
    - 实现 `play`、`stop` 异步方法和 `is_playing` 属性
    - 支持播放 MP3 格式音频数据
    - 播放完成后触发回调
    - _需求：6.1, 6.2, 6.3, 6.4_

  - [ ] 5.5 实现 InterruptHandler
    - 在 `client/src/client/interrupt_handler.py` 中实现 `InterruptHandler` 类
    - 实现 `start_monitoring`、`stop_monitoring` 异步方法
    - 实现 `is_voice` 方法区分环境噪音和用户语音（基于能量阈值）
    - 实现 `on_interrupt` 回调注册
    - _需求：7.1, 7.2, 7.4_

  - [ ]* 5.6 编写语音与噪音分类属性测试
    - **属性 6：语音与噪音分类**
    - 使用 hypothesis 生成随机音频块，验证 `is_voice` 分类结果
    - **验证需求：7.4**

  - [ ]* 5.7 编写语音打断属性测试
    - **属性 5：语音打断停止播放并转换状态**
    - 验证 PLAYING 状态下检测到语音时，播放停止且状态转为 RECORDING
    - **验证需求：7.2, 7.3**

- [ ] 6. 实现客户端唤醒词检测
  - [ ] 6.1 实现 WakeWordDetector
    - 在 `client/src/client/wake_word.py` 中实现 `WakeWordDetector` 类
    - 使用 pvporcupine 进行唤醒词检测
    - 实现 `start_listening`、`stop_listening` 异步方法
    - 实现 `on_wake_word` 回调注册
    - 处理麦克风访问错误：记录日志，5 秒后重试
    - _需求：1.1, 1.2, 1.6_

  - [ ] 6.2 实现唤醒后智能提示音逻辑
    - 在唤醒词检测后，等待约 300ms 窗口期检测后续语音
    - 无后续语音则播放预制提示音（"我在"）
    - 有后续语音则跳过提示音，直接开始录音
    - _需求：1.3, 1.4, 1.5_

- [ ] 7. 检查点 - 确保客户端模块测试通过
  - 确保所有测试通过，如有问题请询问用户。

- [ ] 8. 实现服务端语音识别模块
  - [ ] 8.1 实现 SpeechRecognizer
    - 在 `server/src/server/speech_recognizer.py` 中实现 `SpeechRecognizer` 类
    - 使用 pywhispercpp 加载 Whisper 模型，配置中文识别
    - 实现 `recognize` 方法将 WAV 音频转换为文字
    - 处理识别失败（空结果）和处理错误
    - _需求：3.1, 3.2, 3.3, 3.4_

- [ ] 9. 实现服务端 AI Agent 模块
  - [ ] 9.1 实现 AIAgent
    - 在 `server/src/server/ai_agent.py` 中实现 `AIAgent` 类
    - 使用 strands-agents 库创建智能代理实例
    - 实现 `process` 异步方法处理文字输入并返回回复
    - 实现 `_load_soul` 方法读取 SOUL.md 作为 system prompt
    - 实现 `_load_memory` 方法读取 MEMORY.md 作为对话上下文
    - 实现 `_update_memory` 方法更新 MEMORY.md
    - 处理 Agent 处理错误
    - _需求：4.1, 4.2, 4.3, 4.4, 4.5, 4.6, 4.7, 4.8_

  - [ ] 9.2 实现 Memory 工具
    - 在 `server/src/server/memory_tools.py` 中实现 `read_memory` 和 `update_memory` 两个 strands-agents tool
    - `read_memory` 工具读取 MEMORY.md 文件内容
    - `update_memory` 工具将新信息追加或更新到 MEMORY.md
    - Agent 在对话中自主决定何时调用这些工具
    - _需求：4.6, 4.7, 4.8_

  - [ ] 9.3 创建默认 SOUL.md 和 MEMORY.md 文件
    - 在 `server/SOUL.md` 中创建默认的 Agent 人格定义（参考 #[[file:.kiro/specs/voice-assistant/references/SOUL_TEMPLATE.md]]）
    - 在 `server/MEMORY.md` 中创建空的记忆文件模板（参考 #[[file:.kiro/specs/voice-assistant/references/MEMORY_TEMPLATE.md]]）
    - _需求：4.5_

- [ ] 10. 实现服务端语音合成模块
  - [ ] 10.1 实现 SpeechSynthesizer
    - 在 `server/src/server/speech_synthesizer.py` 中实现 `SpeechSynthesizer` 类
    - 使用 edge-tts 异步接口将文字转换为 MP3 语音数据
    - 配置中文语音角色 `zh-CN-XiaoxiaoNeural`
    - 处理合成错误
    - _需求：5.1, 5.2, 5.3, 5.4_

  - [ ]* 10.2 编写语音合成输出有效性属性测试
    - **属性 8：语音合成输出有效性**
    - 使用 hypothesis 生成随机非空文本，验证合成输出非空且为有效音频格式
    - **验证需求：5.1**

- [ ] 11. 检查点 - 确保服务端模块测试通过
  - 确保所有测试通过，如有问题请询问用户。

- [ ] 12. 实现服务端请求处理流水线
  - [ ] 12.1 实现服务端完整处理流程
    - 在 `server/src/server/ws_server.py` 的 `handle_client` 中串联：接收音频 → 语音识别 → AI Agent 处理 → 语音合成 → 返回语音
    - 实现打断处理：收到 interrupt 消息后取消当前合成和发送任务
    - 各环节错误时返回对应错误消息给客户端
    - _需求：3.1, 4.1, 5.3, 8.1_

  - [ ] 12.2 实现服务端入口 main.py
    - 在 `server/src/server/main.py` 中实现服务端启动逻辑
    - 加载 ServerConfig 配置
    - 启动 WebSocketServer
    - _需求：8.1_

- [ ] 13. 实现客户端主控逻辑与集成
  - [ ] 13.1 实现客户端主控流程
    - 在 `client/src/client/main.py` 中实现客户端启动和主循环逻辑
    - 加载 ClientConfig 配置
    - 初始化所有组件：StateMachine, WakeWordDetector, AudioRecorder, AudioPlayer, InterruptHandler, WebSocketClient
    - 注册状态转换回调，串联完整交互流程：
      - 唤醒 → 智能提示音 → 录音 → 发送 → 等待 → 播放 → 待机
      - 播放中打断 → 发送 interrupt → 录音
    - 启动时自动连接服务端
    - 处理连接失败和离线待机状态
    - _需求：1.2, 1.3, 1.4, 1.5, 2.4, 2.5, 6.3, 7.2, 7.3, 8.2, 8.4, 8.5_

  - [ ]* 13.2 编写客户端集成测试
    - 测试完整交互流程（使用 mock 替代硬件和网络）
    - 测试错误处理和状态恢复
    - _需求：1.2, 2.4, 6.3, 7.3, 8.4_

- [ ] 14. 最终检查点 - 确保所有测试通过
  - 确保所有测试通过，如有问题请询问用户。

## 备注

- 标记 `*` 的任务为可选任务，可跳过以加快 MVP 进度
- 每个任务引用了具体的需求编号以确保可追溯性
- 检查点用于增量验证，确保每个阶段的代码质量
- 属性测试使用 hypothesis 库，每个属性至少 100 次迭代
- 客户端和服务端各自独立的 uv 项目，分别管理依赖
