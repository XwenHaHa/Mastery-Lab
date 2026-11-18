# P1.3 Classroom API

前缀 `/api/v1/classroom`。普通成功返回 `{code:0,message,data}`，字段 camelCase。模型密钥不会返回。

| 方法 | 路径 | 输入/作用 |
| --- | --- | --- |
| GET | `/context?courseId=1&pointId=2` | 当前课程/章节/知识点摘要、教材字数、手工进度、默认模型 |
| POST | `/sessions` | `{courseId,knowledgePointId,modelConfigId?}`，创建或恢复；可切换已有模型 |
| GET | `/sessions/{id}` | 会话上下文、按 ID 排序的全部消息、streaming 标志 |
| GET | `/sessions/{id}/messages?afterId=0&limit=100` | 按 ID 升序的历史页，limit 1–200；无匹配时空数组 |
| POST | `/sessions/{id}/start` | 无 body，空会话主动教学；已有助手消息返回 409 |
| POST | `/sessions/{id}/messages` | `{content}`，去空格后 1–8000 字，发送问题并生成 |
| POST | `/sessions/{id}/regenerate` | 无 body，替换最后一个助手回答；末条为用户则补答 |
| POST | `/sessions/{id}/stop` | 无 body，返回 `{stopped,message}`；无活动任务时 stopped=false |

所有路径 ID 必须正数。不存在/不属于课程返回 404；同会话并发生成、生成中切模型返回 409；未配置模型、参数无效、解密失败返回 422。历史恢复不要求存在模型。课程、章节、知识点关联在后端校验，不信任前端课程标签。

## 流式协议

三个生成接口返回 `Content-Type: text/event-stream`，缓存禁用。使用 fetch POST + ReadableStream，不使用只支持 GET 的 EventSource。

```text
event: meta
data: {"sessionId":1,"messageId":2,"modelName":"用户选择的模型"}

event: delta
data: {"text":"本段真实增量"}

event: done
data: {"sessionId":1,"messageId":2,"status":"completed","message":{"id":2,"role":"assistant","content":"本段真实增量","status":"completed","modelName":"用户选择的模型","errorMessage":"","createdAt":"2026-11-17T00:00:00Z"}}
```

`done.status` 也可能为 `interrupted` 或空输出的 `failed`。HTTP 流已建立后不能再改状态码，模型异常使用：

```text
event: error
data: {"sessionId":1,"messageId":2,"message":"触发限流或额度不足（HTTP 429）","httpStatus":429}
```

前端应在 error 后读取会话，恢复已落库的失败消息。delta 非模拟打字；若兼容网关忽略 stream 并返回普通 JSON，会按单个真实文本块兼容，不声称该网关具备流式能力。

## 中断、重生成和恢复

- 停止接口置取消信号，同时前端立即 AbortController.abort；后端取消等待中的 HTTP 读取并保存已有正文。
- 同会话只允许一个生成任务；不同知识点可有独立任务。多标签页重新进入生成中的会话，只轮询已持久化内容而不重复调用模型。
- 首段等待 60 秒，后续读超时 180 秒，总时限 240 秒，见 `.env.example`。失败后不自动重试，防止额外扣费。
- 重生成不是多版本管理：旧最后回答在预检通过后被替换。上游失败时保存新失败状态；需要保留多个版本应留待后续功能。
- `afterId` 仅适用于追加历史读取；重生成可能复用最后 SQLite ID，需完整刷新会话而不是只用增量游标。
- 本地单用户模型，无跨账号授权体系。只能监听 loopback，不能作为公网服务使用。
