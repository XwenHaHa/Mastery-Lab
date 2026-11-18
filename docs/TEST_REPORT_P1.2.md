# Mastery Lab · P1.2 课程管理与知识点管理测试报告

- 报告日期：2026-11-16
- 被测范围：P1.2「课程中心 + 课程详情 + 章节管理 + 知识点管理 + 学习状态与进度」
- 测试方式：真实前后端进程 + 真实 SQLite + 真实浏览器（Chromium，无 mock、无桩数据）
- 结论：**任务书 12 项验收全部通过**；后端 52 项断言全绿，Playwright 17 步 UI 流程全绿；
  过程中发现并修复 **1 个真实缺陷**（时间未带时区导致「最近学习」偏 8 小时），见第七节。

---

## 一、交付物对照

| 需要的内容 | 位置 |
| --- | --- |
| 功能清单 | 本报告第二节 |
| 修改/新增文件清单 | 本报告第三节 |
| 新增或修改的 API | 本报告第四节 + `docs/ARCHITECTURE.md` 第 9 节 |
| 数据库结构变化 | 本报告第五节 + `docs/DATABASE.md` |
| 页面截图 | `docs/review/p1-2/`（14 张） |
| 真实测试结果 | 本报告第六节 + `docs/qa/p12-api-result.json`、`docs/qa/p12-ui-flow-result.json` |
| 遗留问题 | 本报告第八节 |
| P1.3 建议 | 本报告第九节 |

配套脚本（可复跑，均需服务已启动）：

| 脚本 | 作用 | 结果 |
| --- | --- | --- |
| `docs/qa/p12_api_check.py` | 真实 HTTP + 只读直连 SQLite，52 项断言（含负向用例） | 52/52 通过 |
| `docs/qa/p12_ui_flow.py` | Playwright 端到端 17 步，产出 14 张截图 | 17/17 通过 |

---

## 二、功能清单

**课程中心**

1. 列表展示：课程名、简介、图标（或 MD/PDF 徽标）、教材文件名与大小、章节数/知识点数、学习进度、最近学习时间、创建时间。
2. 搜索：课程名 / 简介 / 教材文件名，大小写不敏感，300ms 防抖；无结果有独立空状态。
3. 排序：最近学习 / 创建时间 / 最近更新（后端排序，非前端假排序）。
4. 编辑课程：名称、简介、图标（10 个预设），弹窗内展示原始教材信息。
5. 删除课程：二次确认，提示将删除的章节数/知识点数/学习状态与本地教材文件。
6. 空状态：无课程时明确给出「导入第一份教材」入口。

**课程详情**

7. 课程基本信息、可编辑、可删除。
8. 学习进度概览：加权进度条、四态计数、最近学习的 3 个知识点（可点击跳转）。
9. 章节树：可展开/折叠，显示每章知识点数与章节进度（进度按同一公式计算）。
10. 章节管理：新增、改名、改简介、删除（二次确认）、上移/下移；顺序持久化、刷新不变。
11. 知识点管理：新增、改名、改简介、改正文、删除（二次确认）、上移/下移。
12. 知识点阅读面板：Markdown 渲染（标题/列表/代码围栏/表格/引用/链接）、所属章节面包屑、上/下一个翻页。
13. 学习状态：四态手工切换，切换后进度与计数立即更新，并记录最近学习时间。
14. 正文编辑弹窗：编辑 / 预览双标签，预览使用与阅读面板相同的渲染器。

**接口层**

15. 20 个课程域接口（含 9 个 P1.2 新增），沿用统一响应外壳与错误码。
16. 归属校验：带 `courseId` 的写操作会校验章节/知识点确实属于该课程，否则 404。
17. 排序校验：必须提交全量 ID 排列，缺项或重复返回 422。

---

## 三、修改与新增文件

**后端（新增 1，修改 5）**

| 文件 | 变化 |
| --- | --- |
| `apps/api/app/services/learning.py` | **新增**：四态状态、历史别名归一、进度权重与公式（唯一事实来源） |
| `apps/api/app/db/models.py` | 新增 `courses.icon`、`courses.last_studied_at`、`knowledge_points.last_studied_at` |
| `apps/api/app/db/__init__.py` | 新增 `_ensure_columns()`（PRAGMA 检测 + ALTER TABLE 加列）、`_migrate_learning_status()` |
| `apps/api/app/schemas/course.py` | 新增 `StatusCounts`、`KnowledgePointSummary/Detail`、`PointStatusUpdate`、`ChapterReorderRequest`、`PointReorderRequest`、`ChapterProgress`、`RecentStudy`、`CourseProgress`；目录项改为不带正文 |
| `apps/api/app/services/course_service.py` | 列表搜索/排序、章节与知识点的归属校验、独立排序接口、学习状态、进度总览、`_utc()` 时间修正 |
| `apps/api/app/api/v1/courses.py` | 新增课程内路径接口 10 个，扁平路径保留为兼容入口 |
| `apps/api/app/main.py` | `SCHEMA_VERSION` 升为 `3` |

**前端（新增 2，修改 6）**

| 文件 | 变化 |
| --- | --- |
| `apps/web/src/utils/markdown.ts` | **新增**：安全 Markdown 渲染器（先转义再组装标签） |
| `apps/web/src/utils/learning.ts` | **新增**：状态文案、状态计数取值、时间/大小格式化 |
| `apps/web/src/api/types.ts` | 新增 `LearningStatus`、`StatusCounts`、`KnowledgePointDetail`、`CourseProgress` 等类型 |
| `apps/web/src/api/index.ts` | 新增 `courseLibraryApi`（课程内路径），保留 `courseApi`（导入流程） |
| `apps/web/src/stores/courses.ts` | 搜索词 + 排序 + 状态合计 |
| `apps/web/src/views/CoursesView.vue` | 重写：搜索/排序/编辑弹窗/教材信息/继续学习 |
| `apps/web/src/views/CourseDetailView.vue` | 重写：进度概览 + 左目录管理 + 右阅读面板 + 三类弹窗 |
| `apps/web/src/styles/base.css` | 新增状态徽标与 `.md-body` 正文样式 |

**文档与测试**

| 文件 | 变化 |
| --- | --- |
| `docs/PRD.md` | 新增第 8 节（P1.2 范围、12 项验收、功能需求、进度口径） |
| `docs/ARCHITECTURE.md` | 新增第 9 节（两类路径、数据契约、进度规则、前端页面、Markdown 渲染、取舍） |
| `docs/DATABASE.md` | 新增列与四态说明、1.6 学习状态与进度、v2→v3 迁移、孤儿行检查命令 |
| `docs/DEVELOPMENT_PLAN.md` | 阶段状态与 P1.2 交付内容、P1.3 计划、风险表更新 |
| `README.md` | 课程管理与学习状态使用说明、接口一览、回归脚本、遗留项 |
| `docs/TEST_REPORT_P1.2.md` | **新增**：本文件 |
| `docs/qa/p12_api_check.py` | **新增**：52 项接口断言脚本 |
| `docs/qa/p12_ui_flow.py` | **新增**：Playwright 全流程脚本 |
| `docs/qa/p12-api-result.json`、`p12-ui-flow-result.json`、`docs/review/p1-2/*.png` | **新增**：测试证据 |

---

## 四、新增 / 修改的 API

| 方法 | 路径 | 状态 | 说明 |
| --- | --- | --- | --- |
| GET | `/api/v1/courses` | 修改 | 新增 `q`（搜索）与 `sort=updated\|created\|studied` 参数 |
| GET | `/api/v1/courses/{id}` | 修改 | 响应增加 `icon`、`lastStudiedAt`、`statusCounts`；章节增加 `progress`/`statusCounts`；知识点改为 `contentLength`（不返回正文） |
| PATCH | `/api/v1/courses/{id}` | 修改 | 支持修改 `icon` |
| GET | `/api/v1/courses/{id}/progress` | **新增** | 整体进度 + 分章节进度 + 最近学习 6 条 |
| GET | `/api/v1/courses/{id}/chapters` | **新增** | 课程章节列表（含知识点摘要） |
| PATCH | `/api/v1/courses/{id}/chapters/reorder` | **新增** | 章节排序（全量 ID 排列） |
| PATCH/DELETE | `/api/v1/courses/{id}/chapters/{chapterId}` | **新增** | 章节修改/删除（带归属校验） |
| GET | `/api/v1/courses/{id}/knowledge-points` | **新增** | 知识点平铺列表，支持 `status` 过滤与 `q` 搜索 |
| POST | `/api/v1/courses/{id}/chapters/{chapterId}/knowledge-points` | **新增** | 新增知识点（可带正文） |
| PATCH | `/api/v1/courses/{id}/chapters/{chapterId}/knowledge-points/reorder` | **新增** | 知识点排序 |
| PATCH/DELETE | `/api/v1/courses/{id}/knowledge-points/{pointId}` | **新增** | 知识点修改/删除（带归属校验） |
| PATCH | `/api/v1/courses/{id}/knowledge-points/{pointId}/status` | **新增** | 更新学习状态 |
| GET | `/api/v1/knowledge-points/{pointId}` | **新增** | 知识点详情（正文 + 前后邻居 + 所属章节） |
| PATCH | `/chapters/{id}`、`/knowledge-points/{id}`、`/chapters/{id}/knowledge-points` | 保留 | P1.1 导入流程使用，行为不变 |

---

## 五、数据库结构变化

- 版本：`app_settings.schema_version` 由 `2` 升为 `3`。
- 新增列（只加列，未改名、未删列、未重建）：

| 表 | 列 | 类型 | 说明 |
| --- | --- | --- | --- |
| `courses` | `icon` | VARCHAR(16) NOT NULL DEFAULT '' | 单字符图标，空串表示按来源显示 MD/PDF |
| `courses` | `last_studied_at` | DATETIME NULL | 最近学习时间（naive UTC） |
| `knowledge_points` | `last_studied_at` | DATETIME NULL | 该知识点最近一次状态变更时间（naive UTC） |

- 值归一（幂等）：`learning_status` 的 `learning → in_progress`、`mastered → completed`。
- 迁移方式：`init_db()` 里 `create_all()` → `_ensure_columns()`（`PRAGMA table_info` 判断后 `ALTER TABLE ADD COLUMN`）→ `_migrate_learning_status()`。
- 实测：本项目真实旧库（3 门课程 / 9 章 / 16 个知识点）升级后行数与内容完全不变，
  启动日志输出 3 行「增量迁移：xxx 表新增列 yyy」；升级后 `schema_version=3`，孤儿行检查为 0/0。

---

## 六、真实测试结果

### 6.1 后端接口回归（`docs/qa/p12_api_check.py`）

命令：`python docs/qa/p12_api_check.py`（后端运行在 127.0.0.1:8000）
结果：**52/52 通过**，明细见 `docs/qa/p12-api-result.json`。覆盖分组：

| 分组 | 代表性断言 |
| --- | --- |
| 基线回归（P0） | 健康检查可用；模型配置列表可读；新建不回传明文 Key；可修改；可删除 |
| 基线回归（P1.1） | Markdown 上传解析；目录不回传正文；PDF 文本层解析；扫描件仍然 422 |
| 课程 | 名称/简介/图标可改；确认后进入课程中心；列表可见；`sort=created` 倒序正确；搜索无结果为 [] |
| 章节 | 新增追加到末尾；改名改简介生效；`GET /chapters` 可用；排序持久化；不完整/重复 ID 被 422 拒绝 |
| 知识点 | 新增成功；数量正确；改名改简介改正文落库；详情带章节与 `nextId`；排序持久化；ID 不全被拒绝 |
| 学习状态 | 可改 `in_progress`；三种状态同时存在；`mastered` 归一为 `completed`；非法状态 422 |
| 进度 | 课程进度与状态分布交叉验证一致（脚本独立算权重）；章节进度一致；`/progress` 返回总览+分章节+最近学习；最近学习按时间倒序；知识点列表可按状态过滤 |
| 越权与错误 | 别的课程的章节不能被改（404）；别的课程的知识点不能被改状态（404）；不能被删（404）；课程/章节/知识点不存在均 404；空章节名 422 |
| 删除与一致性 | 删除知识点后序号连续；删除章节后章节数正确且无孤儿知识点；刷新后顺序/状态仍在；接口统计与数据库行数一致；删除课程后 404 且章节/知识点孤儿为 0 |

### 6.2 UI 端到端（`docs/qa/p12_ui_flow.py`）

命令：`python docs/qa/p12_ui_flow.py`（前端 5173 + 后端 8000）
结果：**17 步全部通过**，`consoleErrors` 与 `failedRequests` 均为空数组；38 次 API 调用全部 200。

| # | 步骤 | 关键实测数据 |
| --- | --- | --- |
| 1 | 回归课程已创建 | courseId=4，3 章（走真实上传 + 确认创建） |
| 2 | 课程中心列表 | 4 行，含图标、教材元信息、进度、最近学习、创建时间 |
| 3 | 搜索课程 | 关键字「UI 回归」命中 1 行 |
| 4 | 按创建时间排序 | 顺序：回归课程 → 异步手册 → 进阶 → 字典 |
| 5 | 编辑课程信息 | `PATCH /courses/4` → 200，图标变为 🐍 |
| 6 | 课程详情已加载 | `/courses/4`，进度 0%，3 章 / 8 知识点，阅读面板默认打开第 1 个未完成知识点 |
| 7 | 切换知识点 | 点击第 2 个知识点，正文正常渲染 |
| 8 | 标记为学习中 | 200，进度 0% → **5%**，计数「未学习 7 学习中 1」 |
| 9 | 标记为待复习 / 已完成 | 进度 → **12%**，计数「未学习 7 已完成 1」 |
| 10 | 新增章节 | `POST /courses/4/chapters` → 200，追加到末尾 |
| 11 | 章节改名 | `PATCH .../chapters/{id}` → 200，目录即时更新 |
| 12 | 新增知识点并渲染 Markdown | 200；阅读面板渲染出代码块 1、表格 1、引用 1 |
| 13 | 知识点排序并刷新验证 | 上移后 `page.reload()`，顺序 `stable=True` |
| 14 | 刷新后学习状态仍在 | 状态仍为「已完成 / 未学习…」 |
| 15 | 删除章节（含确认） | `DELETE` → 200，章节 4 → 3 |
| 16 | 课程中心显示最新进度 | 行内显示「12% 已完成 1 · 学习中 0 · 待复习 0 最近学习 刚刚」 |
| 17 | 回归课程已清理 | 删除测试课程，库里仍为原来 3 门课程 |

### 6.3 页面截图（`docs/review/p1-2/`，1440×900 @2x）

| 文件 | 内容 |
| --- | --- |
| `01-course-center.png` | 课程中心：搜索框、排序、行内进度与最近学习 |
| `02-course-search.png` | 搜索命中 1 门课程 |
| `03-course-sort.png` | 按创建时间排序 |
| `04-course-edit-dialog.png` | 编辑课程弹窗（简介、图标选择、原始教材信息） |
| `05-course-detail.png` | 课程详情首屏：头部 + 进度概览 + 目录 + 阅读面板 |
| `06-point-reading.png` | 切换到另一个知识点的阅读效果 |
| `07-status-in-progress.png` | 标记「学习中」后的进度与计数 |
| `08-status-completed.png` | 标记「已完成」后的进度 |
| `09-add-chapter-dialog.png` | 新增章节弹窗 |
| `10-point-editor-preview.png` | 知识点正文编辑 + Markdown 预览标签 |
| `11-markdown-rendered.png` | 阅读面板渲染代码块 / 表格 / 引用 |
| `12-point-reordered.png` | 知识点上移后的目录 |
| `13-delete-confirm.png` | 删除章节的二次确认 |
| `14-course-center-after.png` | 回到课程中心，进度与最近学习已更新 |

### 6.4 前端质量检查

```
cd apps\web; pnpm run typecheck   # vue-tsc --noEmit，0 error
cd apps\web; pnpm run build       # 构建成功；CourseDetailView 23.38 kB (gzip 7.97 kB)
```

---

## 七、本轮发现并修复的缺陷

| # | 现象 | 根因 | 修复 | 复测 |
| --- | --- | --- | --- | --- |
| 1 | 课程中心「最近学习」显示「8 小时前」，但刚刚操作过；详情页时间同样偏移 | SQLite 存 naive UTC，Pydantic 序列化不带时区后缀，浏览器按本地时间解析（东八区差 8 小时） | `course_service._utc()` 在输出 `createdAt` / `updatedAt` / `lastStudiedAt` 时补 `UTC` 时区标记 | 复测：接口返回 `...T07:41:10.136666Z`；UI 显示「最近学习 刚刚」「创建于 2026/11/16 16:58:17」 |

修复前该问题不会被任何断言发现（接口只比较顺序），是靠人眼看截图发现的，因此补充了「时间字段必须带 Z」的接口检查思路到遗留项。

---

## 八、遗留问题与已知限制

| # | 问题 | 影响 | 处理计划 |
| --- | --- | --- | --- |
| 1 | 模型配置页（P0）的时间字段仍是 naive 输出 | 该页显示时间偏 8 小时 | 与课程接口统一，列入 P1.3 工程化补齐 |
| 2 | 学习状态是用户自评，无自动判定 | 进度不代表真实掌握 | P1.3 用教学证据推导 `mastery_level`，界面再展示 |
| 3 | Markdown 渲染器不支持裸 HTML / 图片 / 公式 | 教材里这些内容按文本显示 | 已在架构文档写明；若需要再换 marked/DOMPurify |
| 4 | 无拖拽排序，只能上移/下移 | 大章节调整略慢 | 有真实需求时再加，接口已支持任意排列 |
| 5 | 知识点正文上限 200,000 字符 | 超大单节会被 422 拒绝 | 导入解析按节切分，实际未触发；需要时改为流式文本 |
| 6 | 仍未引入 pytest / vitest | 回归靠脚本 | P1.3 并行迁移（见开发计划 3.5） |
| 7 | 无 Alembic | 只能加列，不能改列 | 改列前引入，v3 作为 baseline |
| 8 | 前端全量引入 Element Plus | 首屏 JS ~1.09 MB（gzip 359 KB） | P1.3 用 `unplugin-vue-components` 拆包 |

---

## 九、下一阶段（P1.3 AI 学习教室）开发建议

1. **会话状态机先行**：`sessions` / `messages` 建表 + `TEACH→DEMO→CHECK→PAIR→RUN→VERIFY→NEXT` 状态枚举，
   状态迁移在服务层校验（非法迁移 409），前端只渲染不允许跳步。
2. **入口接现有的四态状态**：进入会话时自动把知识点从 `not_started` 推进到 `in_progress`，
   `VERIFY` 通过后推进 `completed`；「待复习」由间隔复习或用户手工设置，不由模型决定。
3. **上下文按知识点注入**：复用 `GET /knowledge-points/{id}` 的 `content` + 同章节相邻标题，
   不要把整本教材塞进 prompt；超长知识点先按二级标题切片。
4. **流式输出用 SSE**，并保证中断可恢复：已生成内容先落库再推送，刷新后能接上。
5. **单问题约束要有代码层校验**：解析模型输出中的疑问句数量，>1 时拒绝展示并重试，而不是只写在提示词里。
6. **保留 P1.2 的进度口径**：教学推进只改 `learning_status`，进度公式不动；
   掌握度另建字段，由证据条数推导，避免两套进度口径打架。
7. **补测试**：把 `p12_api_check.py` 的 52 项断言迁移成 pytest 用例，新增会话状态机的迁移矩阵测试；
   前端把 `utils/markdown.ts` 与 `stores/*` 纳入 vitest。
