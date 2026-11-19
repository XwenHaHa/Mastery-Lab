# P1.6 变更说明（通用教学架构）

- 版本：P1.6-A ~ P1.6-G
- 状态：已实现并回归（2026-11-19）
- 数据库 schema：`9`
- 设计依据：`docs/P16_ARCHITECTURE_AUDIT.md`、`docs/P16_GENERAL_TEACHING_DESIGN.md`

## 1. 阶段目标

P1.6 解决的是「教学流程只适用于 Python 编程」的问题，把 P1.4 的六阶段状态机
扩展为可配置、学科无关的通用教学架构。

三条原则：

1. **双轨并行**：旧六阶段（`pipeline_version=1`）保持可用，新八阶段
   （`pipeline_version=2`）通过特性开关启用，只影响新会话。
2. **状态主权在服务端**：AI 只能返回内容、活动 JSON 和评价建议，不能直接写阶段与掌握度。
3. **只做增量**：数据库只加列、只加表，不删列、不改名、不重写历史数据。

## 2. 阶段总览

| 阶段 | 内容 | 状态 |
| --- | --- | --- |
| P1.6-A | 基线与词汇解耦：阶段元数据、学科预设、活动协议、测试入口 | 已实现 |
| P1.6-B | 活动协议持久化：`teaching_activity_instances` 双写 | 已实现 |
| P1.6-C | 八阶段状态机与阶段契约（特性开关） | 已实现 |
| P1.6-D | 统一提示词组装器与学科策略接入 | 已实现 |
| P1.6-E | 前端通用活动渲染 `ActivityRenderer` | 已实现 |
| P1.6-F | 本轮表现与长期掌握分离（0–5 级） | 已实现 |
| P1.6-G | 素材库：图片、音频、视频 | 已实现 |

## 3. 逐项变更

### 3.1 P1.6-A 基线与词汇解耦

- 新增 `apps/api/app/services/teaching_stages.py`：阶段元数据（key、label、goal、order、optional），
  统一 `normalize_version`、`family_of`、`evaluation_stage_key`、`state_stage_key`、`pipeline_payload`。
- 新增 `apps/api/app/services/subject_profiles.py`：5 套学科策略
  `programming / math / language / theory / practice`，输出 camelCase 结构。
- 新增 `apps/api/app/services/activity_protocol.py`：14 类活动协议，先定义、不接入状态机。
- 新增 `GET /api/v1/meta/teaching`：前端从这里读取阶段与学科元数据。
- 前端新增 `stores/teachingMeta.ts`，`TeachingFlowPanel` 改为读取后端元数据并保留本地兜底。
- 新增 pytest 测试入口 `apps/api/tests`，每个用例使用隔离的临时 SQLite。

### 3.2 P1.6-B 活动协议持久化

- 新表 `teaching_activity_instances`：记录一次教学活动的阶段、类型、定义、学生输入、AI 反馈与结果。
- 生成教学任务时把旧的五字段题目（指导语/问题/标准/提示/小结）适配为
  `TeachingActivityDefinition` 并写入新表，实现**双写**。
- 旧读取路径仍是 `teaching_progress.current_question`，新表只用于审计与回放，不改变旧行为。
- 活动定义包含：内容块、交互规格、评价规格、素材引用、来源定位、提示策略。

### 3.3 P1.6-C 八阶段状态机

- 新增 `apps/api/app/services/teaching_pipeline.py`：
  - `StageContract`：阶段完成条件、允许活动类型、允许动作、回退规则；
  - `TeachingPipeline`：按 `pipeline_version` 选择 v1/v2 契约并执行迁移。
- 两套阶段：

| 版本 | 阶段 |
| --- | --- |
| v1（默认，旧流程） | `TEACH → DEMO → CHECK → PAIR → VERIFY → NEXT` |
| v2（特性开关） | `UNDERSTAND → TEACH → DEMONSTRATE → INTERACT → PRACTICE → VERIFY → CONSOLIDATE → NEXT` |

- `teaching_progress` 新增：
  - `pipeline_version`：新会话按配置写入，旧行保持 `1`；
  - `stage_counters`：按阶段记录尝试/提示次数。
- 未知阶段、缺失契约安全降级到默认规则，不抛异常、不写坏状态。
- 特性开关：`MASTERY_LAB_TEACHING_PIPELINE_VERSION=2`（默认 `1`）。

### 3.4 P1.6-D 提示词与学科策略

- 新增 `apps/api/app/services/prompt_assembler.py`，合并 `teaching_prompt` 与 `teaching_protocol` 的组装逻辑。
- 统一组装顺序：

```text
角色骨架 → 学科策略 → 阶段契约 → 当前活动 → 教材/素材上下文 → 历史消息
```

- `detect_subject_profile` 按课程内容推断学科；`recommend_activity_type` 按阶段与学科推荐活动类型。
- DEMO 阶段可按学科选择 `CODE_DEMO / DIAGRAM_WALKTHROUGH / FORMULA_DERIVATION / AUDIO_VIDEO`。
- 旧的 `build_messages` 保留为兼容入口，内部委托新组装器。

### 3.5 P1.6-E 前端通用活动渲染

- 新增 `apps/web/src/components/ActivityRenderer.vue`，按 `activityType` 渲染不同输入组件。
- 首批渲染 6 类：`TEXT_EXPLANATION`、`MULTIPLE_CHOICE`、`FILL_IN_BLANK`、`SHORT_ANSWER`、
  `CALCULATION`、`CODE_DEMO`。
- 支持图片内容块与音频/视频播放器（P1.6-G 接入素材地址）。
- `ClassroomView` 接入活动渲染与提交逻辑；无法识别的类型回退为文本输入，旧会话不受影响。

### 3.6 P1.6-F 掌握度与档案

- `mastery_state`（本轮表现）与 `mastery_level`（长期掌握）分离，状态扩展为 7 种：

```text
NOT_STARTED / INTRODUCED / UNDERSTANDING / GUIDED_PRACTICE / INDEPENDENT / NEEDS_REVIEW / STABLE
```

- 长期掌握 0–5 级：

| 等级 | 含义 | 达成条件 |
| --- | --- | --- |
| 0 | 未接触 | 无教学证据 |
| 1 | 已接触 | 进入讲解 |
| 2 | 已理解 | 理解检查通过 |
| 3 | 引导练习 | 在提示下完成练习 |
| 4 | 本轮独立 | 单轮 VERIFY 独立通过（上限） |
| 5 | 稳定掌握 | 两次跨轮/跨会话独立通过（间隔 ≥ 24h）并完成巩固 |

- 失败不降低长期等级，只标记需要复习；一次答对不会直接标记长期掌握。
- `mastery_history` 新增证据字段：`evidence_type`、`stage`、`activity_type`、`verdict`、
  `hint_count`、`round_number`、`pipeline_version`。
- `mistake_records` 新增 `activity_type`，错题按活动类型归类；旧分类继续可读。
- 学习档案接口补充 `masteryLevel`、`masteryLevelLabel`、`stableMastery` 与等级分布。
- 旧数据没有 `mastery_level` 时按 `mastery_state` 推导只读下限，不回写历史。

### 3.7 P1.6-G 素材与多模态

- 新表 `materials`（schema 9），文件存放 `data/materials/<course_id>/`，数据库只存服务端生成的相对路径。
- 新增接口：

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| POST | `/api/v1/courses/{course_id}/materials` | 上传素材（multipart：`file`、`caption`） |
| GET | `/api/v1/courses/{course_id}/materials` | 课程素材列表 |
| GET | `/api/v1/materials/{material_id}` | 素材元数据 |
| GET | `/api/v1/materials/{material_id}/content` | 读取文件，带 `nosniff` |
| DELETE | `/api/v1/materials/{material_id}` | 删除素材与文件 |

- 支持类型：
  - 图片：PNG / JPEG / GIF / WebP；
  - 音频：MP3 / WAV / OGG / M4A；
  - 视频：MP4 / WebM。
- 安全校验：扩展名 + MIME + 文件签名三重校验；SVG、伪造扩展名、空文件均拒绝；
  单文件上限 `MASTERY_LAB_MAX_ASSET_BYTES`（默认 50 MB）。
- 引用协议：Markdown 与活动内容只能写 `material://ID`，前端渲染时重写为
  `/api/v1/materials/{id}/content`；其他来源图片降级为纯文本。
- 删除课程时级联删除素材行并清理对应目录。

## 4. 数据模型变更

| 表 | 变更 |
| --- | --- |
| `teaching_progress` | 新增 `pipeline_version`、`stage_counters` |
| `teaching_activity_instances` | 新表：活动实例、定义、输入、反馈、结果 |
| `mastery_history` | 新增 `evidence_type`、`stage`、`activity_type`、`verdict`、`hint_count`、`round_number`、`pipeline_version` |
| `mistake_records` | 新增 `activity_type` |
| `materials` | 新表：课程素材元数据 |

所有新增列都带默认值；新表由 `create_all()` 创建；迁移逻辑在 `db/__init__.py` 中保持幂等，
只加列、不删列、不改名。

## 5. 配置变更

| 配置项 | 默认值 | 说明 |
| --- | --- | --- |
| `MASTERY_LAB_TEACHING_PIPELINE_VERSION` | `1` | 1=六阶段，2=八阶段；只影响新会话 |
| `MASTERY_LAB_MAX_ASSET_BYTES` | `52428800` | 单个图片/音频/视频上限 |
| `materials_dir` | `data/materials` | 素材落盘目录，随 `ensure_dirs()` 创建 |

## 6. 兼容性策略

- 旧教学会话保持 `pipeline_version=1`，阶段、问题、计数读取路径不变。
- 旧 Markdown 课程不依赖素材，可照常学习。
- 旧 `mastery_state` 数据保留；`mastery_level` 缺失时只读推导，不回写。
- 旧错题分类字段继续可读，新字段仅补充活动维度。
- 数据库升级只执行 `create_all()` 与 `_ensure_columns()`，原始数据不被重写。

## 7. 验证结果

### 7.1 自动化测试

```powershell
cd apps/api
.\.venv\Scripts\python.exe -m pytest -q
# 28 passed

cd apps/web
npm run typecheck   # 通过
npm run build       # 通过
```

覆盖范围包括：教学元数据、活动实例双写、双轨流程、提示词组装、长期掌握跨轮证据、
素材上传/读取/删除与非法文件拒绝。

### 7.2 真实数据库副本

| 检查项 | 结果 |
| --- | --- |
| `materials`、`teaching_activity_instances` 建表 | 成功 |
| 旧表行数 | courses 4 / chapters 10 / knowledge_points 19 / learning_sessions 5 / teaching_progress 3 / mastery_history 6 / mistake_records 2，均不变 |
| 素材上传 → 读取 → 列表 → 删除 | 201 / 200 `image/png` / 200 / 200 |
| 原始数据库 sha256 | `12cc14f8…`，验证前后一致 |

### 7.3 前端渲染冒烟

- `material://12` 正确重写为 `/api/v1/materials/12/content`；
- `javascript:` 图片地址被拒绝并降级为纯文本；
- 含引号的属性逃逸输入被转义，不产生可执行标签。

## 8. 已知限制与后续建议

| 限制 | 说明 | 建议 |
| --- | --- | --- |
| 结构化活动生成未接入 | 14 类活动协议、渲染器已就绪，但模型输出仍统一适配为 `SHORT_ANSWER` | 下一步让模型按活动 JSON 输出选择题、填空、排序、计算等 |
| 素材上传无前端入口 | 目前只能通过 Swagger/API 上传 | 在课程详情页增加素材上传与预览 |
| 素材归属未强校验 | 活动协议只校验 `material_id > 0`，未校验素材属于同一课程 | 在教学活动写入前增加课程归属校验 |
| PDF OCR 未做 | 扫描件 PDF 仍明确拒绝，不做 OCR | 作为独立项目评估版面解析 |
| 长期掌握跨轮证据 | 测试中用回填历史时间模拟 ≥24h 间隔，未真实等待 | 上线后由真实学习节奏产生证据 |

## 9. 主要新增文件

```text
apps/api/app/services/teaching_stages.py
apps/api/app/services/subject_profiles.py
apps/api/app/services/activity_protocol.py
apps/api/app/services/teaching_pipeline.py
apps/api/app/services/prompt_assembler.py
apps/api/app/services/activities.py
apps/api/app/services/material_library.py
apps/api/app/api/v1/meta.py
apps/api/app/api/v1/materials.py
apps/api/tests/
apps/web/src/components/ActivityRenderer.vue
apps/web/src/stores/teachingMeta.ts
docs/P16_ARCHITECTURE_AUDIT.md
docs/P16_GENERAL_TEACHING_DESIGN.md
```
