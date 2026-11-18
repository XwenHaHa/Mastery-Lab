# P1.4 Teaching Flow Implementation Plan

> 按 executing-plans / test-driven-development 执行，适合并行的前端工作在固定 API 契约后委派；不提交 Git，不创建分支。

**Goal:** 六阶段教学过程受后端规则控制，评价有证据、操作可恢复，不能手工跳过 VERIFY。

**Architecture:** `docs/TEACHING_STATE_MACHINE.md` 为已确认设计细化。复用会话、取消登记、SSE、模型密钥、Markdown 与课程进度；新增独立状态/操作/评价/事件层。

**Tech Stack:** 现有 FastAPI / Pydantic / SQLAlchemy / SQLite / Vue 3，无新运行依赖。

## 文件边界

- `apps/api/app/db/models.py`、`db/__init__.py`、`main.py`：新表、兼容列与启动恢复。
- `apps/api/app/schemas/teaching.py`、`services/teaching_protocol.py`：严格请求、结构化任务/评价与分阶段提示词。
- `apps/api/app/services/teaching_state.py`：唯一状态服务，版本条件更新、幂等、阶段/证据写入。
- `apps/api/app/api/v1/teaching.py`：流式协调、控制接口、错误映射，复用 llm_client。
- `classroom.py` / `classroom_service.py` / `course_service.py` / `schemas/course.py`：旧端点兼容、防完成绕过及来源输出。
- `apps/web/src/components/TeachingFlowPanel.vue`、`views/ClassroomView.vue`、`views/CourseDetailView.vue`、`api/types.ts`、`api/index.ts`、`api/classroomStream.ts`：分阶段教学交互。
- `docs/qa/p14_*`：隔离单元、接口、迁移/重启、浏览器和真实模型检查。

## 任务与检查点

- [ ] 先编写并运行 `p14_backend_test.py`，新教学接口应 404，旧完成绕过测试应失败。
- [ ] 加表/加列与版本 5；旧库副本升级两次，检查会话、消息、课程行数及内容保持不变。
- [ ] 实现 TeachingStateMachine：`begin(session_id, payload)` 条件更新版本；`finish(operation, result)` 单事务提交消息/评价/事件/进度；`fail(operation)` 恢复待答或阻塞状态。
- [ ] 评价与任务使用 `model_validate_json`，额外字段禁止；ANSWER 才评价，ASK 不推进；测试 INCORRECT/PARTIAL/UNCLEAR 与非法结果不越级。
- [ ] 接入 SSE，完整成功后才能完成阶段；停止/重启/写入异常均不推进；旧 regenerate 不删除教学证据。
- [ ] 前端接入固定契约并覆盖切点/暂停竞态、无模型、窄屏、阶段操作禁用和旧完成来源。
- [ ] 运行离线回归、构建、浏览器截图；真实模型仅针对具名测试教材，区分 429/失败与模拟通过。
- [ ] 更新 PRD/ARCHITECTURE/DATABASE/DEVELOPMENT_PLAN、API 文档、状态图和交付报告。

验证入口：`apps/api/.venv/Scripts/python.exe docs/qa/p14_backend_test.py`；`python docs/qa/p13_validate.py`；`python docs/qa/p14_ui_flow.py`（Playwright 环境同 P1.3）。

不得：静默删库、把旧 completed 当 VERIFIED、在事务内等模型、让客户端直接设置阶段、伪造运行结果/真实测试。
