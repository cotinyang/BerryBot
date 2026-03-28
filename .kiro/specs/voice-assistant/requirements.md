# 需求文档

## 简介

语音助手系统是一个客户端-服务端架构的语音交互系统。客户端运行在树莓派 3B 上，负责语音唤醒、录音、播放及语音打断功能。服务端运行在 VPS Debian 上，负责语音识别（Whisper）、AI Agent 处理（AWS strands-agents）以及语音合成（edge-tts）。客户端与服务端通过网络通信完成完整的语音交互流程。

## 术语表

- **Client（客户端）**: 运行在树莓派 3B 上的语音交互终端程序，负责音频采集、播放和唤醒词检测
- **Server（服务端）**: 运行在 VPS Debian 上的后端服务，负责语音识别、AI 处理和语音合成
- **Wake_Word_Detector（唤醒词检测器）**: 客户端中负责持续监听麦克风输入并检测唤醒词的模块，支持 Sherpa-onnx（默认）和 Porcupine 两种引擎
- **Audio_Recorder（录音器）**: 客户端中负责录制用户语音并编码为音频数据的模块
- **Audio_Player（播放器）**: 客户端中负责接收和播放服务端返回的语音数据的模块
- **Interrupt_Handler（打断处理器）**: 客户端中负责检测用户语音打断并中止当前播放的模块
- **Speech_Recognizer（语音识别器）**: 服务端中使用本地 Whisper 模型将语音转换为文字的模块
- **AI_Agent（AI 代理）**: 服务端中使用 AWS strands-agents 库创建的智能代理，负责处理用户文字输入并生成回复
- **Speech_Synthesizer（语音合成器）**: 服务端中使用 edge-tts 将文字转换为语音的模块
- **Communication_Channel（通信通道）**: 客户端与服务端之间的网络通信链路

## 需求

### 需求 1：语音唤醒

**用户故事：** 作为用户，我希望通过说出唤醒词来激活语音助手，以便开始语音交互。

#### 验收标准

1. WHILE Client 处于待机状态, THE Wake_Word_Detector SHALL 持续监听麦克风输入以检测唤醒词
2. WHEN Wake_Word_Detector 检测到唤醒词, THE Client SHALL 从待机状态切换到录音状态
3. WHEN Client 切换到录音状态, THE Client SHALL 在短暂窗口期（约 300ms）内检测是否有后续用户语音输入
4. IF 短暂窗口期内未检测到用户语音, THEN THE Client SHALL 播放预制提示音（如"我在"）以通知用户语音助手已激活
5. IF 短暂窗口期内检测到用户语音, THEN THE Client SHALL 跳过提示音播放，直接开始录制用户语音
6. IF Wake_Word_Detector 在检测过程中遇到麦克风访问错误, THEN THE Client SHALL 记录错误日志并在 5 秒后重新尝试监听

### 需求 2：语音录制与发送

**用户故事：** 作为用户，我希望语音助手能录制我的语音并发送给服务端处理，以便获得智能回复。

#### 验收标准

1. WHILE Client 处于录音状态, THE Audio_Recorder SHALL 持续录制麦克风输入的音频数据
2. WHEN Audio_Recorder 检测到用户停止说话（静音超过设定阈值）, THE Audio_Recorder SHALL 停止录音并将音频数据发送给 Server
3. THE Audio_Recorder SHALL 将录制的音频编码为 WAV 格式后再发送给 Server
4. IF Audio_Recorder 发送音频数据到 Server 失败, THEN THE Client SHALL 播放错误提示音并返回待机状态
5. WHEN Audio_Recorder 完成音频发送, THE Client SHALL 从录音状态切换到等待响应状态

### 需求 3：语音识别

**用户故事：** 作为系统，我希望服务端能将接收到的语音准确转换为文字，以便 AI Agent 处理。

#### 验收标准

1. WHEN Server 接收到来自 Client 的音频数据, THE Speech_Recognizer SHALL 使用本地 Whisper 模型将音频转换为文字
2. THE Speech_Recognizer SHALL 支持中文语音的识别
3. IF Speech_Recognizer 无法识别音频内容, THEN THE Server SHALL 向 Client 返回一条提示语音，告知用户未能识别语音内容
4. IF Speech_Recognizer 在处理过程中发生错误, THEN THE Server SHALL 记录错误日志并向 Client 返回错误提示语音

### 需求 4：AI Agent 处理

**用户故事：** 作为系统，我希望服务端能通过 AI Agent 智能处理用户的文字输入并生成回复，以便为用户提供有价值的响应。

#### 验收标准

1. WHEN Speech_Recognizer 输出识别文字, THE AI_Agent SHALL 接收该文字并进行处理
2. THE AI_Agent SHALL 使用 AWS strands-agents 库创建并管理智能代理实例
3. WHEN AI_Agent 完成处理, THE AI_Agent SHALL 输出回复文字给 Speech_Synthesizer
4. IF AI_Agent 在处理过程中发生错误, THEN THE Server SHALL 记录错误日志并向 Client 返回错误提示语音
5. THE AI_Agent SHALL 具备 Soul（人格）配置，通过 SOUL.md 文件定义 Agent 的性格、语气和行为准则
6. THE AI_Agent SHALL 具备 Memory（记忆）功能，通过本地 MEMORY.md 文件持久化存储重要的对话信息和用户偏好
7. WHEN AI_Agent 在对话中发现值得记录的信息（如用户偏好、重要决策、关键事实）, THE AI_Agent SHALL 主动更新 MEMORY.md 文件
8. WHEN AI_Agent 处理新的用户输入时, THE AI_Agent SHALL 先读取 MEMORY.md 中的相关记忆作为上下文

### 需求 5：语音合成

**用户故事：** 作为系统，我希望服务端能将 AI Agent 的文字回复转换为自然语音，以便用户通过语音接收回复。

#### 验收标准

1. WHEN AI_Agent 输出回复文字, THE Speech_Synthesizer SHALL 使用 edge-tts 将文字转换为语音数据
2. THE Speech_Synthesizer SHALL 生成中文语音输出
3. WHEN Speech_Synthesizer 完成语音合成, THE Server SHALL 将语音数据发送给 Client
4. IF Speech_Synthesizer 在合成过程中发生错误, THEN THE Server SHALL 记录错误日志并向 Client 返回错误提示语音

### 需求 6：语音播放

**用户故事：** 作为用户，我希望客户端能播放服务端返回的语音回复，以便我通过听觉接收助手的回答。

#### 验收标准

1. WHEN Client 接收到来自 Server 的语音数据, THE Audio_Player SHALL 立即开始播放该语音
2. WHILE Audio_Player 正在播放语音, THE Client SHALL 处于播放状态
3. WHEN Audio_Player 完成语音播放, THE Client SHALL 进入连续对话监听状态（LISTENING），等待用户继续说话
4. IF Audio_Player 在播放过程中遇到音频设备错误, THEN THE Client SHALL 记录错误日志并返回待机状态

### 需求 7：语音打断

**用户故事：** 作为用户，我希望在助手播放回复时能通过说话打断播放，以便我可以立即发出新的指令。

#### 验收标准

1. WHILE Audio_Player 正在播放语音, THE Interrupt_Handler SHALL 持续监听麦克风输入以检测用户语音
2. WHEN Interrupt_Handler 检测到用户语音输入, THE Interrupt_Handler SHALL 立即停止 Audio_Player 的播放
3. WHEN Interrupt_Handler 停止播放后, THE Client SHALL 切换到录音状态以录制用户的新语音输入
4. THE Interrupt_Handler SHALL 区分环境噪音和用户语音，仅在检测到用户语音时触发打断

### 需求 8：客户端与服务端通信

**用户故事：** 作为系统，我希望客户端和服务端之间有可靠的通信机制，以便语音数据能稳定传输。

#### 验收标准

1. THE Communication_Channel SHALL 使用 WebSocket 协议在 Client 和 Server 之间建立持久连接
2. WHEN Client 启动时, THE Client SHALL 自动连接到 Server
3. IF Communication_Channel 连接断开, THEN THE Client SHALL 每隔 5 秒自动尝试重新连接
4. IF Communication_Channel 连接在 3 次重连尝试后仍未恢复, THEN THE Client SHALL 播放连接失败提示音并进入离线待机状态
5. WHEN Communication_Channel 重新建立连接, THE Client SHALL 从离线待机状态恢复到正常待机状态

### 需求 9：连续对话

**用户故事：** 作为用户，我希望唤醒一次后可以连续对话，不用每句话都重新唤醒。

#### 验收标准

1. WHEN Audio_Player 完成语音播放, THE Client SHALL 进入 LISTENING 状态，持续监听麦克风等待用户继续说话
2. WHILE Client 处于 LISTENING 状态, IF 检测到用户语音, THEN THE Client SHALL 切换到 RECORDING 状态开始新一轮录音
3. WHILE Client 处于 LISTENING 状态, IF 超过配置的超时时间（默认 5 秒）未检测到用户语音, THEN THE Client SHALL 播放会话结束提示音并返回 STANDBY 状态
4. WHEN Client 从 LISTENING 返回 STANDBY, THE Client SHALL 重新启动 Wake_Word_Detector

### 需求 10：会话控制指令

**用户故事：** 作为用户，我希望可以通过语音命令主动结束会话，而不用等超时。

#### 验收标准

1. WHEN 用户说出结束意图的话（如"退出"、"不聊了"、"拜拜"）, THE AI_Agent SHALL 调用 end_session 工具
2. WHEN AI_Agent 调用 end_session 工具, THE Server SHALL 向 Client 发送 command 类型消息（action: end_session）
3. WHEN Client 接收到 end_session 指令, THE Client SHALL 播放会话结束提示音并返回 STANDBY 状态

### 需求 11：多模型支持

**用户故事：** 作为用户，我希望可以在对话中切换不同的 AI 模型，以便选择最适合当前需求的模型。

#### 验收标准

1. THE Server SHALL 支持通过 models.json 配置文件预定义多个 LLM 模型（支持 Gemini 和 OpenAI 兼容接口）
2. THE Server SHALL 在启动时加载默认模型
3. WHEN 用户说"有哪些模型", THE AI_Agent SHALL 调用 list_models 工具列出所有可用模型
4. WHEN 用户说"换成 xxx", THE AI_Agent SHALL 调用 switch_model 工具切换到指定模型
5. WHEN 模型切换成功, THE AI_Agent SHALL 在下一轮对话中使用新模型

### 需求 12：通信安全

**用户故事：** 作为系统，我希望客户端和服务端之间的通信是加密和认证的，以防止未授权访问。

#### 验收标准

1. THE Server SHALL 支持通过 TLS 证书启用 wss:// 加密通信
2. THE Server SHALL 支持通过预共享 token 进行客户端认证
3. WHEN Client 连接时, THE Client SHALL 在 WebSocket URL 中携带认证 token
4. IF Client 提供的 token 与 Server 配置不匹配, THEN THE Server SHALL 拒绝连接并关闭 WebSocket
