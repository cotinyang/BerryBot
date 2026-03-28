# MEMORY.md 模板参考

以下是 MEMORY.md 的设计说明和模板，用于 Agent 的持久化记忆。

---

## openclaw 的 Memory 设计理念

- MEMORY.md 是本地 markdown 文件，Agent 通过工具读写
- 不是完整的对话历史，而是经过筛选的重要信息
- Agent 自主决定何时读取和更新记忆
- 记忆内容包括：用户偏好、重要事实、关键决策、待办事项等
- Agent 每次处理新输入前，先搜索/读取 MEMORY.md 中的相关内容

## openclaw 的 Memory 工具

openclaw 提供两个核心工具：
- `memory_search` — 语义搜索 MEMORY.md 内容，找到与当前对话相关的记忆片段
- `memory_get` — 读取 MEMORY.md 中的特定行，获取详细内容

## 我们的简化实现

由于语音助手场景相对简单，我们采用简化版本：
- `read_memory` — 读取整个 MEMORY.md 文件内容
- `update_memory` — 追加或更新 MEMORY.md 中的条目

## MEMORY.md 文件模板

```markdown
# 记忆

## 用户偏好

（Agent 会在这里记录发现的用户偏好）

## 重要事实

（Agent 会在这里记录重要的事实信息）

## 待办与提醒

（Agent 会在这里记录用户提到的待办事项）
```

## 记忆更新规则

Agent 的 system prompt 中应包含以下指导：
1. 当用户表达偏好时（如"我喜欢..."、"我不喜欢..."），记录到用户偏好
2. 当用户提到重要个人信息时（如名字、地址、习惯），记录到重要事实
3. 当用户提到待办事项时（如"提醒我..."、"记住..."），记录到待办与提醒
4. 不要记录日常闲聊内容
5. 更新时保持简洁，每条记忆一行
