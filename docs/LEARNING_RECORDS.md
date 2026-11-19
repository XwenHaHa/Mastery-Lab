# Mastery Lab — 学习档案与学习记录设计（P1.5）

> 本文描述学习活动、有效时长、断点续学、掌握状态、错题归并与学习报告的实际实现。
> 文档与代码保持一致；所有统计都来自本地 SQLite，不使用模拟学习数据。

## 1. 数据模型

P1.5 新增 6 张表，并在 `knowledge_points` 增加 2 列（schema 版本 6）。旧表与旧数据不删除。

| 表 | 作用 | 关键字段 |
| --- | --- | --- |
| `learning_activities` | 一次学习活动（进入教室 → 离开） | `course_id`、`knowledge_point_id`、`session_id`、`status`、`active_seconds`、`last_heartbeat_at`、`result`、阶段与尝试快照 |
| `learning_breakpoints` | 每个会话一条断点快照 | `session_id` 主键、当前阶段/状态、`draft_answer`、`client_seq`、当前问题、计数、最后消息 |
| `mastery_history` | 掌握状态变化历史 | `from_state`、`to_state`、`reason`、`evidence`(JSON)、会话与活动 |
| `mistake_records` | 归并后的错题 / 薄弱点 | 原始问题、用户回答、参考答案、错误原因、纠正讲解、`dedupe_key`、`occurrence_count`、处理状态 |
| `mistake_occurrences` | 每次错误发生的明细 | `mistake_id`、阶段、评价、当次问题与回答、反馈 |
| `learning_events` | 活动层面的关键事件 | `ACTIVITY_STARTED`、`ACTIVITY_COMPLETED`、`MASTERY_CHANGED`、`MISTAKE_RECORDED` 等 |

`knowledge_points` 新增：

- `mastery_state`：`NOT_STARTED` / `INTRODUCED` / `UNDERSTANDING` / `GUIDED_PRACTICE` / `INDEPENDENT` / `NEEDS_REVIEW`；
- `mastery_updated_at`：最后一次掌握状态变化时间。

约束与索引：

- `learning_activities` 对 `session_id` 建部分唯一索引（`status='active'`），保证同一会话最多一条进行中的活动；
- 所有新表对课程/知识点/会话建索引；`mistake_records.dedupe_key` 建索引用于归并；
- 删除课程时，章节、知识点、活动、错题、断点随外键级联删除；`mastery_history.activity_id` 使用 `SET NULL`，历史本身不因活动清理而消失。

## 2. 学习活动与有效学习时长

### 2.1 活动生命周期

1. 进入教室后前端调用 `POST /learning/activities/start`；
2. 若该会话已有 `active` 活动且最后心跳在 15 分钟内，直接复用（`reused=true`），不重复计时；
3. 若超过 15 分钟没有心跳，旧活动关闭为 `finished` + `end_reason=idle_timeout`，`ended_at` 取最后心跳时间，然后新建活动；
4. 切换知识点、离开教室、关闭浏览器时调用 `finish`，`result` 为 `finished`；
5. VERIFY 通过时后端直接结束活动，`result=completed`；
6. 后端启动时扫描一次空闲活动并按最后心跳关闭，重启不会把离线时间算进学习时长。

### 2.2 时长口径

- 前端每 30 秒上报一次 `activeSecondsDelta`；
- 只有页面可见且最近 5 分钟内有真实操作（指针、键盘、滚动）时才累计；
- 页面隐藏时立即上报一次并停止累计；重新可见后重新计时；
- 单次上报服务端最多接受 120 秒，并且不超过「距上次心跳的时间 + 5 秒」，防止伪造或时钟跳跃；
- `active_seconds` 是唯一进入统计的时长；`started_at` / `ended_at` 仅用于展示与活动详情，不直接相减。

因此下列情况不会虚增时长：切换标签页、浏览器关闭、后端中断、长时间无操作、重复打开同一知识点、恢复会话。

## 3. 断点续学

### 3.1 快照内容

`learning_breakpoints` 保存：

- 课程、章节、知识点、会话、当前活动；
- 当前教学阶段、阶段状态、修订号、是否暂停；
- 当前问题、已完成阶段、PAIR 小步与 CHECK/PAIR/VERIFY 尝试次数、提示次数；
- 前端草稿、输入模式（提问 / 提交回答）；
- 最后一条消息与最后一条老师消息的 ID、老师消息摘要。

教学阶段、问题与尝试次数由后端在状态机变化时同步写入，前端不能伪造；前端只通过 `PUT` 保存草稿与输入模式。

### 3.2 保存时机

- 进入教室、阶段切换、问题生成、评价完成、暂停/恢复、重新学习时由后端同步；
- 用户输入草稿时前端 900 ms 防抖保存；
- 页面隐藏、关闭标签页、浏览器退出时用 `fetch(keepalive)` 再保存一次；
- 重要状态变化后立即保存，不只依赖 `beforeunload`。

### 3.3 并发与顺序

- 每个会话维护单调递增 `client_seq`；
- 服务端只接受大于等于当前序号的写入；
- 旧序号请求返回当前快照且 `accepted=false`，不会覆盖更新的草稿；
- 同一会话的断点行由主键约束保证唯一；并发初始化使用 SQLite savepoint 兜底。

### 3.4 恢复规则

1. 刷新、关闭教室、关闭浏览器、后端重启后，重新打开同一知识点；
2. 当前知识点未完成 → 回到原知识点；
3. 当前阶段未完成 → 回到原阶段与原阶段状态；
4. 若上一次在等待回答 → 恢复同一问题与草稿，不重新生成问题；
5. 若 VERIFY 已通过 → 不重复要求验证，恢复入口指向下一个知识点；
6. 只有用户主动点击「重新学习」才会清空当前轮次草稿并重新开始，之前的历史证据不删除；
7. 恢复不创建新会话：`learning_sessions` 对「课程 + 知识点」有唯一约束，`openSession` 幂等。

## 4. 掌握状态

| 状态 | 含义 | 触发证据 |
| --- | --- | --- |
| `NOT_STARTED` | 未接触 | 默认值；无教学证据 |
| `INTRODUCED` | 已接触 | 完成 TEACH 或 DEMO |
| `UNDERSTANDING` | 理解中 | 正在 CHECK，或 CHECK 尚未稳定通过 |
| `GUIDED_PRACTICE` | 引导练习 | 进入 PAIR，或 CHECK 正确后进入陪练 |
| `INDEPENDENT` | 独立完成 | VERIFY 通过，且验证过程没有使用提示 |
| `NEEDS_REVIEW` | 需要复习 | VERIFY 失败/需要复习，或已处于待复习时再次出错 |

规则：

- 状态只由教学状态机事件推导，AI 的自然语言回复不能直接写状态；
- 每次变化写 `mastery_history`，记录前一状态、后一状态、原因、阶段、评价、尝试与提示次数；
- 一次 CHECK 答对不会直接得到 `INDEPENDENT`，必须经过两个 PAIR 小步和独立 VERIFY；
- `INDEPENDENT` 不会因为一次模糊回答被降级；明确失败会进入 `NEEDS_REVIEW`；
- 重新学习会保留旧历史与旧状态证据，新证据可再次改变状态；
- 迁移时只回填已有教学进度和已验证完成的知识点；历史手工完成（`legacy_manual`）不推断为已掌握。

## 5. 错题与薄弱点

### 5.1 什么会生成错题

- CHECK：`INCORRECT`、`PARTIAL`；
- PAIR：`INCORRECT`、`PARTIAL`；
- VERIFY：`FAILED`、`NEEDS_REVIEW`。

不会生成错题：自由提问、普通对话、`UNCLEAR`（证据不足，不视为错误）、CHECK/PASSED 的正确回答。

### 5.2 归并规则

`dedupe_key = sha1(知识点 ID + 阶段 + 归一化用户回答 + 归一化理解偏差)`：

- 相同知识点、相同阶段、相同错误 → 同一条 `mistake_records`，`occurrence_count + 1`，更新最近一次上下文；
- 每次发生仍写一条 `mistake_occurrences`，保留当次问题、回答、评价与反馈；
- 已标记「已理解」的错题如果再次发生，会重新打开并累加次数。

### 5.3 处理状态

- `open`：待处理；
- `understood`：用户标记已理解，记录 `resolved_at`；
- 「重新练习」只打开对应课程/知识点的教室，不自动清空错题或伪造掌握状态。

## 6. 学习历史与报告

### 6.1 学习历史

- 列表按活动开始时间倒序，支持课程、知识点、时间范围筛选与分页；
- 每条记录包含课程、知识点、开始/结束时间、有效时长、到达阶段、完成阶段、结果、尝试与提示次数；
- 详情包含阶段事件、问答与评价、当次错误与补讲、最终总结；
- 历史直接读取 `learning_activities`，不把页面停留时间当作学习时长。

### 6.2 学习档案总览

- 累计有效学习时间 = `SUM(learning_activities.active_seconds)`；
- 学习过的课程 = 有活动或有非「未学习」知识点的课程；
- 已完成 / 学习中 / 待复习来自知识点学习状态与掌握状态；
- 最近学习时间取课程与活动最后心跳的较大值；
- 本周统计以本地时区周一 00:00 为起点。

### 6.3 学习报告

- 本周学习时间：本周开始的活动 `active_seconds` 之和；
- 本周涉及知识点：本周活动去重知识点数；
- 本周完成知识点：本周 `mastery_history` 首次变为 `INDEPENDENT` 的去重知识点数；
- 薄弱点：`open` 错题按发生次数与最近发生排序；
- 最近进展：最近掌握状态变化；
- 课程报告：课程进度、章节进度与本周时长。

报告只展示统计事实。本阶段不提供 AI 学习画像或预测；若后续增加 AI 建议，必须与统计事实分区展示。

## 7. API

统一前缀 `/api/v1`，响应结构 `{ code, message, data }`。

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| POST | `/learning/activities/start` | 开始或复用学习活动 |
| POST | `/learning/activities/{id}/heartbeat` | 上报有效时长；返回 `closed` 表示空闲已结束 |
| POST | `/learning/activities/{id}/finish` | 结束活动 |
| GET | `/learning/resume` | 最近一次可恢复位置（已完成知识点自动指向下一个） |
| GET | `/learning/sessions/{id}/breakpoint` | 读取断点快照 |
| PUT | `/learning/sessions/{id}/breakpoint` | 保存草稿与输入模式，`clientSeq` 防旧覆盖新 |
| GET | `/learning/overview` | 学习档案总览 |
| GET | `/learning/courses` | 按课程的学习进度与当前位置 |
| GET | `/learning/mastery` | 掌握状态分布与按课程/章节明细 |
| GET | `/learning/history` | 学习历史列表 |
| GET | `/learning/history/{activityId}` | 一次学习的详细过程 |
| GET | `/learning/mistakes` | 错题/薄弱点列表与筛选 |
| GET | `/learning/mistakes/{id}` | 错题详情与发生历史 |
| PATCH | `/learning/mistakes/{id}` | 标记已理解 / 重新打开 |
| POST | `/learning/mistakes/{id}/practice` | 返回重新练习所需路由与会话 |
| GET | `/learning/report` | 本周学习报告，可传 `courseId` |

校验与安全：

- 所有课程/知识点/会话 ID 都校验存在性与归属，跨课程组合返回 404；
- 不返回 API Key 或模型配置密文；
- 关键写入在事务中完成；断点写入使用序号防覆盖；
- 学习数据默认保存在本机 `data/`，不自动上传。

## 8. 迁移与备份

- schema 版本从 5 升到 6；
- 增量迁移只加表、加列，不删用户数据；
- `_backfill_mastery()` 幂等：只填补 `NOT_STARTED`，并写入一条迁移来源的 `mastery_history`；
- 删除课程会级联删除该课程的学习活动、错题、断点；掌握历史通过 `SET NULL` 保留知识点维度记录（知识点本身随课程删除时一并清理）；
- 建议在升级前备份 `data/mastery_lab.db`，升级后可用同一文件回滚到旧版本（旧代码会忽略新表/新列）。

## 9. 已知限制

- 活动记录以会话为粒度，一次活动对应一个知识点；同一天多次进入会产生多条活动；
- 跨周活动全部计入开始所在周，不做按天/按周切分；
- 空闲阈值固定为 15 分钟（活动）与 5 分钟（前端计时），暂未提供设置项；
- 单机单用户模型，不提供多用户隔离与云端同步；
- 「重新练习」不会自动创建新轮次，用户进入教室后可主动点击「重新学习」。
