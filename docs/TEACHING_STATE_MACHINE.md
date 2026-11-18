# P1.4 教学状态机设计

2026-11-17：用户确认采用后端六阶段控制，旧手工完成保留来源，不计为 VERIFY 通过。本文先记录实施契约，实际验收结果另见 P1.4 测试报告。

## 状态与门槛

```text
TEACH --讲解完整生成、继续--> DEMO --案例完整生成、继续--> CHECK
CHECK --CORRECT--> PAIR --两个小步骤均 CORRECT--> VERIFY
VERIFY --PASSED 且有实际回答证据--> NEXT --用户继续--> 下一知识点 TEACH
CHECK PARTIAL -> CHECK 补充检查；UNCLEAR -> 保留问题并要求澄清
CHECK INCORRECT -> TEACH；PAIR INCORRECT/PARTIAL -> 当前小步骤
VERIFY NEEDS_REVIEW/FAILED -> PAIR（保留薄弱点与提示记录）
```

阶段状态：PENDING / ACTIVE / WAITING_USER / COMPLETED / BLOCKED；暂停用独立 paused 字段，不丢失原阶段状态。
TEACH/DEMO 完整成功才可继续；中断、无内容或异常不视为完成。CHECK/PAIR/VERIFY 只允许一个当前待答任务。每轮 PAIR 至少两个小步骤，由程序计数，不采纳 AI 提出的跳阶段建议。

## 程序边界

- TeachingStateMachine 统一处理允许动作、前置条件、乐观版本校验、事务提交及审计事件。
- 模型产生当前阶段内容或经过 Pydantic 校验的任务/评价 JSON。模型没有 current_stage 写权限，未知字段和无效枚举拒绝。
- 自由提问与提交回答分开；提问不判分、不推进阶段。在 VERIFY 获取提示、换题或寻求解释会计入帮助记录。
- 结构化题目/评价先完整校验再显示；TEACH/DEMO 与自由答疑沿用真实增量 SSE，不模拟打字。
- 评价中的引用必须来自实际提交；“我懂了”等空泛确认不能通过。PASSED 后有提示只能标记 GUIDED_PRACTICE，不能标记 INDEPENDENT。
- 题目原文、回答、反馈、评价、版本、阶段开始/结束及返回原因可追溯。生成失败不生成成功评价，不推进阶段。
- 保留 P1.3 会话与消息 ID；教学重生成采用追加消息，不删除被证据引用的历史。

## 持久化与并发

新增 teaching_progress、teaching_operations、teaching_events、teaching_evaluations；knowledge_points 增加 completion_source。
每会话一条进度。操作使用 requestId + expectedRevision；同一请求重放不再次计数/调用模型，过期版本或并发返回 409。
模型调用不占用数据库写事务；操作登记、回答与计数原子提交；模型结果、阶段迁移、评价与课程进度原子提交。失败保留问题和已有历史。
启动时将未完成操作恢复为 interrupted，不假装已生成；有待答题恢复 WAITING_USER，否则恢复 BLOCKED 并允许重试。
SQLite 仍单机单 worker，复用现有进程内取消机制，并用数据库版本条件更新兜底。只加表/加列，启动前使用 SQLite backup 备份现有库。

## 旧数据兼容

旧 completed 标记为 legacy_manual，进度数值不静默清零，但界面明确“历史手工完成，未教学验证”。旧对话保留，第一次启用新流程从 TEACH 开始，不从旧自然语言猜阶段。
新完成只能由 VERIFY 成功写入 completion_source=verified。课程内/扁平手工状态接口及 mastered 别名都必须经过同一门槛。课程详情保留未学习/学习中/待复习操作，完成入口改为进入教室学习验证。
已完成知识点重进显示总结，继续下一点是显式操作；最后一点返回 courseComplete，不拼不存在的地址。明确重新学习才新开教学轮次，旧证据保留。

## API 契约

- GET `/api/v1/classroom/sessions/{id}/teaching`：读取/初始化教学进度，camelCase。
- POST `/api/v1/classroom/sessions/{id}/teaching/actions`：SSE 教学动作。
- POST `/api/v1/classroom/sessions/{id}/teaching/control`：暂停/继续/下一知识点/重新学习。
- GET `/api/v1/classroom/sessions/{id}/teaching/events`：阶段事件与评价证据。

动作请求：`{requestId: UUID, expectedRevision: number, action: string, content?: string}`，不接受 currentStage。
流式动作：START、CONTINUE、ANSWER、ASK、EXPLAIN_AGAIN、CHANGE_EXAMPLE、GIVE_HINT、DONT_UNDERSTAND、TRY_MYSELF、REGENERATE。
控制动作：PAUSE、RESUME、NEXT、RESTART。
SSE 复用 meta/delta/done/error；meta 与 done 增加 teaching。done.message 仍为 ChatMessage。控制返回 `{teaching, nextKnowledgePointId, courseComplete}`。

TeachingState 字段：sessionId、revision、currentStage、stageStatus、paused、goal、nextStep、allowedActions、completedStages、currentQuestion、pairStep、pairTotalSteps、checkAttempts、pairAttempts、verifyAttempts、hintCount、verifyHintCount、backtrackCount、masteryState、verificationResult、legacyCompletion、summary、errorMessage、completedAt、lastActivityAt。

## 前端与验证

教室顶部独立教学流程面板，展示六阶段/目标/状态/下一步，操作只使用后端 allowedActions。输入明确区分“提交回答”与“自由提问”。不因进入教室、用户点按钮或生成结束自动标记掌握。
阶段反馈后若进入 PENDING，页面自动开始本阶段补讲/任务；暂停或切知识点后不得触发旧阶段生成。
PAIR 使用代码片段/文本，不声称运行通过；P2 可以复用 ANSWER 的结构化提交边界，当前不接受运行结果伪证据。

先写状态门槛、幂等、无效 JSON、中断、暂停、恢复、旧数据迁移测试。模拟/真实模型结果分开，当前默认模型 preflight HTTP 429，不反复调用。真实验收失败不得写全绿。
