# 聊天室与对话双轨制（room vs conversation）

> 对应主索引：`../README.md`
> 对应代码：
> - `apps/backend/app/services/chat_storage.py` —— 聊天室（多人 / @小文 / 文件 / 表情）
> - `apps/backend/app/services/storage.py::ConversationStorage` —— 学生对话（单人 ↔ 智能体多轮）
> - `apps/backend/app/main.py`：`/api/chat/*` 路由 + `_handle_xiaowen_mention` + `WebSocket /ws/chat/{room_id}`
> 对应前端：`apps/web/app/chat/page.tsx`（聊天室）、学生主页 `apps/web/app/student/page.tsx`（对话）

## 1. 一图流：两条数据通路并存

```
┌─────────── 聊天室（chat room） ────────────┐   ┌───── 学生 ↔ 智能体对话（conversation） ─────┐
│ 多人 + AI（@小文）+ 文件 + 表情            │   │ 1 学生 ↔ 多 Agent 串联                       │
│ WebSocket 实时广播                         │   │ HTTP POST /api/dialogue/turn 请求-响应       │
│ data/chat/rooms.json                       │   │ data/conversations/{project_id}/{conv}.json  │
│ data/chat/messages/{room_id}.json          │   │ 每条消息都附带 agent_trace                   │
│ data/chat/ai_analyses/{room_id}.json       │   │ 自动生成 logical_project_id                  │
│ data/chat_files/{room_id}/{filename}       │   │ 自动维护 exploration_state, summary, title   │
└────────────────────────────────────────────┘   └────────────────────────────────────────────┘
                       ▲                                                ▲
                       │                                                │
                       └────── 唯一交集：@小文 触发 deep mode ────────┘
                              `_handle_xiaowen_mention` 复用 graph_workflow
```

设计意图：
- **聊天室**是多人协作场景的"群"，主要承载团队沟通 + 文件共享 + AI 助理顺手回答；
- **对话**是单个学生 1v1 跟智能体推进项目的主战场，每条消息都要走完整的多智能体流水线（diagnose → kg → hypergraph → critic → coach …），并把结果落到 `agent_trace` 里。
- 两套数据**故意不共享 schema**，避免聊天室的高频小消息把对话主链路的索引搞重。

## 2. 聊天室数据模型

### 2.1 房间元信息

文件：`data/chat/rooms.json`

```json
{
  "room_id": "uuid4",
  "type": "team | dm | system",
  "name": "团队A · 项目讨论",
  "avatar": null,
  "members": ["user-...", "ai_xiaowen", ...],
  "admin_ids": ["user-..."],
  "team_id": "team-...",
  "project_id": "project-...",
  "created_at": "2026-04-24T12:00:00+08:00",
  "last_message_preview": "张三: 我们看一下今天的访谈纪要…",
  "last_message_at": "2026-04-24T18:42:01+08:00",
  "unread_counts": { "user-xxx": 3 }
}
```

### 2.2 消息

文件：`data/chat/messages/{room_id}.json`（每个房间一份独立 JSON）

```json
{
  "msg_id": "uuid4",
  "room_id": "...",
  "sender_id": "user-xxx | ai_xiaowen",
  "sender_name": "张三 | 小文",
  "type": "text | image | file | system | ai_reply",
  "content": "...",
  "mentions": ["ai_xiaowen", ...],
  "reply_to": "msg_id | null",
  "file_meta": {
    "filename": "...",
    "stored_name": "...",
    "size": 12345,
    "content_type": "image/png",
    "url": "/chat_files/{room_id}/{stored_name}"
  },
  "reactions": {
    "👍": ["user-xxx", ...],
    "❤️": [...]
  },
  "created_at": "2026-04-24T18:42:01+08:00"
}
```

### 2.3 AI 分析归档（共享面板专用）

文件：`data/chat/ai_analyses/{room_id}.json`，最多保留 200 条

```json
{
  "id": "msg_id（同 ai_reply 消息）",
  "query": "学生原话（去掉 @小文）",
  "reply": "小文输出全文",
  "mode": "shallow | deep",
  "sender": "@小文 的发起人姓名",
  "time": "ISO8601"
}
```

> 这个文件是为"AI 共享分析面板"设计的——团队成员可以看到历史所有 AI 回答的归档，不需要在聊天里翻消息。

### 2.4 上传文件

物理路径：`data/chat_files/{room_id}/{stored_name}`
HTTP 暴露：`/chat_files/{room_id}/{stored_name}`（FastAPI `StaticFiles` 挂载）
存储名 = `uuid4().hex[:8] + "_" + 原文件名`，避免重名互相覆盖。

## 3. 对话（conversation）数据模型

文件：`data/conversations/{project_id}/{conversation_id}.json`

```json
{
  "conversation_id": "uuid4",
  "project_id": "project-{user_id}",
  "student_id": "...",
  "title": "AI 法务 · 数据合规与跨境传输",
  "summary": "用户希望识别 …",
  "created_at": "...",
  "messages": [
    { "role": "user", "content": "...", "timestamp": "..." },
    {
      "role": "assistant",
      "content": "...",
      "timestamp": "...",
      "agent_trace": { … 完整的诊断 / kg / 超图 / critic / competition },
      "diagnosis": { … },
      "next_task": { … },
      "kg_analysis": { … },
      "hypergraph_insight": { … },
      "exploration_state": { "phase": "...", "filled_slots": {…} }
    }
  ],
  "exploration_state": { "phase": "discovery", … }
}
```

特征：
- **每个 project_id 一个文件夹，每个 conversation 一个 JSON**：方便按学生独立备份 / 删除。
- **每条 assistant 消息都带 `agent_trace`**：相当于自带"审计日志"，前端可视化、教师批改、自动化测试都能直接读。
- **自动生成 title / summary**：`append_message` 时按 next_task / diagnosis / kg insight 优先级生成；首条 assistant 消息会把 title 从"新对话"覆盖为真实标题。
- **`exploration_state` 跨轮持久化**：`graph_workflow` 用它来追踪学生在 discovery → validation → execution 三个阶段的填槽进度。

## 4. 路由 / API 全景

### 4.1 聊天室相关（`/api/chat/*`）

| 路径 | 用途 |
| --- | --- |
| `GET /api/chat/contacts?user_id=` | 我的可联系人列表（按团队聚合 + 全校师生 + 系统 AI 小文） |
| `POST /api/chat/rooms` | 创建房间（team / dm） |
| `GET /api/chat/rooms?user_id=` | 我加入的所有房间，按 `last_message_at` 倒序 |
| `GET /api/chat/rooms/{room_id}` | 房间元信息 |
| `DELETE /api/chat/rooms/{room_id}` | 删除房间（同时清空消息文件） |
| `POST /api/chat/rooms/{room_id}/members` | 加成员 |
| `DELETE /api/chat/rooms/{room_id}/members/{user_id}` | 踢成员 |
| `GET /api/chat/rooms/{room_id}/messages?limit=&before=` | 拉历史消息（支持分页/before 游标） |
| `POST /api/chat/rooms/{room_id}/messages` | 发送文本消息（命中 `@小文` 自动触发 AI 异步回复） |
| `POST /api/chat/rooms/{room_id}/files` | 上传文件 / 图片，自动产生 `image` / `file` 消息 |
| `GET /api/chat/rooms/{room_id}/files` | 列出该房间所有文件类消息 |
| `GET /api/chat/rooms/{room_id}/ai-history` | 该房间所有 AI 分析归档（共享面板用） |
| `DELETE /api/chat/rooms/{room_id}/ai-history/{entry_id}` | 删除某条归档 |
| `WebSocket /ws/chat/{room_id}?user_id=&user_name=` | 实时广播（new_message / ai_analysis / 在线状态） |

### 4.2 对话相关

| 路径 | 用途 |
| --- | --- |
| `POST /api/dialogue/turn` | 同步多智能体一轮（含 `agent_trace`） |
| `POST /api/dialogue/turn-stream` | SSE 流式 |
| `GET /api/conversations/{project_id}` | 列出该项目下所有对话 |
| `GET /api/conversations/{project_id}/{conversation_id}` | 拉一条对话完整内容 |
| `DELETE /api/conversations/{project_id}/{conversation_id}` | 删除对话 |

## 5. @小文：聊天室里通向智能体主链的唯一入口

`_handle_xiaowen_mention(room_id, project_id, content, sender_name)`：

1. 抽出真实 query（去掉 `@小文` / `@xiaowen`）。
2. 拉本房间最近 30 条消息组成 history_context（去掉非文本消息）。
3. **意图分类** `_classify_xiaowen_intent`：
   - `shallow` → 直接 `composer_llm.chat_text()`，秒回
   - `deep`    → 走 `graph_workflow.run_workflow(message=..., mode="coursework", history_context=..., conversation_messages=...)`
4. 先广播一条 system 消息「小文正在思考 / 正在深度分析」，给前端 loading 反馈。
5. 拿到回复后：
   - 写一条 `type=ai_reply` 的消息（`sender_id=ai_xiaowen`）。
   - 调用 `chat_store.save_ai_analysis(room_id, entry)` 落盘共享面板归档。
   - 通过 `_broadcast_to_room` 推送两条 WS 事件：`new_message` + `ai_analysis`。

> 关键设计：deep 模式 **不会污染学生的 conversation 文件**。因为 chat 是群协作场景，不应该把"团队群里的随手提问"算到某个学生的对话历史里。如果要记到对话里，应该在学生主对话页面里发，而不是在聊天室里 @小文。

## 6. WebSocket 协议

连接 URL：`/ws/chat/{room_id}?user_id=...&user_name=...`

**服务器→客户端 事件**：

```json
// 新消息（包括 AI 回复、文件、系统消息）
{ "type": "new_message", "message": { ... 上面 messages 模型 ... } }

// AI 分析归档新增
{ "type": "ai_analysis", "entry": { ... 上面 ai_analyses 模型 ... } }

// 在线 / 离线广播
{ "type": "presence", "user_id": "...", "online": true }

// 别人正在输入
{ "type": "typing", "user_id": "...", "user_name": "..." }
```

**客户端→服务器 事件**：

```json
// 心跳（前端 30s 一次）
{ "type": "ping" }

// 输入提示
{ "type": "typing" }

// 1v1 私聊定向投递（管理员/系统消息可指定 target_user_id）
{ "type": "private", "target_user_id": "...", "payload": { ... } }
```

底层 `_ws_rooms: dict[room_id, dict[user_id, WebSocket]]` 维护连接表，断线时直接 `pop`。广播是同步遍历，发送失败的连接就地踢掉。

## 7. 与教师 / 管理员的耦合点

| 教师 / 管理员动作 | 是否影响聊天室 | 是否影响对话 |
| --- | --- | --- |
| 教师在 `/teacher` 给学生写干预 / 评分 | 不影响 | 通过 `teacher_feedback_context` 注入下一轮对话的 system prompt |
| 管理员删除学生账号 | 学生在的房间还在，只是看不到他了；他发的消息保留 | 该 project_id 下所有 conversation JSON 仍然在盘上 |
| 管理员封禁 AI（disable composer） | 聊天室 @小文 fallback 到固定文案 | 对话回复降级，但 trace 还会落 |

## 8. 可拓展点（已留好钩子）

| 想加的能力 | 应该改哪里 |
| --- | --- |
| 群里 AI 主动追问（不需要 @） | `chat_send_message` 里的 `should_trigger_ai` 判断条件加规则（例如冷场 30 秒触发） |
| 把聊天室一段对话"沉淀"到学生对话里 | 加 `POST /api/chat/rooms/{room_id}/promote-to-conversation`，复用 `_handle_xiaowen_mention` 的 deep 路径 |
| 对话支持多人 | `ConversationStorage` 加 `participants: list[str]`；`_derive_logical_project_id` 加 owner 选择 |
| 聊天室全文检索 | `chat_storage.search(query, room_ids=[...])`，遍历 `messages/*.json` 配合 `re` 即可（数据量不大不用 ES） |

## 9. 一些容易踩的坑（帮你提前避开）

1. **删除房间会同时删消息文件**：`delete_room` 里 `f.unlink()`。如果想留备份，提前 `cp` 一份。
2. **AI 触发是异步的**：`should_trigger_ai` 命中后是 `threading.Thread(...)`，主请求不阻塞。如果在测试里立刻读消息可能没看到 ai_reply，需要 sleep 或订阅 WS。
3. **每条消息都覆盖 `last_message_preview`**：`update_room_preview` 截前 80 字。富文本 / Markdown 在预览里会变成原始字符。
4. **WebSocket 同房间内允许同一 user_id 多连接**：`_ws_rooms[room_id][user_id] = websocket` 会覆盖。如果你想做"多端同时在线"，把 value 换成 list 即可。

## 10. 自测命令

```powershell
# 1) 起后端 + 前端
cd C:\...\BDSC; cmd /c "scripts\dev-all.cmd"

# 2) 创建房间（取自己 user_id 替换）
curl -X POST http://127.0.0.1:8037/api/chat/rooms `
  -H "Content-Type: application/json" `
  -d '{"name":"测试群","room_type":"team","members":["user-xxx","ai_xiaowen"]}'

# 3) 发一条消息（带 @小文）
curl -X POST http://127.0.0.1:8037/api/chat/rooms/<room_id>/messages `
  -H "Content-Type: application/json" `
  -d '{"sender_id":"user-xxx","sender_name":"我","msg_type":"text","content":"@小文 帮我列一下 BMC 9 个格子","mentions":["ai_xiaowen"]}'

# 4) 拉 AI 归档
curl http://127.0.0.1:8037/api/chat/rooms/<room_id>/ai-history
```
