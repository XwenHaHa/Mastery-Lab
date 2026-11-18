# P1.3 AI 学习教室交付报告

日期：2026-11-17。范围以 `plan/P1.3 AI 学习教室与智能教学对话开发任务.md` 为准。

## 1. 交付结论

P1.3 基础教学链路已实现并实际运行，保留既有 P0/P1.1/P1.2 架构，没有重新初始化。工作区原已有部分 P1.3 雏形，本轮完成缺陷修复、交互补全、验收和文档同步。

**真实模型 API 验收 26/26 通过；不能宣称真实浏览器重复验收全程通过**：首轮已完成 8 个核心步骤，后续窄屏测试修正后重跑遇到上游长等待与 HTTP 429。最终完整 UI 回归使用明确标注的本地模拟上游完成，未将模拟输出计为真实教学效果。

没有开发 P1.4 教学状态机、掌握度判断、Monaco 或代码执行。

## 2. 功能清单

- 课程详情「开始学习」进入知识点教室；248px 课程目录、教程式正文、可折叠学习信息三栏。
- 当前课程/章节/知识点、手工学习状态、已学习数量、加权进度与当前模型可见；模型可以切换，生成中禁用。
- 新知识点由老师主动讲解：概念/用途/类比/完整案例/逐句解释/预期输出/常见错误；不强迫用户先写代码。
- 六个快捷入口与自由提问，结合教材和已有对话。Enter 发送，Shift+Enter 换行，输入限制 8000 字。
- 真实 POST SSE 增量，Markdown、代码高亮、KaTeX；旧请求被取消后不能继续污染新知识点。
- 停止会取消等待中的上游读取并保存部分正文；支持重生成、刷新恢复、多标签页同步已保存内容。
- 每课程/知识点独立会话、课程归属校验、历史分页、同会话并发 409、缺模型与安全错误提示。
- 历史保留首次主动讲解；最长 20 条/14000 字，教材正文最多 6000 字；截断不会修改数据库原文。
- 复用后端 DPAPI/Fernet 模型密钥，不向浏览器返回明文；过滤上游错误，输出跨 chunk 检查当前密钥，屏蔽 httpx URL 日志。

## 3. 实际验证

| 检查 | 实际结果 | 证据 |
| --- | --- | --- |
| 环境 | Node 22.18.0 / Python 3.13.1 / Git 2.42.0；目录无 .git | `task_plan.md` |
| 后端隔离测试 | 26/26（含教室手工状态同步补充测试） | `qa/p13-backend-test.log` |
| 前端 SSE/安全渲染/公式 | 6/6 | `qa/p13-frontend-test.log` |
| Vue TS + Vite 构建 | 通过；保留既有 >500KB chunk 警告 | `qa/p13-build-test.log` |
| 真实模型探测 | HTTP 200，回复“可用”，10910ms | `qa/p13-model-probe.json` |
| 真实模型教学 API | 26/26 | `qa/p13-real-result.json` |
| 真实浏览器核心流程 | 首轮 8 步完成；后续完整重跑因网关 429 受限 | 本节说明与真实截图；`qa/p13-ui-real-limited.json` |
| 模拟上游完整浏览器 | 11 步通过，0 pageerror | `qa/p13-ui-mock-result.json` |
| P0/P1.1/P1.2 接口 | 52/52 | `qa/p12-api-result.json` |
| P1.2 浏览器回归 | 17 步通过 | `qa/p12-ui-flow-result.json` |
| 本地前后端 | 最终 8000 与 5173 均 HTTP 200，Swagger 8 个教室操作 | `qa/p13-final-runtime.json`、`qa/p13-startup.log` |
| SQLite 最终只读检查 | schema=4，quick_check=ok，无外键违例 | `qa/p13-final-runtime.json` |

模拟测试覆盖等待首段的超时、等待上游时取消、并发生成、切模型冲突、前端跨 chunk UTF-8/CRLF、流末尾错误、密钥跨 chunk 隐藏等难以稳定触发的情况。真实 HTTP 429 的错误展示也已观察到。

最终复核额外复现并修复崩溃残留：新一轮生成开始前，将旧 streaming 消息归为 interrupted，不再把旧回答误显示成仍在生成。

真实配置模型名：`deepseek-v4.1-flash-free`（读取用户配置，不在产品代码硬编码）。每次教学都来自专用测试教材 `qa/fixtures/p13-python.md`，不把用户原有教材拿去验收。

| 真实调用 | 增量数 | 首段毫秒 | 总毫秒 | 结果 |
| --- | ---: | ---: | ---: | --- |
| 变量主动教学 | 175 | 9969 | 28159 | completed，包含 price=37、完整代码与预期输出 |
| 追问 price/total/74 | 173 | 8241 | 14400 | completed，引用前一例子 |
| 慢讲并停止 | 4 | 6371 | 6533 | interrupted，部分正文落库 |
| 重新生成 | 119 | 11665 | 14865 | completed |
| 切换列表与索引 | 227 | 13961 | 20693 | completed，使用 books 与索引上下文 |

停止请求发出约 161ms 后流结束；可能已有网络中途的增量到达，UI 在 abort 后不再追加。会话恢复为同一个 ID，5 条对话顺序和正文一致。

真实浏览器首轮完成：从课程详情进入、面板折叠、第三知识点主动生成、停止及刷新精确恢复、Enter/换行/代码块、快捷解释关联 stock、KaTeX 公式、切回首知识点恢复历史。随后窄屏测试试图打开一个已打开的目录，修正测试后重跑遭遇服务长等待/429。新增首段 60 秒/总计 240 秒期限，并以模拟服务验证完整交互；没有自动消耗用户额度无限重试。

## 4. 截图

真实模型/实际浏览器截图位于 `docs/review/p1-3/`：

- `01-classroom-restored-dark.png`：深色三栏与真实历史。
- `02-real-streaming.png`：首次主动讲解的实际增量。
- `03-stopped-restored.png`：停止后恢复。
- `04-code-example.png`：完整 Python 案例和代码高亮。
- `05-contextual-code-explanation.png`：结合上一案例解释代码。
- `06-math-rendering.png`：真实输出公式。
- `07-classroom-light.png`：浅色主题。
- `10-real-http429.png`：真实网关限流提示，不是模拟结果。

`mock-*.png` 是模拟上游的截图，包括窄屏布局、切点竞态与模拟错误，文件名前缀明确区分。

## 5. API / 数据库 / 提示词

- 8 个接口说明与 SSE 样例：`API_CLASSROOM.md`；Swagger 实际包含 classroom 标签。
- 数据结构：沿用雏形中的 `learning_sessions` / `chat_messages`，schema=4。课程/知识点删除级联清理；模型删除 SET NULL。没有重建用户库。
- 重生成替换末条助手消息，不提供历史版本。分页 afterId 不作为重生成刷新机制。
- 教学提示词：`apps/api/app/services/teaching_prompt.py`，分系统角色、课程教材、知识点、历史和当前问题。
- 进度不由模型自动改变，仍取 P1.2 的四态手工记录；“已学习”不等于“已掌握”。

## 6. 文件清单

本轮修改的产品文件：

```text
apps/api/.env.example
apps/api/app/main.py
apps/api/app/core/config.py
apps/api/app/api/v1/classroom.py
apps/api/app/services/classroom_service.py
apps/api/app/services/teaching_prompt.py
apps/api/app/services/stream_registry.py
apps/api/app/services/llm_client.py
apps/web/src/api/classroomStream.ts
apps/web/src/views/ClassroomView.vue
apps/web/src/views/SettingsView.vue
```

新增验收代码：`docs/qa/p13_backend_test.py`、`p13_frontend_test.mjs`、`p13_real_check.py`、`p13_ui_flow.py`、`p13_mock_gateway.py`、`p13_validate.py`、`fixtures/p13-python.md`。测试日志/JSON 和截图在对应 qa/review 目录。

修改 README、PRD、ARCHITECTURE、DATABASE、DEVELOPMENT_PLAN；新增 `API_CLASSROOM.md`、本报告、`task_plan.md`、`findings.md`、`progress.md`。

未重建的已有 P1.3 文件：ORM 模型、Schema、前端类型、路由、API 索引、Markdown/高亮与 KaTeX 集成、课程详情入口。本轮在已有实现上补全，不把原有文件冒称为全部新建。

## 7. 运行与复验

启动：根目录执行 `powershell -ExecutionPolicy Bypass -File scripts\dev.ps1`。前端 `http://127.0.0.1:5173`，API `http://127.0.0.1:8000/docs`。课程中心 → 课程详情 → 开始学习。

离线验证：`python docs/qa/p13_validate.py`，内部调用项目虚拟环境 Python、Node 测试与构建，生成 UTF-8 日志和退出码 JSON。

真实验证：`apps\api\.venv\Scripts\python.exe docs\qa\p13_real_check.py --keep-course`，随后可运行 `python docs/qa/p13_ui_flow.py`。测试会产生真实 API 请求，需可用额度。Playwright 与 Chromium 是 QA 环境依赖，不是产品运行依赖；本机使用 `E:/tmp/playwright-python` 与 `E:/tmp/ms-playwright`。

本轮保留一门专用“P1.3 教学验收 · Python 入门”课程供查看，包含真实与明确标注的模拟记录；原有三门课程未删改。临时模拟模型已删除，返回默认真实配置；测试课程可以在课程中心手动删除。

环境问题：CLI 环境曾有 Path/PATH 两个大小写键，PowerShell Start-Process 报错；以去重的子进程环境启动，未修改系统环境。沙箱不能正确枚举后台进程，已申请权限在沙箱外完成停止/启动。应以实际健康检查和日志确认，不据单独的沙箱 PID 查询判断服务消失。

最终一次带日志捕获的重启命令等待超时，后端实际已启动；随后单独运行前端脚本恢复，重新完成模拟 UI 11 步和双端 HTTP 检查。最终运行状态以 `qa/p13-final-runtime.json` 为准。

## 8. 遗留风险与范围边界

1. 用户网关已返回真实 429；稳定完成整套真实浏览器复验需要恢复额度/解除限流。本轮没有伪造全绿结论。
2. 配置使用 HTTP 而非 HTTPS 时，密钥与教材在网络传输中没有 TLS 保护。推荐改用 HTTPS；模型调用会发送教材节选和对话，不是全程离线。
3. 单用户、单 worker；无云端鉴权/多租户隔离。不要公开监听，分发前补本机访问令牌与来源校验。
4. 教学纪律由提示词约束，不保证每次输出严格只有一个问题或绝无幻觉；P1.4 再做结构化输出与状态校验。
5. Mermaid 未引入，仅代码降级；不支持执行示例，预期输出不是真实运行结果。
6. 浏览器会话详情仍一次加载全部历史，长会话可进一步分页/虚拟滚动；发给模型的上下文已限量。
7. 主进程异常结束可能丢最后 1.2 秒内尚未检查点落库的片段；中断/正常退出即时落库。
8. 既有 Element Plus 首屏包约 1.09MB；构建警告未作为无关优化扩大范围。
9. 无 Git 仓库，未创建提交，也无法提供 Git 基线 diff；文件清单来自实际操作。外部审查代理遇 429，无审查结论，已进行本地复核与自动化验证。

## 9. P1.4 建议

保持现有会话和流服务边界，在服务端引入版本化教学阶段与事件，先实现 TEACH/DEMO/CHECK；证据关联消息、用户回应和知识点，不让模型直接写掌握度。把“一次一个待答问题”和显式阶段迁移变为可测规则。PAIR/RUN/VERIFY 等依赖执行证据的环节留到 P2。迁移旧对话时只补阶段，不推断用户已掌握。

## 10. 教室内学习完成标记（2026-11-17 补充）

用户反馈进入教室后需要退出才能标记完成。本次在当前知识点标题旁加入「标记为已完成」，完成后可「改为学习中」，保留独立的上一点/下一点按钮。保存后同步目录、进度与已学习数量，不清空对话/草稿、不刷新或跳转页面。AI 生成结束不自动改变学习状态。

沿用现有 `PATCH /api/v1/courses/{course_id}/knowledge-points/{point_id}/status`，不修改后端产品代码或数据库结构。进度显示统一读取课程数据，避免旧的聊天会话快照覆盖保存结果；保存中防重复提交，跨课程响应被隔离，失败保留原显示并支持重试。没有新增依赖。

实际验证：

- 先运行新增浏览器回归，因缺少完成按钮按预期失败，证据 `qa/classroom-status-ui-red.json`。
- 实现后浏览器 **8/8** 通过，0 pageerror、0 意外 API 请求：完成/撤回、刷新恢复、目录与双侧进度/数量同步、失败重试、重复提交、保存期间切知识点/课程、旧流恢复快照隔离、390px 窄屏操作。证据 `qa/classroom-status-ui-result.json`。
- 浏览器 API 为明确隔离的模拟响应；未写入用户课程、未调用真实模型。新截图 `review/p1-3/status-completed-mock.png`、`review/p1-3/status-narrow-mock.png` 已人工查看。
- 另新增真实 FastAPI + 临时 SQLite 集成测试，验证完成/改回学习中后课程详情与会话进度一致，重开保持会话 ID 与全部消息，掌握度不变。后端合计 **26/26**，前端原有 **6/6**，Vue 类型检查与 Vite 构建通过；既有大包警告仍在。
- 本轮没有重跑真实模型教学验收，前文真实 API/真实浏览器限流说明不变。外部代码审查再次遇 429，未获得独立审查结论；已完成本地代码复核和自动化验证。

本轮文件：`apps/web/src/views/ClassroomView.vue`、`docs/qa/classroom_status_ui.py`、`docs/qa/p13_backend_test.py`、`README.md`、本报告及 `superpowers/plans/2026-11-17-classroom-learning-status.md`。
