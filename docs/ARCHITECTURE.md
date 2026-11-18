# Mastery Lab 架构（P0 至 P1.3 实际实现）

本文档描述**已经写进代码**的结构，不写理想化设计。未实现的部分统一在文末列出并说明原因。

## 1. 总体形态

```
浏览器 (127.0.0.1:5173)
   │  Vue 3 SPA  ── /api/* 由 Vite dev server 代理 ──┐
   │                                                ▼
   │                                     FastAPI (127.0.0.1:8000)
   │                                       ├── /api/v1/*
   │                                       ├── /docs (Swagger)
   │                                       └── SQLite  data/mastery_lab.db
   └─────────────────────────────────────────────────────────────
                                    启动/停止：scripts/*.ps1
```

- 单机两进程：前端（Vite dev server）、后端（Uvicorn）。
- 开发期跨域通过 Vite `server.proxy` 规避；后端同时配置了 CORS 白名单（`http://localhost:5173`、`http://127.0.0.1:5173`）。
- 生产构建（`pnpm build`）产物在 `apps/web/dist`，P0 尚未提供「由后端托管静态资源」的单进程模式。

## 2. 后端分层

| 层 | 位置 | 职责 | 不做什么 |
| --- | --- | --- | --- |
| 应用装配 | `app/main.py` | FastAPI 实例、CORS、统一异常处理、访问日志、lifespan 初始化 | 不写业务流程 |
| 路由 | `app/api/v1/{health,models,courses}.py` | 参数接收、依赖注入、响应包装 | 不碰数据库细节、不写业务规则 |
| 依赖 | `app/api/deps.py` | 每请求一个 SQLAlchemy Session | — |
| 服务 | `app/services/` | 业务规则：名称唯一、默认唯一、密钥加解密、调用上游、课程/章节/知识点增删改与排序、学习状态与归属校验 | 不构造 HTTP 响应 |
| 学习规则 | `app/services/learning.py` | 四态状态、历史别名归一、进度权重与公式（唯一事实来源） | 不访问数据库、不关心 HTTP |
| 教材处理 | `app/services/{materials,md_parser,pdf_parser}.py` | 文件落盘与校验、Markdown/PDF 解析成 章节→知识点 | 不写数据库、不返回 HTTP |
| Schema | `app/schemas/` | 请求/响应模型与字段校验，对外 camelCase | 不访问数据库 |
| ORM | `app/db/models.py` | 表结构 | 不含业务逻辑 |
| 基础设施 | `app/core/` | 配置、统一响应/异常、密钥加密 | — |

### 统一响应

普通 `/api/v1` 接口（含流开始前的错误）返回同一外壳；P1.3 生成接口成功后使用 SSE：

```json
{ "code": 0, "message": "ok", "data": { } }
```

- `code = 0` 表示成功；非 0 时 `message` 可直接展示给用户。
- 错误码：`1001` 不存在（HTTP 404）、`1002` 冲突（409）、`1003` 参数校验（422）、`1004` 上游异常（502）、`1500` 未预期异常（500）。
- 通过 `app.exception_handler` 统一拦截 `AppError`、`RequestValidationError`、`HTTPException`、`Exception`，
  因此前端只需要处理一种响应形态。

### 字段命名

Python 内部 snake_case，对外一律 camelCase：`app/schemas/base.py` 提供
`CamelModel` / `CamelOutModel`（`alias_generator=to_camel`、`populate_by_name=True`、输出模型带 `from_attributes=True`）。
`/api/v1/health` 手写 dict，也直接使用 camelCase，保持全局一致。

## 3. 密钥存储

```
用户输入 API Key
   ↓  services/model_registry.create_config
core/security.encrypt_secret
   ├─ Windows：CryptProtectData（DPAPI，当前用户作用域）→ "dpapi:v1:<base64>"
   └─ 非 Windows：Fernet + data/secrets/master.key  → "fernet:v1:<token>"
   ↓
model_configs.api_key_cipher（仅密文）
model_configs.api_key_hint  = "****"（新写入；读取旧记录时也不展示尾码）
```

- 解密只发生在后端：调用上游、以及「用已保存配置测试」时。
- Windows DPAPI 加密失败拒绝保存。更换 Base URL 必须重填密钥；仅按已保存参数发出的测试才更新该行的状态。
- 密文带方案前缀，迁移或换机后可识别并给出可读错误，而不是静默损坏。
- 访问日志只记录 `方法 路径 状态码 耗时`，不记录请求体。

## 4. 前端结构

| 部分 | 位置 | 说明 |
| --- | --- | --- |
| 入口 | `src/main.ts` | Pinia、Router、Element Plus（中文包）、主题初始化 |
| 布局 | `src/layouts/AppShell.vue` | 左侧导航 + 顶栏 + 内容区；每 30 秒轮询健康检查 |
| 路由 | `src/router/index.ts` | `/`、`/courses`、`/courses/import`、`/courses/:id`、`/models`、`/settings`、404；视图懒加载，`afterEach` 设置 document.title |
| 状态 | `src/stores/*` | `theme`（深浅色持久化）、`system`（健康状态）、`models`（配置列表与 CRUD）、`courses`（课程列表 + 搜索词 + 排序 + 状态合计） |
| 网络 | `src/api/client.ts`・`src/api/index.ts` | `fetch` 封装，解析统一外壳，失败抛 `ApiError`；`courseLibraryApi`（课程内路径）与 `courseApi`（导入流程的扁平路径）分开 |
| 工具 | `src/utils/{learning,markdown}.ts` | 状态文案/时间格式化；自研安全 Markdown 渲染器（先转义再组装标签，不支持裸 HTML） |
| 样式 | `src/styles/theme.css`・`base.css` | CSS 变量设计令牌；`html.dark` / `html[data-theme=light]` 两套值；状态徽标与 `.md-body` 正文样式 |
| 页面 | `src/views/*` | 概览 / 课程中心 / 导入 / 课程详情 / 模型配置 / 设置 / 404 |

### 视觉约定

- 中性深色底（`#0d1117` 系）+ 单一强调色（`#4c8dff`），不使用渐变与装饰性阴影。
- 信息用分隔线与留白组织，而不是大量卡片；表格与表单密度按桌面端习惯。
- 字体栈为系统字体，等宽内容用 Cascadia/Consolas，避免引入外部字体请求。

## 5. 启动与进程管理

`scripts/` 五个脚本的分工：

| 脚本 | 行为 | 失败时的表现 |
| --- | --- | --- |
| `check-env.ps1` | 检查 Node/pnpm/Python/Git、venv、node_modules、端口、数据目录 | 缺组件时列出问题并 `exit 1` |
| `start-api.ps1` | 建 venv → 按 requirements hash 安装依赖 → 检查 8000 → 后台启动 uvicorn → 轮询健康检查（≤60s） | 打印 `api.err.log` / `api.log` 尾部，清理 PID 文件后 `exit 1` |
| `start-web.ps1` | 缺 node_modules 时安装 → 检查 5173 → 用 node 直接跑 `vite.js --strictPort` → 轮询页面 | 同上，打印 web 日志尾部 |
| `dev.ps1` | check-env → start-api → start-web，任一失败即中止 | 后端失败则不启动前端；前端失败提示保留后端并给停止命令 |
| `stop.ps1` | 按当前数据目录的 PID 和进程创建时间核验，再用 `taskkill /T /F` 停止进程树 | 身份不符拒绝停止；不按端口或进程名猜测 |

实现细节与踩坑记录：

- uvicorn 在 Windows 上会派生子进程，只杀父进程会留下占着 8000 的子进程，因此 `stop.ps1` 使用 `taskkill /T`。
- 前端不用 `pnpm run dev` 包一层，而用 `node node_modules/vite/bin/vite.js` 启动，避免 `.cmd` shim 与含空格路径的引号问题。
- 所有脚本保存为 **UTF-8 with BOM**，否则 Windows PowerShell 5.1 会把中文按 GBK 解码成乱码；不使用
  `[Console]::OutputEncoding = UTF8`，避免 GBK 控制台下输出乱码。

## 6. 配置管理

- `app/core/config.py` 基于 `pydantic-settings`，环境变量前缀 `MASTERY_LAB_`，读取 `apps/api/.env`（示例见 `.env.example`）。
- 主要项：`host`、`port`、`log_level`、`data_dir`（默认 `<repo>/data`）、`database_url`、`cors_origins`、`llm_timeout_seconds`。
- **不提供**「API Key 写进 .env」的路径：密钥只能经界面写入并经 DPAPI 加密，避免第二份明文副本。

## 7. 未实现与原因

| 能力 | 状态 | 原因 |
| --- | --- | --- |
| 教材导入 / 解析 | **已实现（P1.1）** | Markdown 按标题层级确定性解析；PDF 依赖文本层，扫描件明确拒绝、不做 OCR |
| 课程管理与学习状态 | **已实现（P1.2）** | 课程/章节/知识点的增删改序、四态学习状态与加权进度，见本文第 9 节 |
| 教学对话与流式输出 | 已实现（P1.3） | 教材上下文、主动讲解、POST SSE、停止与历史恢复；完整状态机属于 P1.4 |
| 掌握度（mastery_level） | 未实现 | 掌握度必须由「证据条数 + 最近一次独立完成」推导，P1.2 只写四态状态，不虚构掌握度 |
| 代码执行沙箱 | 仅占位目录 | Windows 上安全执行用户代码需要进程隔离、超时强杀、资源限制与网络/文件白名单，风险高，需独立设计（P2） |
| Monaco 编辑器 | 未实现 | P2；P1.2 的正文编辑用普通多行文本框 + Markdown 预览 |
| 数据库迁移 | 未引入 Alembic | P1.2 是「只加列 + 状态归一」，靠 `_ensure_columns()` 幂等迁移；需要改已有列时再引入 |
| 认证 | 无 | 服务只监听 127.0.0.1，单用户本地场景；对外分发前需重新评估 |
| 自动化测试 | 标准库测试及脚本 | unittest、Node test、Playwright；实际结果见各阶段测试报告 |
| 前端按需引入 Element Plus | 全量引入 | 当前 `index-*.js` 约 1.09 MB（gzip 359 KB），本地应用可接受；后续可加 `unplugin-vue-components` 拆包 |
| 单进程部署（后端托管前端产物） | 未实现 | 用两个进程，安装包形态留到后续阶段 |

## 8. P1.1 教材导入管线

### 8.1 请求路径

```
浏览器（拖拽/选择文件，XHR 上传进度）
   └─ POST /api/v1/courses/upload (multipart)
        ├─ services/materials.save_material()
        │    ├─ 扩展名白名单（.md/.markdown/.txt/.pdf）
        │    ├─ 流式写入 + 20 MB 上限 + sha256 + 空文件拦截
        │    ├─ PDF 校验 %PDF 魔数；文本校验 UTF-8 / GB18030
        │    └─ 落盘 data/courses/<uuid12>/<原文件名>
        ├─ services/materials.parse_material()
        │    ├─ Markdown → md_parser.parse_markdown()
        │    └─ PDF → pdf_parser.parse_pdf()（无文本层抛 PdfNoTextError → HTTP 422）
        └─ services/course_service.create_draft()
             └─ 写入 courses + chapters + knowledge_points（status=draft）
```

### 8.2 草稿 → 正式课程

| 阶段 | status | 出现位置 | 用户动作 |
| --- | --- | --- | --- |
| 解析完成 | `draft` | 仅导入预览页（`GET /courses/{id}` 可读） | 改名 / 增删 / 调序 |
| 确认创建 | `active` | 课程中心列表 | 开始学习（P1.2）或删除 |
| 取消导入 | — | 不出现 | `DELETE /courses/{id}`：删行 + 删教材文件 |

「AI 生成的学习路线只是建议」这条产品约束，落在实现上就是：解析结果永远是 `draft`，
必须显式 `POST /courses/{id}/confirm` 才会进入课程中心。

### 8.3 解析规则（确定性，无模型依赖）

| 输入 | 规则 | 兜底 |
| --- | --- | --- |
| Markdown | 第一个 `#` 作课程名；`##` 作章节；`###`–`######` 作知识点，归属最近的上层章节；代码围栏保留语言标识并计数 | 没有标题 → 单章节「全文」并在 warnings 里说明 |
| PDF | 抽取文本层；`第X章` / `1.2 标题` / 全大写短行 视为标题（章节或知识点）；无标题时按页组织 | 无可提取文本（扫描件）→ 422 明确报错，不返回结构 |
| 代码块 | Markdown 用围栏语言；PDF 用「4 空格缩进」启发式，语言记为 `text` | 识别不到就不计，不猜语言 |

### 8.4 安全约束

- 文件名只取 `basename`，过滤控制字符、限长 120；真实目录由服务端生成，与用户输入无关。
- 所有读写都经过 `_within_courses()` 校验，`../` 穿越直接拒绝（有对应冒烟断言）。
- 超限/空文件/错误类型/假 PDF/损坏文本都在落盘前后被拦截，失败时清理临时目录。
- 教材内容不进前端构建产物，也不发给任何外部服务。

### 8.5 前端页面

| 路由 | 视图 | 要点 |
| --- | --- | --- |
| `/courses` | `CoursesView` | 课程行：图标/类型徽标、名称、简介、教材元信息、进度条、最近学习、继续学习/编辑/删除（P1.2 增强，见第 9.4 节） |
| `/courses/import` | `CourseImportView` | 两步：拖拽上传（进度）→ 结构预览（改名/增删/上下移/确认或取消） |
| `/courses/:id` | `CourseDetailView` | P1.2 重写：进度概览 + 左目录管理 + 右阅读面板，见第 9 节 |

## 9. P1.2 课程管理与学习状态

### 9.1 两类 API 路径

| 用途 | 路径形状 | 归属校验 | 谁在用 |
| --- | --- | --- | --- |
| 课程内路径 | `/courses/{courseId}/chapters/{chapterId}`、`/courses/{courseId}/knowledge-points/{pointId}` | 有：`_get_chapter` / `_get_point` 校验父级，不匹配返回 404 | P1.2 课程中心与课程详情 |
| 扁平路径 | `/chapters/{chapterId}`、`/knowledge-points/{pointId}` | 无（路径里没有课程 ID，因此没有跨课程歧义） | P1.1 导入预览页 |

两类路径调用同一批服务函数，前端按场景选择。归属校验的意义：详情页切换课程后，
过期的 `chapterId` 不会误改到另一门课的数据（回归脚本里有对应的 3 条负向断言）。

排序接口一律「全量 ID 排列」语义：

```
PATCH /courses/{id}/chapters/reorder            {"ids": [12, 9, 14]}
PATCH /courses/{id}/chapters/{cid}/knowledge-points/reorder   {"ids": [31, 30]}
```

服务层校验「无重复 + 集合相等」，不相等返回 422 并提示刷新，避免客户端拿旧列表覆盖出脏顺序。

### 9.2 数据契约（响应形状）

| 接口 | 返回 | 为什么不这样那样 |
| --- | --- | --- |
| `GET /courses/{id}` | `CourseDetail`：章节 + 知识点摘要（`contentLength`，不含正文） | 目录一次拉全，但不把几十万字正文塞进列表；避免每次状态切换都重传全文 |
| `GET /knowledge-points/{pid}` | `KnowledgePointDetail`：正文 + 前后邻居 + 所属章节/课程 | 阅读面板点开才拉正文，支持「上一个/下一个」 |
| `PATCH .../status`、章节/知识点增删改 | `CourseDetail` | 一次写入即拿回最新目录与统计，前端不需要二次拼装 |
| `GET /courses/{id}/progress` | 整体进度 + 分章节进度 + 最近学习的 6 条 | 课程详情的进度条与「最近学习」来自同一接口，口径一致 |

时间字段统一以 UTC 输出（`...Z`）。SQLite 里存的是 naive UTC，服务层用 `_utc()` 补时区标记，
否则浏览器会把 UTC 当本地时间解析，东八区「最近学习」会凭空差 8 小时（P1.2 实际修掉的缺陷）。

### 9.3 进度规则

唯一实现是 `app/services/learning.py`：四态权重 `0 / 0.4 / 0.7 / 1`，
`进度 = round(Σ 权重 / 总数 × 100)`，总数为 0 时为 0。课程、章节、测试脚本都引用这一份，
前端 `utils/learning.ts` 只做文案与展示，不重复计算。

历史状态值（P1.1 的 `learning` / `mastered`）在写入时归一、在启动迁移时批量归一，
读库时还有 `safe_status()` 兜底（未知值按 `not_started` 处理），避免一条脏数据让整页 500。

### 9.4 前端页面

| 路由 | 视图 | 关键交互 |
| --- | --- | --- |
| `/courses` | `CoursesView` | 搜索（300ms 防抖）、三种排序、行内「继续学习 / 编辑 / 删除」；编辑弹窗含图标选择与原始教材信息；空状态给出导入入口 |
| `/courses/:id` | `CourseDetailView` | 头部信息 + 编辑/删除；进度概览（进度条 + 四态计数 + 最近学习）；左目录（章节折叠、章节与知识点的改名/上下移/增删）；右阅读面板（Markdown 正文、四态状态开关、上下翻页） |

布局是「左目录 + 右阅读」两栏（`grid-template-columns: 360px 1fr`），1200px 以下自动叠成单列。
目录里的操作按钮平时半透明，hover 行时变实——避免几十个图标把目录挤满，同时保持键盘和自动化点击可达
（只调 `opacity`，不设 `pointer-events: none`）。

### 9.5 Markdown 渲染

`src/utils/markdown.ts` 是自研渲染器，约 200 行，策略是**先做 HTML 转义、再逐行组装标签**：

- 支持：标题、段落、代码围栏（保留语言标识）、行内代码、粗体/斜体/删除线、有序/无序列表（一层嵌套）、引用、分隔线、表格、链接；
- P1.3 补充 KaTeX 行内/块级公式与轻量代码高亮；不支持裸 HTML、图片、脚注、Mermaid，按文本/代码展示；
- 链接只放行 `http(s)` / `mailto` / 站内相对路径 / 锚点，`javascript:` 之类降级成纯文本。

不引 marked + DOMPurify 的原因：当前需求只需要展示教材里的常见语法，自己 200 行就能覆盖，
而两个第三方依赖会带来额外的升级与 XSS 面；代价是渲染能力受限（已在上面写清）。

### 9.6 本阶段的取舍

- 学习状态只有四态，**没有**「掌握度」与自动评估：掌握度需要证据链，属 P1.4/P2。

## 10. P1.3 教学链路

`ClassroomView → POST /classroom/sessions → /start 或 /messages → teaching_prompt → llm_client → 用户配置的 /chat/completions`。

- `services/classroom_service.py` 校验 active 课程、知识点归属与模型。`learning_sessions` 唯一约束保护课程/知识点；模型删除后外键置空并回退默认。
- `api/v1/classroom.py` 在流开始前检查密钥、构造上下文，用户消息/重生成替换/助手占位在同一个事务提交；模型不存在或无法解密不会损失上一回答。
- `stream_registry.py` 的每会话锁仅适用于单 worker。停止 Event 和上游读取并发等待，停止时取消等待并关闭 HTTP 流，而非等到下一个 token 才停止。
- SSE：`meta` 标识消息、`delta` 传文本、`done` 带已保存消息、`error` 带安全错误。正文约每 1.2 秒检查点保存，终态再次提交；进程崩溃最多可能损失最后一个检查点内的增量。
- 教学 prompt 独立分层，保留首次 AI 主动讲解以支持“解释刚才代码”。字符预算不是精确 token 计数，超大消息截断不修改原记录。
- 首个正文增量最多等待 60 秒（配置读超时更小时取更小值），后续读超时默认 180 秒，整轮默认 240 秒；回答默认最大 4096 tokens。配置见 `.env.example`。
- 上游 HTTP/SSE 错误不回显原文；输出跨 chunk 检查当前密钥并隐藏；日志不打印请求体、提示词或密钥，关闭 httpx INFO URL 日志。
- 前端请求以 AbortController 与会话序号隔离，旧请求回调/finally 不修改新知识点。生成中刷新时只轮询数据库已收到的检查点，不伪造模型增量。
- 教室复用独立全屏路由 `/courses/:id/classroom`，模型选择使用现有模型 API，无前端持久化密钥。
- 本地单用户数据目录隔离，不提供多账号/多租户隔离。默认仅 loopback；不得把服务直接暴露到公网。公开分发前仍需本机鉴权和来源校验。

接口契约见 `API_CLASSROOM.md`；测试与限制见 `TEST_REPORT_P1.3.md`。
- 没有拖拽排序：上下移按钮 + 全量 ID 提交已经满足「调整顺序并持久化」，拖拽留到有实际反馈需求时再做。
- 章节/知识点编辑用弹窗而不是就地编辑：P1.1 的就地编辑在 blur 时触发保存，容易吞掉紧接着的点击（当时的已知问题），
  详情页改用显式弹窗 + 显式保存，交互更可预期。
