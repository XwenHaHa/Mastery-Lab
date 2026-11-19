# P1.6 通用教学架构审计报告

- 审计日期：2026-11-19
- 审计范围：`apps/api`（FastAPI/SQLAlchemy）、`apps/web`（Vue 3）、`docs/qa` 测试资产、现有 SQLite 数据库
- 审计方式：**只读检查**。审计阶段未修改代码、数据库结构或用户数据；后续 A–E 实施见下方状态。
- 实施状态：**P1.6-A / B / C / D / E / F / G 已实现并回归**（2026-11-19）。
- 验证入口：`apps/api/.venv/Scripts/python.exe -m pytest`（隔离临时 SQLite），前端 `npm run typecheck` / `npm run build`。
- 需求基准：`plan/P1.6 通用教学架构审计与改造方案.md`

---

## 0. 结论摘要

### 0.1 总体判断

现有系统可以演进为通用教学平台，**不需要推倒重写**。

P1.4/P1.5 已经具备通用平台最难得的三件事：

1. **服务端控制教学阶段**：AI 只能返回内容或结构化 JSON，不能直接写阶段、不能宣布通过。
2. **可靠的状态转换与审计**：乐观版本号、`requestId` 幂等、事务提交、事件与评价可追溯。
3. **学习档案闭环**：会话、消息、学习活动、掌握历史、错题、断点续学都已落库。

真正的耦合不在“控制面”，而在**教学语义层**：

- 阶段名称与阶段分支把 `TEACH/DEMO/CHECK/PAIR/VERIFY/NEXT` 写死在多处；
- 系统提示词和阶段指令把 AI 固定成“技术老师”，DEMO 固定为代码案例；
- 题目结构固定为 `instruction/question/rubric/hint/summary` 五字段，无法表达选择题、填空、排序、计算、实操、音视频等；
- 知识点只存一段 Markdown 正文，没有素材/图片/图表/来源定位；
- 前端教学面板、输入框文案、快捷动作默认面向代码。

### 0.2 本次审计的实测基线

| 项目 | 实测值 |
| --- | --- |
| 后端导入 | `python -c "from app.main import app"` 成功 |
| 后端 API 路由 | 48 条 `/api/v1/*` |
| SQLite 业务表 | 20 张（不含索引/自动索引） |
| 课程 / 章节 / 知识点 | 4 / 10 / 19 |
| 学习会话 / 消息 | 5 / 76 |
| 教学进度 | 3 条：`DEMO·BLOCKED`、`NEXT·COMPLETED`、`TEACH·BLOCKED` |
| 掌握状态 | `INDEPENDENT` 1，`NOT_STARTED` 18 |
| 学习状态 | `completed/verified` 1，`in_progress` 2，`not_started` 16 |
| 学习活动 / 错题 / 断点 | 6 / 2 / 3 |
| 自动化测试套件 | **不存在**（无 pytest/vitest 配置；验证依赖 `docs/qa/*.py` 与报告） |

> 这 3 条教学进度说明：迁移方案必须能处理“进行中（TEACH/DEMO/BLOCKED）”和“已完成（NEXT/COMPLETED）”两类真实数据，不能只考虑新库。

### 0.3 推荐改造路线

采用“**分层解耦 + 双轨兼容 + 小步迁移**”，不做一次性重写：

1. 先抽出**教学活动协议**和**阶段契约**（纯新增模块，不改旧行为）。
2. 用**特性开关**启用新 8 阶段流程；旧会话走兼容适配器。
3. 提示词改为“通用骨架 + 学科策略 + 活动指令”三层组装。
4. 前端先增加通用活动渲染器，代码演示只是其中一种活动。
5. 最后再接入图片/音频/视频、OCR、代码执行等重能力。

详细阶段拆分见第 6 节；教学模型设计见 `docs/P16_GENERAL_TEACHING_DESIGN.md`。

---

## 1. 审计方法与证据

### 1.1 已检查模块

| 层 | 文件 |
| --- | --- |
| 状态机 | `apps/api/app/services/teaching_state.py` |
| 教学协议/提示词 | `apps/api/app/services/teaching_protocol.py`、`teaching_prompt.py` |
| 数据模型 | `apps/api/app/db/models.py`、`db/__init__.py` |
| 课堂服务 | `apps/api/app/services/classroom_service.py` |
| 学习档案 | `services/learning_record.py`、`mastery.py`、`mistakes.py`、`breakpoints.py`、`archive.py` |
| 教材导入 | `services/materials.py`、`md_parser.py`、`pdf_parser.py` |
| API | `api/v1/classroom.py`、`teaching.py`、`learning.py`、`courses.py`、`models.py` |
| Schema | `schemas/teaching.py`、`classroom.py`、`course.py` |
| 前端 | `views/ClassroomView.vue`、`components/TeachingFlowPanel.vue`、`utils/markdown.ts`、`utils/highlight.ts`、`api/types.ts` |
| 测试资产 | `docs/qa/*.py`、`docs/TEST_REPORT_P1.x.md`、`docs/qa/*.json` |

### 1.2 实际执行过的检查

```text
1. 读取项目结构与全部核心源码（未修改）。
2. 后端导入检查：from app.main import app → 成功，48 条 API 路由。
3. 只读查询当前 SQLite：
   - 表清单 20 张；
   - 关键表行数；
   - teaching_progress 阶段分布；
   - knowledge_points 掌握/学习状态分布。
4. 检索全部 “Python/代码/技术老师” 等关键词，确认耦合位置。
5. 检查 package.json / requirements.txt：没有测试脚本、没有 pytest、没有 vitest。
```

### 1.3 本次未做的事

- 未启动前后端、未调用模型、未运行浏览器回归（本阶段只做审计与设计）。
- 未修改数据库、未执行迁移。
- 未对现有测试脚本重新跑分，仅核对测试资产是否存在及其形态。

---

## 2. 现有架构审计

### 2.1 分层与调用链

现有系统是清晰的三层结构：

```text
Vue 页面
  ClassroomView.vue
  ├─ learningApi.start/heartbeat/breakpoint   → /api/v1/learning/*
  ├─ classroomApi.openSession                 → /api/v1/classroom/sessions
  └─ teachingApi.actions/control (SSE)        → /api/v1/classroom/sessions/{id}/teaching/*
          │
FastAPI 路由
  classroom.py  (P1.3 自由对话，有 teaching_progress 时被禁止)
  teaching.py   (P1.4 六阶段教学)
  learning.py   (P1.5 档案/错题/断点)
          │
服务层
  TeachingStateMachine  → 阶段、动作白名单、评价分支、事务
  teaching_protocol     → 系统提示 + 阶段指令 + JSON 解析
  teaching_prompt       → P1.3 自由对话提示（另一套）
  classroom_service     → 会话/消息/模型解析
  mastery / mistakes / learning_record / breakpoints / archive
          │
SQLite（SQLAlchemy，WAL，单机单 worker）
```

**审计发现 A1：存在两套并行提示词系统。**

- `teaching_prompt.py` 服务 P1.3 自由对话；
- `teaching_protocol.py` 服务 P1.4 状态机。

两套都把 AI 定义为“技术老师”，且都以代码为中心。`classroom.py` 在检测到 `TeachingProgress` 后拒绝自由对话（`classroom.py#L74-L78`），因此实际教学中只有 `teaching_protocol.py` 生效，但两套角色定义长期并存会造成维护分叉。目标架构应合并为一个“提示词组装器”。

### 2.2 数据模型

现有 20 张表：

| 表 | 作用 | 与本阶段关系 |
| --- | --- | --- |
| `model_configs` | 模型接入配置（密钥加密） | 通用，复用 |
| `app_settings` | K/V，schema 版本 | 复用，可存迁移标记/策略开关 |
| `courses` | 课程、来源文件、状态、图标 | 需加学科/策略关联 |
| `chapters` | 章节 | 通用 |
| `knowledge_points` | 标题、摘要、Markdown 正文、状态、掌握态 | **核心改造点**：需素材/活动计划/长期掌握 |
| `learning_sessions` | 每（课程, 知识点）一条会话 | 通用，复用 |
| `chat_messages` | 用户/助手消息 | 需增加活动关联与结构化内容 |
| `teaching_progress` | 阶段、计数、当前问题、掌握态 | **核心改造点**：阶段与单一问题模型 |
| `teaching_operations` | 幂等操作日志 | 通用，复用 |
| `teaching_events` | 阶段迁移事件 | 通用，复用 |
| `teaching_evaluations` | 每次评价证据 | 通用，复用 |
| `learning_activities` | 一次学习活动（时长/心跳） | 通用；**注意命名冲突** |
| `mastery_history` | 掌握状态变更历史 | 通用，扩展证据类型 |
| `mistake_records` | 错题/薄弱点归并 | 基本通用 |
| `mistake_occurrences` | 每次错误明细 | 通用 |
| `learning_breakpoints` | 断点快照 | 需兼容阶段值 |
| `learning_events` | 学习层事件 | 通用，可承载活动事件 |

关键字段现状：

- `knowledge_points.content` 是**单个 Markdown 文本字段**（`models.py#L148`），没有素材引用、来源页码、图表数据。
- `knowledge_points.code_count`、`chapters.code_count`、课程汇总 `codeCount` 都是编程学科元数据（`models.py#L123/L150`）。
- `knowledge_points.mastery_level` 字段存在但**从未写入**（`models.py#L153`），可复用为长期掌握等级。
- `teaching_progress.current_question/rubric/hint` 只能承载**一个待答问题**（`models.py#L246-L249`）。
- `teaching_progress.pair_step` 与 `pairTotalSteps=2` 把 PAIR 固定为两步（`teaching_state.py#L106`）。
- `LearningActivity` 已被占用为“学习会话活动/计时”，**新教学活动不能复用该名称**。

### 2.3 教学状态机

核心逻辑位于 `TeachingStateMachine`：

| 机制 | 现状 | 评价 |
| --- | --- | --- |
| 阶段集合 | `STAGES = ("TEACH","DEMO","CHECK","PAIR","VERIFY","NEXT")`（`teaching_state.py#L14`） | 硬编码 |
| 阶段目标 | `GOALS` 字典（`#L15-L22`），含“代码片段” | 编程耦合 |
| 动作白名单 | `allowed()`（`#L70-L87`）按阶段与状态返回 | 机制可靠，需泛化 |
| 前进 | `CONTINUE/TRY_MYSELF` 固定 `TEACH→DEMO→CHECK`（`#L178-L182`） | 硬编码 |
| 回退 | `move()` 特殊处理 `target=="PAIR" → UNDERSTANDING`（`#L140-L144`） | 阶段语义写死 |
| 阶段完成 | `complete_stage()` 写入 `completed_stages`（`#L156-L161`） | 通用 |
| 任务生成 | `kind=="task"` 只产出五字段题目 | 结构过窄 |
| 评价分支 | `apply_evaluation()` 直接按 `CHECK/PAIR/VERIFY` 分支（`#L246-L339`） | **核心耦合** |
| ANSWER 计数 | `{"CHECK":"check_attempts","PAIR":"pair_attempts","VERIFY":"verify_attempts"}[stage]`（`#L192`） | 新阶段会 KeyError |
| 验证通过 | VERIFY PASSED → NEXT、`learning_status=completed`、`completion_source=verified`（`#L303-L315`） | 完成门槛可靠 |
| 掌握态 | 一次 VERIFY 无提示即 `INDEPENDENT`（`#L310`） | **与“不能一次答对=长期掌握”冲突** |
| 控制动作 | PAUSE/RESUME/NEXT/RESTART（`#L368-L419`） | 通用 |
| 恢复 | 启动时把 active 操作置为 interrupted（`#L421-L425`） | 通用 |

**审计发现 A2：状态机的“控制机制”是资产，“阶段语义”是负债。**

可以保留：乐观锁、幂等、动作白名单、事务、事件、评价引用校验、服务重启恢复。

必须抽象：阶段列表、阶段目标、前进/回退规则、阶段专属计数、阶段专属评价分支。

### 2.4 提示词与上下文

| 位置 | 内容 | 问题 |
| --- | --- | --- |
| `teaching_protocol.SYSTEM`（#L12-L16） | “耐心技术老师”“未运行任何代码”“Markdown 代码围栏” | 角色与输出格式均编程化 |
| `LESSONS`（#L18-L21） | TEACH 讲概念；DEMO 给“最小代码案例” | DEMO 只支持代码 |
| task 指令（#L35-L42） | CHECK 出“概念/代码阅读理解”；PAIR“围绕先前案例完成一小步”；VERIFY 独立小任务 | 只支持问答式/编程式 |
| evaluation 指令（#L49-L53） | 评价“代码片段” | 无选择题/计算/实操评价模式 |
| `teaching_prompt.START_DIRECTIVE`（#L18-L26） | 首轮必须给“完整可运行代码案例” | P1.3 遗留，编程化 |
| `teaching_prompt.SYSTEM_ROLE`（#L28-L45） | “AI 技术老师”，代码规则 | P1.3 遗留 |
| `build_context_block`（#L61-L98） | 课程/章节/知识点/Markdown 正文 | 无素材、无来源定位、无学科策略 |

**审计发现 A3：AI 的评价能力被“文本问答”限制。**

当前 `TeachingJudgment` 的 `evidence_quote` 必须是用户回答中的逐字引用（`teaching_state.py#L251-L255`）。这对简答题合理，但无法评价选择题（选中项就是证据）、计算题（数值+步骤）、排序题（序列）、实操题（交付物）。

### 2.5 API

48 条 `/api/v1/*` 路由，核心教学接口：

| 接口 | 作用 | 改造影响 |
| --- | --- | --- |
| `POST /classroom/sessions` | 创建/恢复会话 | 可复用 |
| `POST /classroom/sessions/{id}/teaching/actions` | SSE 教学动作 | 需支持“活动级动作” |
| `POST /classroom/sessions/{id}/teaching/control` | 暂停/继续/下一点/重学 | 可复用，阶段值兼容 |
| `GET /classroom/sessions/{id}/teaching` | 教学状态 | 需返回活动与阶段契约 |
| `GET /classroom/sessions/{id}/teaching/events` | 事件与评价 | 可复用 |
| `POST /learning/activities/start|heartbeat|finish` | 学习计时 | 可复用 |
| `GET/PUT /learning/sessions/{id}/breakpoint` | 断点 | 需兼容阶段值 |
| `GET /learning/mistakes*` | 错题 | 基本可复用 |
| `GET /learning/overview|courses|mastery|history|report` | 档案 | 需扩展活动维度 |

**审计发现 A4：请求契约缺少“活动身份”。**

`TeachingAction` 只有 `requestId/expectedRevision/action/content`（`schemas/teaching.py#L9-L19`），没有 `activityId`、`activityType`、结构化答案。所有答案都被压成一段文本。目标架构需要在不破坏旧请求的前提下，增加可选字段并新增活动级接口。

### 2.6 前端

| 位置 | 现状 | 影响 |
| --- | --- | --- |
| `TeachingFlowPanel.vue#L7-L10` | 写死六阶段中文标签 | 无法展示新 8 阶段 |
| `TeachingFlowPanel.vue#L34` | “依据文本与代码片段评价，未执行代码” | 编程文案 |
| `ClassroomView.vue#L42-L49` | 快捷动作含“解释这段代码” | 编程耦合 |
| `ClassroomView.vue#L112-L119` | 又一份阶段中文映射 | 重复定义 |
| `ClassroomView.vue#L993` | 空状态“逐段解释代码” | 编程耦合 |
| `ClassroomView.vue#L1018-L1030` | 唯一输入是 textarea，占位符写“代码片段” | 无结构化答题组件 |
| `utils/markdown.ts#L1-L11` | 支持 KaTeX；**明确不支持图片/Mermaid** | 公式可用，图片/图表缺失 |
| 无 Monaco/终端 | 符合 P1.6 纪律（不得提前开发） | 暂不处理 |

**审计发现 A5：前端只有一种答题形态（文本框），没有活动渲染层。**

选择题、填空题、排序题、计算题、图片分析、音频练习都无法在当前输入区表达。

### 2.7 教材导入与解析

| 解析器 | 能做什么 | 不能做什么 |
| --- | --- | --- |
| `md_parser.py` | 标题层级 → 章节/知识点；代码围栏计数；正文原样保留 Markdown | 不提取图片、公式结构、表格结构、来源行号；无附件 |
| `pdf_parser.py` | 有文本层 PDF 抽文字；中文/编号/大写行启发式识别标题；缩进识别代码 | 扫描版报错不 OCR；不抽图片；不抽公式/表格；页码信息只用于章节兜底 |

**审计发现 A6：教材是“纯文本快照”，没有素材清单。**

`knowledge_points.content` 已经能保存公式的 Markdown/LaTeX 文本，前端也能用 KaTeX 渲染；但**图片、图表、音频、视频、PPT/Word、来源页码**没有存储位置和引用协议。

### 2.8 学习档案、错题与掌握度

| 能力 | 现状 | 评价 |
| --- | --- | --- |
| 学习时长 | 客户端心跳，服务端裁剪，空闲结束 | 通用、可靠 |
| 阶段计数 | check/pair/verify attempts、hint counts | 阶段绑定，需泛化为活动计数 |
| 掌握状态 | 6 态，由教学证据推导，写 `mastery_history` | 状态语义与阶段绑定 |
| 错题 | 归并 + 每次明细；错误类型 concept/practice/verification | 基本通用 |
| 断点 | 阶段、问题、草稿、输入模式、clientSeq | 阶段值需兼容 |
| 长期掌握 | 一次 VERIFY 无提示即 INDEPENDENT | **不满足需求“不得一次答对视为长期掌握”** |

**审计发现 A7：`mastery_level` 字段闲置。**

`knowledge_points.mastery_level` 自 P1.2 起存在但从未写入（`models.py#L153`）。可以在不新增列的情况下承载“长期掌握等级/证据强度”，比再加一个字段更稳。

### 2.9 测试现状

- 仓库根目录、`apps/api`、`apps/web` 均**没有 pytest / vitest / jest 配置或测试目录**。
- 验证资产是 `docs/qa/` 下的**一次性脚本 + JSON 结果 + 日志 + 截图**，按 P0–P1.5 分阶段存在。
- 这些脚本不是 CI 可重复执行的测试套件，也没有统一 fixture/隔离数据库约定。

**审计发现 A8：本次改造必须先补“可重复回归基线”。**

P1.6 的每次代码修改都要求真实测试结果；如果没有可重复的测试入口，后续只能继续依赖手工脚本，风险不可控。

---

## 3. 编程领域耦合清单

分类说明：

- **通用能力**：无需修改，直接复用。
- **领域耦合**：需要抽象/参数化。
- **缺失能力**：后续需要新增。
- **暂不处理**：本阶段只登记，未来阶段再做。

### 3.1 高优先级耦合（直接影响通用化）

| # | 位置 | 现状 | 分类 | 处理方向 |
| --- | --- | --- | --- | --- |
| 1 | `teaching_state.py#L14` | 六阶段硬编码 | 领域耦合 | 抽为 `StageDefinition` 注册表 + 阶段契约 |
| 2 | `teaching_state.py#L15-L22` | 阶段目标含“代码片段” | 领域耦合 | 目标由阶段契约 + 学科策略生成 |
| 3 | `teaching_state.py#L140-L144` | 回退到 PAIR 特判 | 领域耦合 | 改为通用“回退策略”配置 |
| 4 | `teaching_state.py#L178-L182` | `TEACH→DEMO→CHECK` 硬编码 | 领域耦合 | 由阶段顺序与完成条件驱动 |
| 5 | `teaching_state.py#L192` | ANSWER 计数按阶段字典取值 | 领域耦合 | 活动级计数器，未知阶段安全降级 |
| 6 | `teaching_state.py#L246-L339` | 评价分支按 CHECK/PAIR/VERIFY | 领域耦合 | 改为“活动评价结果 → 阶段完成判定” |
| 7 | `teaching_state.py#L310` | 一次 PASSED 即 INDEPENDENT | 领域耦合 | 拆分“本轮表现”与“长期掌握” |
| 8 | `teaching_state.py#L106` | `pairTotalSteps=2` | 领域耦合 | 由活动数量/阶段契约决定 |
| 9 | `teaching_protocol.py#L12-L16` | “技术老师/代码围栏/未运行代码” | 领域耦合 | 通用角色 + 学科策略注入 |
| 10 | `teaching_protocol.py#L18-L21` | DEMO 固定代码案例 | 领域耦合 | DEMO 活动类型由策略选择 |
| 11 | `teaching_protocol.py#L35-L42` | 题目指令固定问答/代码 | 领域耦合 | 按活动类型生成指令 |
| 12 | `teaching_prompt.py#L18-L45` | 另一套“技术老师”提示 | 领域耦合 | 合并为统一提示词组装器 |
| 13 | `schemas/teaching.py#L22-L28` | `TeachingTask` 五字段 | 缺失能力 | 通用 `TeachingActivity` 协议 |
| 14 | `schemas/teaching.py#L31-L39` | `TeachingJudgment` 固定枚举 | 部分通用 | 保留评价枚举，扩展评价模式 |
| 15 | `models.py#L148` | 知识点只有一段 Markdown | 缺失能力 | 增加素材引用/来源定位/活动计划 |
| 16 | `models.py#L246-L249` | 只能存一个当前问题 | 缺失能力 | 增加 `current_activity_id`，`current_question` 降级为缓存 |
| 17 | `frontend/TeachingFlowPanel.vue#L7-L10` | 六阶段标签写死 | 领域耦合 | 阶段元数据由 API 下发 |
| 18 | `frontend/ClassroomView.vue#L112-L119` | 第二份阶段映射 | 领域耦合 | 删除重复，统一来源 |
| 19 | `frontend/ClassroomView.vue#L42-L49` | 快捷动作“解释代码” | 领域耦合 | 按学科策略配置快捷动作 |
| 20 | `frontend/ClassroomView.vue#L1018-L1030` | 唯一 textarea 输入 | 缺失能力 | 通用活动渲染器 |

### 3.2 中低优先级耦合与缺失

| # | 位置 | 现状 | 分类 | 处理方向 |
| --- | --- | --- | --- | --- |
| 21 | `models.py#L123/L150`、课程汇总 | `code_count` 元数据 | 领域耦合 | 保留兼容，新增 `material_count`/`activity_count` |
| 22 | `md_parser.py#L1-L9` | 只统计代码围栏 | 缺失能力 | 增加素材清单、图片/表格/公式抽取（后续） |
| 23 | `pdf_parser.py#L1-L8` | 无 OCR/图片/公式 | 缺失能力 | P1.7+ 引入 OCR/版面解析 |
| 24 | `markdown.ts#L1-L11` | 不支持图片/Mermaid | 缺失能力 | 先做安全图片组件，再考虑图表 |
| 25 | `markdown.ts#L39-L53` | KaTeX 公式可用 | 通用能力 | 保留 |
| 26 | `mistakes.py#L29-L38` | 错误类型按阶段映射 | 领域耦合 | 改为“活动类型 + 错误类型” |
| 27 | `mistakes.py#L60-L69` | 只有 CHECK/PAIR/VERIFY 算错 | 领域耦合 | 由活动评价结果决定 |
| 28 | `mastery.py#L55-L91` | 掌握状态按六阶段推导 | 领域耦合 | 改为按“活动证据”推导 |
| 29 | `breakpoints.py#L60-L83` | 断点保存阶段值 | 领域耦合 | 阶段值兼容映射 |
| 30 | `learning_record.py#L316-L338` | 活动输出含阶段计数 | 领域耦合 | 增加通用活动计数，保留旧字段 |
| 31 | `classroom.py#L74-L78` | 有教学进度就禁止自由对话 | 通用能力 | 保留（保证证据完整） |
| 32 | `models.py#L209-L233` | 消息无活动/素材引用 | 缺失能力 | 增加可选 `activity_instance_id`、`content_blocks` |
| 33 | `models.py#L316-L365` | `LearningActivity` 名称已占用 | 通用能力 | **新表必须换名**，避免语义冲突 |
| 34 | `db/__init__.py#L51-L62` | 增量加列迁移机制 | 通用能力 | 复用，扩展迁移注册 |
| 35 | `main.py#L25` | `SCHEMA_VERSION="6"` | 通用能力 | 升级到 7 并记录 |
| 36 | 无测试套件 | 仅 `docs/qa` 脚本 | 缺失能力 | 新增 `apps/api/tests` + 前端测试入口 |
| 37 | 无学科/策略字段 | 课程不知道自己是数学还是编程 | 缺失能力 | 新增课程教学档案 |
| 38 | 无活动跳过机制 | 每个知识点都走同一套阶段 | 缺失能力 | 阶段/活动 `applicable` 判定 |
| 39 | 无代码编辑器/运行器 | 符合当前范围 | 暂不处理 | P2 再做，P1.6 不碰 |
| 40 | 无图片/音频/视频素材 | 纯文本 | 缺失能力 | 素材表 + 静态文件服务（后续阶段） |

### 3.3 统计

| 分类 | 数量 |
| --- | --- |
| 通用能力（复用） | 6 |
| 领域耦合（需抽象） | 20 |
| 缺失能力（需新增） | 12 |
| 暂不处理 | 2 |

> 注：同一文件可能有多条问题，统计按条目计。

---

## 4. 现有架构与目标架构对照

### 4.1 现有架构

```text
┌─────────────────────────────────────────────────────────────┐
│ 前端 ClassroomView                                          │
│  ├─ 六阶段硬编码标签（TeachingFlowPanel / STAGE_TEXT）       │
│  ├─ 单一 textarea 输入                                      │
│  └─ 代码导向快捷动作与文案                                   │
└──────────────────────────┬──────────────────────────────────┘
                           │ TeachingAction{action, content}
┌──────────────────────────▼──────────────────────────────────┐
│ TeachingStateMachine                                        │
│  STAGES = TEACH→DEMO→CHECK→PAIR→VERIFY→NEXT                 │
│  ├─ allowed() 白名单                                        │
│  ├─ apply_evaluation() 按阶段分支                           │
│  └─ 一次 PASSED → INDEPENDENT                               │
└───────────────┬──────────────────────────┬──────────────────┘
                │                          │
┌───────────────▼──────────────┐  ┌────────▼──────────────────┐
│ teaching_protocol            │  │ 学习档案                   │
│  “技术老师”                   │  │  learning_activities       │
│  DEMO=代码案例                │  │  mastery_history           │
│  TeachingTask 五字段          │  │  mistake_records           │
│  TeachingJudgment 固定枚举    │  │  learning_breakpoints      │
└───────────────┬──────────────┘  └───────────────────────────┘
                │
┌───────────────▼─────────────────────────────────────────────┐
│ 数据模型                                                     │
│  knowledge_points.content = 一段 Markdown                    │
│  teaching_progress.current_question = 一个问题               │
│  chat_messages.content = 一段文本                            │
└─────────────────────────────────────────────────────────────┘
```

### 4.2 目标架构

```text
┌─────────────────────────────────────────────────────────────┐
│ 前端通用活动渲染层                                            │
│  ├─ 阶段/活动元数据来自 API                                  │
│  ├─ ActivityRenderer（选择/填空/排序/计算/简答/代码/音视频）  │
│  └─ 代码编辑器只是 CODE_DEMO / PRACTICAL_TASK 的一个组件      │
└──────────────────────────┬──────────────────────────────────┘
                           │ ActivityAttempt{activityId, input}
┌──────────────────────────▼──────────────────────────────────┐
│ 教学编排层（Stage Orchestrator）                              │
│  ├─ StageContract 注册表（完成条件、允许活动、回退规则）      │
│  ├─ ActivityPlan（本知识点适用活动，可跳过）                  │
│  ├─ 证据判定 → 阶段迁移（AI 无权写状态）                      │
│  └─ 本轮表现 + 长期掌握分开计算                               │
└───────┬──────────────────────┬──────────────────┬────────────┘
        │                      │                  │
┌───────▼──────────┐  ┌────────▼────────┐  ┌──────▼───────────┐
│ 提示词组装器      │  │ 通用活动协议     │  │ 学习档案          │
│ 角色骨架          │  │ ActivityType×14  │  │ 活动尝试/证据      │
│ + 学科策略        │  │ InteractionSpec  │  │ 掌握历史/错题      │
│ + 活动指令        │  │ EvaluationSpec   │  │ 断点/时长          │
│ + 素材上下文      │  │ MaterialRef      │  │                   │
└───────┬──────────┘  └────────┬────────┘  └──────┬───────────┘
        │                      │                  │
┌───────▼──────────────────────▼──────────────────▼───────────┐
│ 数据模型（只加不删）                                          │
│  knowledge_points + subject/activity_plan/material_manifest  │
│  teaching_progress + current_activity_id/pipeline_version     │
│  teaching_activity_instances（新表）                          │
│  course_teaching_profiles（新表）                             │
│  materials（新表，schema 9 已启用）                           │
└─────────────────────────────────────────────────────────────┘
```

### 4.3 对照要点

| 维度 | 现有 | 目标 |
| --- | --- | --- |
| 阶段 | 6 个固定阶段 | 8 阶段契约驱动，可配置 |
| 教学单元 | “一个当前问题” | “一个当前活动 + 活动计划” |
| 活动类型 | 讲解/代码演示/问答 | 14 类通用活动 |
| 学科 | 隐含编程 | 课程级学科策略 |
| AI 权限 | 不能写状态（保留） | 不能写状态（保留） |
| 掌握 | 一次验证即独立 | 本轮表现 + 长期证据 |
| 素材 | 纯 Markdown | Markdown + 素材引用 + 来源定位 |
| 前端 | 文本输入 | 通用活动渲染器 |
| 兼容 | — | 旧会话适配器 + 特性开关 + 可回滚 |

---

## 5. 数据库兼容性与迁移方案

### 5.1 原则

1. **只加不删**：不删除表、不删除列、不改列名、不重写历史行。
2. **旧数据可读**：旧阶段值必须继续正确展示与恢复。
3. **迁移幂等**：重复启动不重复写入。
4. **可回滚**：迁移前备份数据库；新功能用开关控制；回滚不依赖反向 DDL。
5. **不重复建模型**：已存在 `learning_activities`，新表必须换名。

### 5.2 建议新增结构

> 以下是设计建议，本阶段不执行建表。

#### A. `knowledge_points` 新增可空列

| 列 | 类型 | 用途 |
| --- | --- | --- |
| `subject_key` | VARCHAR(32) NULL | 学科标识，如 `programming/math/language/theory/practical` |
| `activity_plan` | TEXT NULL | JSON：本知识点建议活动列表（可跳过标记） |
| `material_manifest` | TEXT NULL | JSON：素材清单与来源定位 |
| `long_term_mastery` | VARCHAR(24) NULL | 长期掌握等级（可选；也可复用 `mastery_level`） |

> `mastery_level` 已存在且闲置，优先复用它承载 0–5 等级，避免再加一列。

#### B. `teaching_progress` 新增可空列

| 列 | 类型 | 用途 |
| --- | --- | --- |
| `pipeline_version` | INTEGER NOT NULL DEFAULT 1 | 1=旧六阶段，2=新八阶段 |
| `current_activity_id` | INTEGER NULL | 当前活动实例 |
| `strategy_snapshot` | TEXT NULL | 会话启动时的学科策略快照 |

#### C. 新表 `teaching_activity_instances`

| 列 | 说明 |
| --- | --- |
| `id` | 主键 |
| `session_id` | FK `learning_sessions` |
| `course_id` / `knowledge_point_id` | 便于查询与统计 |
| `stage_key` | 所属阶段 |
| `activity_type` | 14 类之一 |
| `sort_order` | 阶段内顺序 |
| `status` | PENDING/ACTIVE/WAITING_EVALUATION/COMPLETED/SKIPPED/FAILED |
| `payload_json` | 完整活动协议（内容块、交互、评价标准、素材引用） |
| `result_json` | 学生输入 + 评价结果 + 反馈 |
| `hint_count` / `attempt_no` | 计数 |
| `started_at` / `completed_at` | 时间 |
| `created_at` / `updated_at` | 审计 |

> 命名刻意避开 `learning_activities`，后者继续表示“学习时长活动”。

#### D. 新表 `course_teaching_profiles`

| 列 | 说明 |
| --- | --- |
| `course_id` | PK/FK |
| `subject_key` | 学科 |
| `strategy_key` | 策略预设或 `custom` |
| `strategy_json` | 覆盖配置 |
| `confirmed_by_user` | 是否由用户确认 |
| `created_at` / `updated_at` | 审计 |

#### E. 新表 `materials`（已实现，schema 9）

实际结构以 `docs/DATABASE.md` 第 9.5 节为准：

| 列 | 说明 |
| --- | --- |
| `id` | 主键，即 `material://ID` 中的 ID |
| `course_id` | 归属课程（不含 `knowledge_point_id`，素材可在课程内复用） |
| `file_name` / `relative_path` | 展示名与服务端生成的存储路径 |
| `mime_type` / `size_bytes` / `sha256` | 文件信息 |
| `kind` | image / audio / video |
| `caption` | 说明文字 |
| `source_ref` | 教材来源定位（JSON 文本） |

### 5.3 旧阶段值迁移映射

旧 3 条真实数据：`DEMO/BLOCKED`、`NEXT/COMPLETED`、`TEACH/BLOCKED`。

| 旧阶段 | 新阶段（建议） | 说明 |
| --- | --- | --- |
| `TEACH` | `TEACH` | 同名保留 |
| `DEMO` | `DEMONSTRATE` | 语义直接对应 |
| `CHECK` | `INTERACT` | 理解检查 |
| `PAIR` | `PRACTICE` | 引导练习；`pair_step` 保留为活动进度 |
| `VERIFY` | `VERIFY` | 同名保留 |
| `NEXT` | `NEXT` | 同名保留 |
| — | `UNDERSTAND` / `CONSOLIDATE` | 新阶段；旧会话视为已跳过 |

`completed_stages` 按同一映射重写；`mastery_state` 不变；`verification_result` 不变。

### 5.4 迁移步骤（建议）

```text
1. 启动前备份：data/mastery_lab.db → data/backups/p16-<timestamp>.db（SQLite backup API）。
2. create_all() 创建新表（不触碰旧表）。
3. _ensure_columns() 补齐新增可空列（幂等）。
4. 一次性回填：
   - courses 无策略 → subject_key 默认 'programming'（保持现状语义）；
   - teaching_progress 旧行 → pipeline_version=1，不强制改阶段；
   - 旧阶段值建立别名映射表，读写通过适配器归一。
5. 记录 app_settings['p16_migration'] = {version, timestamp, backupPath}。
6. 启动后执行只读校验：表存在、行数不变、外键无违例、旧会话可读取。
```

### 5.5 回滚方案

- **数据回滚**：停止服务 → 用备份覆盖 `data/mastery_lab.db`（`data/backups` 已有目录）。
- **代码回滚**：新功能受 `app_settings['teaching_pipeline']` 控制；回滚时切回 `v1`，旧代码路径继续工作。
- **不改旧列**：因为只加列/加表，回滚不需要反向 DDL。
- **不删除新表**：保留数据，避免回滚后再次迁移丢历史。

### 5.6 兼容性验收

- 旧 3 条教学进度均可读取、展示、继续。
- 旧 `NEXT/COMPLETED` 会话仍显示总结且不重复要求验证。
- 旧断点记录可恢复，草稿不丢。
- 旧错题/掌握历史不丢失，统计口径不变。
- 回滚后旧版本代码可正常打开同一数据库。

---

## 6. 分阶段改造任务清单

> 原则：每一步都可独立验证、可回滚，不一次性替换旧流程。

### P1.6-A 基线与词汇解耦（不改变行为）

- 抽出 `teaching_stages.py`：阶段元数据（key、label、goal、order、optional）。
- 抽出 `subject_profiles.py`：学科预设与策略结构（先只读）。
- 新增 `activity_protocol.py`：14 类活动 Pydantic 模型（先不接入状态机）。
- 前端阶段标签改为读取后端元数据（保留旧值兜底）。
- 新增可重复测试入口：`apps/api/tests`（pytest）+ 隔离临时数据库。
- 验收：现有 48 条 API 行为不变；旧会话回归通过。

### P1.6-B 活动协议持久化（只写不读）

- 新增 `teaching_activity_instances` 表。
- 教学任务生成时，把 `TeachingTask` 适配成 `ACTIVITY` 记录（双写）。
- 旧读取路径仍用 `current_question`，新表仅审计/回放。
- 验收：新表数据与当前问题一致；旧流程零变化。

### P1.6-C 八阶段状态机（特性开关）

- 新增 `StageContract` 与通用编排器；`pipeline_version=2` 时启用。
- 旧 `pipeline_version=1` 走适配器，保持六阶段行为。
- `ANSWER` 计数、评价分支改为活动级；未知阶段安全降级。
- 阶段完成条件：最小活动数、必需活动类型、评价门槛、是否允许提示。
- 验收：新旧两套流程并行回归；旧数据不被改写。

### P1.6-D 提示词与学科策略接入

- 合并 `teaching_prompt` 与 `teaching_protocol` 为统一组装器。
- 组装顺序：角色骨架 → 学科策略 → 阶段契约 → 当前活动 → 素材上下文 → 历史。
- DEMO 按策略选择 `CODE_DEMO / DIAGRAM_WALKTHROUGH / FORMULA_DERIVATION / AUDIO_VIDEO`。
- 验收：编程课程输出不退化；数学/语言 dry-run 能生成对应活动。

### P1.6-E 前端通用活动渲染

- 新增 `ActivityRenderer`，按 `activityType` 渲染输入组件。
- 首批：`TEXT_EXPLANATION`、`MULTIPLE_CHOICE`、`FILL_IN_BLANK`、`SHORT_ANSWER`、`CALCULATION`、`CODE_DEMO`。
- 保留 textarea 作为 `SHORT_ANSWER/CONVERSATION` 的默认实现。
- 验收：各活动类型可提交、可评价、可恢复；旧会话仍可显示。

### P1.6-F 掌握度与档案扩展

- 区分“本轮表现”和“长期掌握”。
- `INDEPENDENT` 仅表示本轮独立完成；长期掌握需跨轮证据。
- 复用 `mastery_level` 记录 0–5 等级；`mastery_history` 增加证据类型。
- 错题按活动类型归类，保留旧 `concept/practice/verification` 兼容。
- 验收：一次答对不会直接标记长期掌握；历史数据统计不倒退。

### P1.6-G 素材与多模态（已实现）

- 新表 `materials`（schema 9）：课程素材元数据，文件落盘 `data/materials/<course_id>/`，
  路径与文件名由服务端生成，数据库不保存用户输入路径。
- 接口：
  - `POST /api/v1/courses/{course_id}/materials` 上传（multipart，`file` + `caption`）；
  - `GET /api/v1/courses/{course_id}/materials` 列表；
  - `GET /api/v1/materials/{material_id}` 元数据；
  - `GET /api/v1/materials/{material_id}/content` 返回文件（`X-Content-Type-Options: nosniff`）；
  - `DELETE /api/v1/materials/{material_id}` 删除（同时删除文件）。
- 安全校验：只接受 PNG/JPEG/GIF/WebP、MP3/WAV/OGG/M4A、MP4/WebM；扩展名 + MIME + 文件签名
  三重校验（SVG、伪造扩展名、空文件均拒绝）；单文件上限 `max_asset_bytes`（50 MB）。
- 引用协议：Markdown 与活动内容只能写 `material://ID`（前端渲染时重写为内容接口地址），
  也允许直接写 `/api/v1/materials/{id}/content`；其他外链图片降级为纯文本。
- 前端：`utils/markdown.ts` 支持安全图片渲染（含 `figcaption`），`ActivityRenderer` 支持
  `image` 内容块与音频/视频播放器；旧 Markdown 课程不受影响。
- 删除课程时级联删除素材行与文件。
- 验收：`tests/test_materials.py` 覆盖上传/列表/读取/删除、拒绝 SVG/伪造 PNG/空文件/不存在课程、
  删除课程清理素材；真实数据库副本上建表、上传、读取、删除全部 200/201，原库 sha256 不变。
- PDF OCR/版面解析与素材自动抽取另行立项。

### 任务依赖关系

```text
A ──> B ──> C ──> D ──> E ──> F
                    └────────> G（可与 E/F 并行，需素材表）
```

---

## 7. 风险与回归测试计划

### 7.1 主要风险

| 风险 | 影响 | 缓解 |
| --- | --- | --- |
| 旧阶段值迁移错误 | 进行中会话错乱、断点失效 | 别名适配器 + 备份 + 只读校验 + 不强制改旧行 |
| 新活动 JSON 解析失败 | 教学中断、阶段不推进 | Pydantic 严格校验 + 版本号 + 失败不推进阶段 |
| 两套流程并存导致分叉 | 行为不一致、测试困难 | 特性开关 + 共享阶段契约 + 双轨回归 |
| 提示词变长 | 上下文超限、成本上升 | 分层预算（策略/活动/素材/历史分别限额） |
| 一次答对仍被当成掌握 | 违反产品原则 | 证据规则 + 长期掌握独立计算 |
| 前端活动渲染回归 | 旧课堂不可用 | 保留 textarea 兜底 + 按活动类型渐进启用 |
| 表名冲突 | 数据语义混乱 | 新表统一 `teaching_activity_*` 前缀 |
| 无自动化测试 | 无法证明“真实测试结果” | 先补 pytest 基线，再改代码 |

### 7.2 回归矩阵

| 层 | 用例 | 期望 |
| --- | --- | --- |
| P1.1 | Markdown/PDF 导入、扫描 PDF 报错 | 行为不变 |
| P1.2 | 课程/章节/知识点 CRUD、排序、状态 | 行为不变 |
| P1.3 | 自由对话、SSE 流、停止、重生成、断线恢复 | 行为不变 |
| P1.4 | 六阶段推进、回退、暂停、重学、重启恢复 | v1 行为不变；v2 新流程独立 |
| P1.5 | 学习时长、断点、档案、错题、历史详情 | 行为不变 |
| 迁移 | 旧库启动、重复启动、回滚 | 行数不变、无外键错误 |
| 新功能 | 14 类活动协议校验、8 阶段推进、策略切换 | 新增用例通过 |
| 前端 | 旧课堂显示、新活动提交、窄屏布局 | 无 pageerror |

### 7.3 测试分层建议

1. **单元测试**：阶段契约、活动协议校验、评价规则、掌握度推导。
2. **API 测试**：用临时 SQLite + mock LLM，覆盖动作/评价/断点/迁移。
3. **契约测试**：活动 JSON 的 golden fixtures（每种类型至少 1 个）。
4. **前端测试**：活动渲染器组件测试 + 关键页面流程。
5. **手工验收**：真实模型小样本；真实结果与模拟结果分开记录。

### 7.4 每次代码修改的交付要求

- 必须给出：修改文件、测试命令、真实输出、通过/失败数量。
- 不允许只改文档宣称完成。
- 不允许用“模拟通过”替代真实模型验收；两者必须标注清楚。

---

## 8. 需要用户确认的决策点

在进入编码前，需要确认以下 5 项：

1. **阶段模型**：是否接受 8 阶段 `UNDERSTAND → TEACH → DEMONSTRATE → INTERACT → PRACTICE → VERIFY → CONSOLIDATE → NEXT`？还是先保留 6 阶段、只做活动类型扩展？
2. **迁移策略**：旧会话采用“别名适配、不改旧行”，还是“一次性归一写库 + 备份回滚”？
3. **学科策略来源**：新建课程时由用户选择学科，还是 AI 推荐后由用户确认？是否允许按章节覆盖？
4. **长期掌握标准**：`INDEPENDENT` 是否只代表“本轮独立完成”，长期掌握是否要求“至少两次跨轮独立证据”？
5. **实施顺序**：是否按 P1.6-A → G 的顺序推进，先补自动化测试基线，再动状态机？

> 确认后才会进入 P1.6-A 的代码改造；未确认前不修改任何现有功能。
