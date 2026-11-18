# Mastery Lab

本地优先、面向公众分发的 AI 互动技术学习平台。用户导入 Markdown / PDF 教材后，由 AI 扮演一名耐心的技术老师：
先讲清概念、给出最小可运行示例、一次只问一个问题、陪着写代码、跑起来看结果，直到学习者能独立实现。

当前进度：**P0 至 P1.3 已实现；P1.4 六阶段代码及模拟流程已通过测试，尚未完成真实模型教学验收**。换机开发与未结事项见 `docs/DEV_HANDOFF.md`。
P1.3 已通过真实模型流式教学、追问、中断与对话恢复测试；后续重复调用遇到网关限流，完整记录见 `docs/TEST_REPORT_P1.3.md`。教学状态机/掌握度留在 P1.4，代码执行留在 P2。

---

## 1. 环境要求

| 组件 | 版本 | 说明 |
| --- | --- | --- |
| Windows | 10 / 11 | 首版目标系统，密钥加密依赖 Windows DPAPI |
| Node.js | ≥ 18（实测 v22.18.0） | 运行前端 |
| pnpm / npm | pnpm ≥ 8（实测 10.34.5），或 npm | 安装前端依赖，脚本会自动选择 |
| Python | ≥ 3.11（实测 3.13.1） | 运行后端 |

默认端口：后端 `127.0.0.1:8000`，前端 `127.0.0.1:5173`。需要的任一端口被占用时启动脚本会报错，
不会静默换端口，避免出现「页面打不开但不确定连到哪」的情况。

## 2. 第一次运行

```powershell
# 在刚克隆的项目根目录执行以下命令

# 可选：先确认工具链与端口状态
powershell -ExecutionPolicy Bypass -File scripts\check-env.ps1

# 一键启动（自动创建 apps\api\.venv、安装依赖、等待健康检查后启动前端）
powershell -ExecutionPolicy Bypass -File scripts\dev.ps1
```

启动成功后：

- 页面：<http://127.0.0.1:5173/>
- Swagger 文档：<http://127.0.0.1:8000/docs>
- 日志：`data\run\api.log`、`data\run\api.err.log`、`data\run\web.log`、`data\run\web.err.log`
- 进程号：`data\run\api.pid`、`data\run\web.pid`

停止：

```powershell
powershell -ExecutionPolicy Bypass -File scripts\stop.ps1
```

**已有旧库时先验收，不要直接升级。** 本工作区含尚未完成交付的 P1.4 代码；当前后端启动会将 schema 4 升到 5。要与日常实例并行，请在项目根目录另开 PowerShell，使用独立目录和端口（每个数据目录只启动一套服务）：

```powershell
$env:MASTERY_LAB_DATA_DIR = Join-Path $PWD 'data\qa-p0-20261118'
$env:MASTERY_LAB_DATABASE_URL = 'sqlite:///' + ((Join-Path $env:MASTERY_LAB_DATA_DIR 'mastery_lab.db') -replace '\\','/')
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\dev.ps1 -ApiPort 18080 -WebPort 15173
# 浏览器：http://127.0.0.1:15173/ ；Swagger：http://127.0.0.1:18080/docs
# 停止此实例（保留以上环境变量）：
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\stop.ps1
```

启动记录及日志在所选数据目录的 `run/`。停止脚本只根据该目录中匹配的 PID 和启动时间结束进程，不按端口猜测归属。P0 验收证据见 `docs/TEST_REPORT_P0.md`。

## 3. 配置模型

1. 打开页面 → 左侧「模型配置」→「新建配置」。
2. 填写：配置名称、API Base URL（如 `https://api.deepseek.com/v1`）、模型名称（如 `deepseek-chat`）、API Key。
3. 点「测试连接」——会真的向该地址发一次 `/chat/completions` 请求，成功才提示可用。
4. 保存。Windows 下经 DPAPI 加密入库，浏览器之后只看到固定掩码 `****`。若修改 Base URL，须重新填写新地址的密钥才能测试或保存；未保存的草稿测试不会覆盖已保存参数的结果。远端提供商请使用 HTTPS，不要通过远程明文 HTTP 发送密钥。

支持多个配置，但同一时间只有一个「默认模型」。P1.1 的教材解析是纯本地的确定性解析，**不依赖任何模型**。

## 4. 导入教材与课程中心

1. 左侧「课程中心」→「导入教材」。
2. 拖入或选择文件：Markdown（`.md` / `.markdown` / `.txt`）或 PDF（`.pdf`），单个文件最大 20 MB。
3. 上传后自动解析，进入结构预览：
   - Markdown：`#` 作课程名、`##` 作章节、`###`–`######` 作知识点，代码围栏连同语言标识一起保留；
   - PDF：抽取文本层后按「第 X 章」「1.2 标题」「全大写短行」等启发式识别章节，识别不到就按页组织并在页面上提示；
   - 扫描版 PDF 没有文本层时**明确报错**（HTTP 422），不伪造解析结果。
4. 在预览页可以直接改名、删除章节/知识点、上下移动顺序、添加章节或知识点。
5. 点「确认创建课程」才会写入正式课程（`status=active`）；点「取消导入」会删除草稿与已落盘的教材文件。

课程中心展示：课程名、课程简介、图标/教材来源、章节与知识点数量、学习进度、最近学习时间、创建时间，支持搜索与排序（最近学习 / 创建时间 / 最近更新），可编辑名称、简介与图标，可删除课程。

## 5. 课程详情、目录管理与学习状态

点课程行的「继续学习」进入课程详情（`/courses/{id}`）：

- 顶部是进度概览：加权进度、四种状态的数量、最近学习的 3 个知识点；
- 左侧是课程目录：章节可折叠，章节显示「知识点数 · 进度%」，侧栏支持章节与知识点的改名、上移/下移、增删；
- 右侧是阅读面板：显示知识点正文（Markdown 渲染，支持代码围栏、列表、表格、引用、链接），底部可「上一个/下一个」翻页；
- 阅读面板里的「学习状态」四态可手工切换：未学习 / 学习中 / 待复习 / 已完成，切换后进度立即重算并写入数据库。

学习进度计算规则（代码在 `apps/api/app/services/learning.py`，前后端与文档统一）：

```
进度 = round(Σ 状态权重 / 知识点总数 × 100)
权重：未学习 0 · 学习中 0.4 · 待复习 0.7 · 已完成 1
```

知识点总数为 0 时进度为 0（空课程不算「已完成」）。章节进度用同一公式，只在章节内的知识点上计算。
掌握度（`mastery_level`）不参与计算，P1.2 不写该字段。

进入 AI 学习教室后，也可直接在当前知识点标题旁点击「标记为已完成」，完成后可「改为学习中」。保存会同步目录和课程进度，不清空对话、不自动跳到下一知识点；无需返回课程详情操作。AI 生成结束不会自动标记学习完成。

## 6. 常用命令

| 目的 | 命令 |
| --- | --- |
| 只启动后端 | `powershell -File scripts\start-api.ps1` |
| 只启动前端 | `powershell -File scripts\start-web.ps1` |
| 停止全部 | `powershell -File scripts\stop.ps1` |
| 强制重装后端依赖 | `powershell -File scripts\start-api.ps1 -Reinstall` |
| 前端类型检查 | `cd apps\web; pnpm run typecheck` |
| 前端生产构建 | `cd apps\web; pnpm run build` |
| 直接跑后端（调试） | `cd apps\api; .venv\Scripts\python.exe -m uvicorn app.main:app --reload` |
| P1.2 后端接口回归 | `python docs\qa\p12_api_check.py`（需后端已启动） |
| P1.2 UI 回归 + 截图 | `python docs\qa\p12_ui_flow.py`（需前后端已启动） |

## 7. 接口一览（P0 + P1.1 + P1.2）

P1.3 教室的 8 个接口及 SSE 事件见 `docs/API_CLASSROOM.md`。

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/api/v1/health` | 健康检查（数据库、密钥方案、运行环境） |
| GET/POST | `/api/v1/models` | 模型配置列表 / 新建 |
| GET/PUT/DELETE | `/api/v1/models/{id}` | 模型配置详情 / 修改 / 删除 |
| POST | `/api/v1/models/test` | 连接测试（支持未保存的表单） |
| POST | `/api/v1/courses/upload` | 上传教材 → 解析为课程草稿 |
| GET | `/api/v1/courses?status=&q=&sort=` | 课程列表（`sort` 取 `updated`/`created`/`studied`） |
| GET | `/api/v1/courses/{id}` | 课程详情（章节 + 知识点目录，不含正文） |
| PATCH | `/api/v1/courses/{id}` | 修改课程名/简介/图标 |
| POST | `/api/v1/courses/{id}/confirm` | 确认创建正式课程 |
| DELETE | `/api/v1/courses/{id}` | 删除课程（级联章节/知识点/学习状态 + 清理教材文件） |
| GET | `/api/v1/courses/{id}/progress` | 学习进度总览（整体 + 分章节 + 最近学习） |
| GET | `/api/v1/courses/{id}/chapters` | 获取课程章节（含知识点摘要） |
| POST | `/api/v1/courses/{id}/chapters` | 新增章节 |
| PATCH | `/api/v1/courses/{id}/chapters/reorder` | 调整章节顺序（传全量 ID 排列） |
| PATCH/DELETE | `/api/v1/courses/{id}/chapters/{chapterId}` | 修改 / 删除章节（校验归属） |
| GET | `/api/v1/courses/{id}/knowledge-points?status=&q=` | 课程知识点平铺列表（可按状态过滤、搜索） |
| POST | `/api/v1/courses/{id}/chapters/{chapterId}/knowledge-points` | 新增知识点 |
| PATCH | `/api/v1/courses/{id}/chapters/{chapterId}/knowledge-points/reorder` | 调整知识点顺序 |
| PATCH/DELETE | `/api/v1/courses/{id}/knowledge-points/{pointId}` | 修改 / 删除知识点（校验归属） |
| PATCH | `/api/v1/courses/{id}/knowledge-points/{pointId}/status` | 更新知识点学习状态 |
| GET | `/api/v1/knowledge-points/{pointId}` | 知识点详情（正文 + 前后邻居） |
| PATCH | `/api/v1/courses/{id}/reorder` | 批量调整章节/知识点顺序（导入预览用） |

P1.1 的扁平路径（`/chapters/{id}`、`/knowledge-points/{id}`）继续保留给导入流程使用；
P1.2 的界面一律走带 `courseId` 的课程内路径，服务层会校验章节/知识点确实属于该课程。

## 8. 目录结构

```
Mastery Lab/
├── AGENTS.md                  # P0 任务书
├── README.md
├── plan/                      # 阶段任务书（P1.1 等）
├── apps/
│   ├── api/                   # FastAPI 后端
│   │   ├── app/
│   │   │   ├── main.py        # 应用装配：CORS、统一异常、访问日志
│   │   │   ├── core/          # 配置、统一响应、密钥加密
│   │   │   ├── db/            # 引擎、会话、ORM 模型（模型配置 + 课程三表）
│   │   │   ├── schemas/       # Pydantic 模型（对外 camelCase）
│   │   │   ├── services/      # 模型配置、教材存储、md/pdf 解析、课程业务
│   │   │   └── api/v1/        # health · models · courses
│   │   ├── requirements.txt
│   │   └── .env.example
│   └── web/                   # Vue 3 + Vite 前端
│       ├── src/
│       │   ├── api/           # fetch 封装 + 上传进度（XHR）
│       │   ├── layouts/       # AppShell：侧栏 + 顶栏
│       │   ├── views/         # 概览 / 课程中心 / 导入 / 课程详情 / 模型配置 / 设置 / 404
│       │   ├── stores/        # theme · system · models · courses
│       │   └── styles/        # 设计令牌（深色默认 + 浅色）
│       └── vite.config.ts     # /api → 127.0.0.1:8000
├── runtime/runner/            # P2 代码沙箱占位（未实现）
├── data/                      # SQLite、密钥、上传、教材原文、运行日志
├── docs/                      # PRD / 架构 / 数据库 / 开发计划 / 审查图
└── scripts/                   # check-env · start-api · start-web · dev · stop
```

## 9. 数据与安全

- 所有数据都在本机 `data/` 目录；数据库 `data/mastery_lab.db`（SQLite，WAL）。
- 教材原文按 `data/courses/<随机目录>/<原文件名>` 保存，路径只存相对 `data/` 的形式，换机器可用。
- API Key 两种存储方案：Windows 上优先 **DPAPI**（`dpapi:v1:` 前缀，按当前 Windows 用户加密）；
  Windows 加密失败则拒绝保存，不自动降级；非 Windows 使用 **Fernet + 本地主密钥文件**（`data/secrets/master.key`）。旧 Fernet 密文仍支持读取。
- 模型接口不返回密钥字符，也不记录密钥。`apiKeyHint` 只返回 `****`，包括读取旧版记录时。
- 上传安全：只按扩展名白名单接收、单文件 20 MB 上限、文件名只取 basename 并过滤控制字符、
  读写路径必须落在 `data/courses` 内（防目录穿越）、PDF 校验 `%PDF` 魔数、文本校验编码。
- 服务只监听 `127.0.0.1`，不对局域网暴露；教材不会被上传到任何外部服务器。

## 10. 当前未完成（不要误解为已完成）

- 完整教学状态机、掌握度评估与错误归因 —— P1.4；AI 对话与流式输出已在 P1.3 实现。
- Monaco 编辑器、Python 代码执行沙箱、运行结果回传 —— P2（`runtime/runner` 仅占位）。
- 掌握度判定：`mastery_level` 字段留到后续阶段，P1.2 **不虚构掌握度**，只记录四态学习状态。
- 扫描版 PDF 的 OCR —— 当前明确提示无法识别，不做伪解析。
- 未引入 pytest / vitest；P1.3 使用标准库 unittest、Node test 与 Playwright，可复跑且不增加运行时依赖。
- 数据库迁移框架：目前只支持「新增表 / 新增列」，改现有列需要手工处理（见 `docs/DATABASE.md` 第 6 节）。
- 模型配置页的时间字段仍按 naive 本地时间显示（P0 遗留，课程相关接口已在 P1.2 修正为 UTC 带时区）。

更完整的范围、验收记录与风险见 `docs/` 目录：

- P1.1 端到端测试报告：`docs/TEST_REPORT_P1.1.md`（导入页 / Markdown / PDF / 结构编辑 / 课程创建的 8 张截图）。
- P1.2 端到端测试报告：`docs/TEST_REPORT_P1.2.md`（课程中心 / 课程详情 / 目录管理 / 学习状态，14 张截图在 `docs/review/p1-2/`）。

## 12. AI 学习教室（P1.3）

1. 在模型配置中保存并测试可用模型。导入教材、确认创建课程。
2. 课程中心 → 课程详情 → 选择知识点 →「开始学习」。地址为 `/courses/:id/classroom?point=:pointId`。
3. 新知识点自动开始讲解；老师先解释概念、展示完整案例，再解释代码。代码仅展示，不在浏览器执行。
4. 在下方输入问题，Enter 发送、Shift+Enter 换行；也可使用「再讲一遍」「换个例子」等六个快捷入口。
5.「停止生成」会取消当前请求并保留内容；可继续提问或「重新生成」最后一个回答。刷新或切换知识点后恢复各自的历史。
6. 右侧可选择已保存模型；生成中不允许切模型。学习状态/进度沿用课程详情的手工标记，不自动判断掌握。

教材与记录保存在本机，但当前知识点节选和有限对话会发送到所选模型服务。推荐 HTTPS；HTTP 网关无法保证传输保密。密钥只在后端解密，错误不回显上游原文。单本机用户、单 Uvicorn worker，不提供云端账号隔离。

```powershell
# 根目录运行：离线逻辑测试，不访问真实模型，不修改用户数据库
apps\api\.venv\Scripts\python.exe docs\qa\p13_backend_test.py
node --test docs\qa\p13_frontend_test.mjs
npm --prefix apps/web run build

# 需服务已启动、有可用模型额度；会产生真实模型调用费用
apps\api\.venv\Scripts\python.exe docs\qa\p13_real_check.py --keep-course
# Python 环境需已有 playwright 和 Chromium
python docs\qa\p13_ui_flow.py
# 上游限流时可单独跑模拟交互验收，不能替代真实模型测试
python docs\qa\p13_ui_flow.py --mock
```

`--keep-course` 保留专用验收课程供 UI 使用；不传时脚本结束自动清理。UI 脚本仅操作该专用课程。验收结果、参数、截图索引和本轮文件清单见 `docs/TEST_REPORT_P1.3.md`。
- 可复跑脚本在 `docs/qa/`：`p12_api_check.py`（真实数据库 + HTTP 的 52 项断言）、`p12_ui_flow.py`（Playwright 全流程）。
