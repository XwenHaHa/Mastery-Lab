# Mastery Lab · P1.1 教材导入测试报告

- 报告日期：2026-11-16
- 被测范围：P1.1「教材导入 + 课程解析 + 课程结构编辑 + 课程创建」
- 测试方式：真实前后端进程 + 真实浏览器（Chromium，无 mock、无桩数据）
- 结论：**主流程全部通过（10/10）**；过程中发现 **4 个缺陷，已全部修复并复测通过**，另有 4 项已知限制与 2 项风险，见第八、九、十节。

---

## 一、交付物对照

| 需要的内容 | 位置 |
| --- | --- |
| 教材导入页面截图 | `docs/review/p1-1/screenshots/01-import-page.png` |
| Markdown 教材测试结果 | 本报告第四节 + `docs/qa/parse-result.json`、`02-md-parsed.png` |
| PDF 教材测试结果 | 本报告第五节 + `06-pdf-parsed.png`、`08-scanned-pdf-error.png` |
| 多级标题与代码块解析结果 | 本报告第四节明细表 + `docs/qa/parse-result.json` |
| 课程结构编辑截图 | `docs/review/p1-1/screenshots/03-structure-edit.png` |
| 课程创建成功截图 | `04-md-course-created.png`、`07-pdf-course-created.png`、`05-course-center.png` |
| SQLite 持久化验证结果 | 本报告第七节 + `docs/qa/db-check-result.json` |
| 完整测试报告 | 本文件 |

配套脚本（可复跑）：

| 脚本 | 作用 |
| --- | --- |
| `docs/qa/ui_flow.py` | Playwright 端到端：上传 → 解析 → 编辑 → 创建 → 课程中心 → PDF → 扫描件报错 |
| `docs/qa/parse_check.py` | 直接调用解析器，输出多级标题/代码块/PDF 结构的 JSON |
| `docs/qa/db_check.py` | 只读直连 SQLite，导出课程目录树 |
| `docs/qa/fixtures/make_pdfs.py` | 生成两份 PDF 样本（有文本层 / 模拟扫描件） |

---

## 二、测试环境

| 项 | 值 |
| --- | --- |
| 系统 | Windows 10（10.0.19045） |
| Node / pnpm | v22.18.0 / 10.34.5 |
| Python | 3.13.1（`apps/api/.venv`） |
| 浏览器 | Playwright Chromium，视口 1440×900，`deviceScaleFactor=2`（截图 2880px 宽） |
| 服务 | 前端 `http://127.0.0.1:5173`，后端 `http://127.0.0.1:8000`，由 `scripts/dev.ps1` 启动 |
| 数据库 | `data/mastery_lab.db`（WAL 模式） |

测试样本：

| 文件 | 大小 | 用途 |
| --- | --- | --- |
| `docs/qa/fixtures/advanced-python.md` | 2,621 B | 一到六级标题、python/bash/json 三种代码围栏、行内代码与加粗 |
| `docs/qa/fixtures/pdf-asyncio-textlayer.pdf` | 4,081 B | 2 页、有文本层、含「第 X 章」与「1.1 标题」、含 2 行固定缩进 |
| `docs/qa/fixtures/pdf-scanned-like.pdf` | 1,880 B | 2 页纯图形，无文本对象（模拟扫描件） |

---

## 三、结果矩阵

| # | 用例 | 方法 | 实际结果 | 结论 |
| --- | --- | --- | --- | --- |
| 1 | 打开导入页 | 浏览器访问 `/courses/import` | 标题「导入教材」，拖拽区可见 | 通过 |
| 2 | 上传 Markdown 并解析 | 真实 `POST /api/v1/courses/upload` | 201，3 章 / 8 知识点 / 5 代码块 | 通过 |
| 3 | 多级标题归类 | 对照 `parse-result.json` | 一级→课程名，二级→章节，三至六级→知识点 | 通过 |
| 4 | 代码块识别 | 同上 | 5 个代码围栏，语言与行数均正确 | 通过 |
| 5 | 结构编辑：改名 | 章节标题输入框改名 + Enter | `PATCH /api/v1/chapters/4` → 200，列表即时更新 | 通过 |
| 6 | 结构编辑：调整顺序 | 第二章「上移」 | `PATCH /api/v1/courses/2/reorder` → 200，顺序变为 2→1→3 | 通过（修复后） |
| 7 | 结构编辑：新增章节 | 「添加章节」弹窗 | `POST /api/v1/courses/2/chapters` → 200，追加第 4 章 | 通过 |
| 8 | 确认创建课程 | 「确认创建课程」 | `POST /api/v1/courses/2/confirm` → 200，跳转 `/courses/2` | 通过 |
| 9 | PDF 解析 | 真实上传 | 201，2 章 / 4 知识点 / 1 代码块 | 通过（修复后） |
| 10 | 扫描件 PDF 必须报错 | 真实上传 | 422 + 明确中文提示，未生成任何课程 | 通过 |
| 11 | SQLite 持久化 | 重启前后直连数据库对比 | 课程 3 / 章节 9 / 知识点 16 行，重启后结构与编辑结果一致 | 通过 |

一次运行中的完整接口流水（来自 `docs/qa/ui-flow-result.json` 的 `apiCalls`）：

```
GET   200 /api/v1/health
POST  201 /api/v1/courses/upload      ← advanced-python.md
PATCH 200 /api/v1/chapters/4          ← 改名（Enter 触发）
PATCH 200 /api/v1/chapters/4          ← 改名（点击按钮时 blur 触发，重复但幂等）
PATCH 200 /api/v1/courses/2/reorder   ← 上移章节
POST  200 /api/v1/courses/2/chapters  ← 新增章节
POST  200 /api/v1/courses/2/confirm   ← 确认创建
GET   200 /api/v1/courses/2
GET   200 /api/v1/courses
POST  201 /api/v1/courses/upload      ← pdf-asyncio-textlayer.pdf
POST  200 /api/v1/courses/3/confirm
POST  422 /api/v1/courses/upload      ← pdf-scanned-like.pdf（预期报错）
```

浏览器控制台仅有 1 条 `Failed to load resource: 422`，正是扫描件用例的预期结果；无 JS 异常、无失败请求。

---

## 四、Markdown 解析结果（多级标题 + 代码块）

![Markdown 解析预览](review/p1-1/screenshots/02-md-parsed.png)

解析器把标题层级映射为课程结构，实测结果：

| 章节（二级标题） | 知识点（三~六级标题） | 代码块 |
| --- | --- | --- |
| 第 1 章 进程、线程与协程 | `### 1.1 为什么需要并发` | python / 6 行 |
| | `#### 1.1.1 GIL 的边界` | bash / 1 行 |
| | `##### 1.1.1.1 何时绕过 GIL` | — |
| | `###### 1.1.1.1.1 实验设计` | — |
| | `### 1.2 事件循环` | json / 1 行 |
| 第 2 章 实战：并发下载 | `### 2.1 串行版本` | python / 7 行 |
| | `### 2.2 异步版本` | python / 13 行 |
| 第 3 章 练习 | （章节下无子标题，自动补同名知识点） | — |

统计：`chapters=3`、`knowledgePoints=8`、`codeBlocks=5`、`characters=1615`、`warnings=[]`。

要点确认：

1. 一级标题只作课程名（`Python 进阶：并发与异步`），不会变成章节；
2. **六级标题**正确归属为知识点，且归属于最近的上级章节（1.1.1.1.1 落在第 1 章）；
3. 代码围栏的语言标识被保留（python/bash/json），行数不含围栏行；
4. 代码块内容随知识点正文一起保存（`content` 字段中为 ```python … ``` 形式），P2 讲代码时可直接取用；
5. 行内代码与 `**加粗**` 在标题与摘要中被剥离，不污染课程名。

原始数据：`docs/qa/parse-result.json`。

---

## 五、PDF 解析结果

![PDF 解析预览](review/p1-1/screenshots/06-pdf-parsed.png)

| 章节 | 知识点 | 代码块 |
| --- | --- | --- |
| 第 1 章 协程与事件循环 | 1.1 什么是协程 | — |
| | 1.2 事件循环的角色 | — |
| 第 2 章 异步 HTTP 请求 | 2.1 用 aiohttp 并发 | text / 2 行 |
| | 2.2 超时与重试 | — |

统计：`chapters=2`、`knowledgePoints=4`、`codeBlocks=1`、`characters=464`、`pages=2`、`warnings=[]`。

难点与处理：

- 首页第一行「Python 异步编程实践手册」被识别为课程名，不会退化成「第 1 页」；
- 「第 1 章 / 第 2 章」及「1.1 / 2.1」均被识别为标题层级，未出现「开篇（第 N 页）」兜底章节；
- 固定 4 空格缩进的内容被收成 `text` 代码块（PDF 无法得知真实语言，如实标注 `text`，不猜测）。

### 扫描件（无文本层）必须明确报错

![扫描件 PDF 报错](review/p1-1/screenshots/08-scanned-pdf-error.png)

```
POST /api/v1/courses/upload → 422
提示：这个 PDF 没有可提取的文本层（多为扫描件或纯图片），当前版本无法识别其文字。
      请先用 OCR 工具转成文本，或改用 Markdown 教材。
```

数据库中没有新增任何课程记录，符合「不编造章节结构」的设计承诺。

---

## 六、课程结构编辑与课程创建

![结构编辑](review/p1-1/screenshots/03-structure-edit.png)

在预览页完成的编辑（全部经真实接口落库）：

| 操作 | 编辑前 | 编辑后 |
| --- | --- | --- |
| 章节改名 | 第 1 章 进程、线程与协程 | 第 1 章 并发模型（导入后改名） |
| 调整顺序（上移第二章） | 1 → 2 → 3 | 2 → 1 → 3 |
| 新增章节 | 3 章 | 4 章（第 4 章 附加练习（手动添加）） |

确认创建后跳转课程详情（课程名来自一级标题，章节/知识点结构与预览一致）：

![Markdown 课程创建成功](review/p1-1/screenshots/04-md-course-created.png)

PDF 课程同样创建成功：

![PDF 课程创建成功](review/p1-1/screenshots/07-pdf-course-created.png)

课程中心列表可同时看到新建的两门课程与原有的《Python 字典与集合》：

![课程中心](review/p1-1/screenshots/05-course-center.png)

导入入口页（拖拽区与说明）：

![导入页](review/p1-1/screenshots/01-import-page.png)

---

## 七、SQLite 持久化验证

验证方式：不经过任何接口，直接用 `sqlite3` 只读连接 `data/mastery_lab.db` 查询行与目录树；随后停止前后端进程、再重新启动，重复查询并比对。

服务运行期间（写入后）：

```
表: ['app_settings', 'chapters', 'courses', 'knowledge_points', 'model_configs']
  courses: 3 行
  chapters: 9 行
  knowledge_points: 16 行

courses:
  1  Python 字典与集合            active  markdown  dict-notes.md               719 B
  2  Python 进阶：并发与异步      active  markdown  advanced-python.md        2,621 B
  3  Python 异步编程实践手册      active  pdf       pdf-asyncio-textlayer.pdf 4,081 B
```

课程 2 的章节顺序与名称（直接从 `chapters.sort_order` 读出），与 UI 上的编辑结果完全一致：

```
[1] 第 2 章 实战：并发下载         → 2.1 串行版本(1 code) | 2.2 异步版本(1 code)
[2] 第 1 章 并发模型（导入后改名） → 1.1(1) | 1.1.1(1) | 1.1.1.1(0) | 1.1.1.1.1(0) | 1.2(1)
[3] 第 3 章 练习                   → 第 3 章 练习(0)
[4] 第 4 章 附加练习（手动添加）   → （空章节，导入页允许）
```

停止进程后再次直连查询：`courses=3 / chapters=9 / knowledge_points=16`，结构不变。
重启服务后通过接口复查：`GET /api/v1/courses/2` 返回 `status=active`、4 章 / 8 知识点，章节顺序与改名结果与停机前一致；`GET /api/v1/courses` 三项统计（章 / 点 / 代码块）分别为 `4/8/5`、`2/4/1`、`3/4/3`。

结论：数据确实落在磁盘文件中，不依赖进程内存；知识点初始学习状态为 `not_started`，与导入页脚注一致。

---

## 八、缺陷清单（4 项，均已修复并复测）

| # | 缺陷 | 现象（修复前） | 根因 | 修复 |
| --- | --- | --- | --- | --- |
| 1 | PDF 章节标题无法识别 | 「第 1 章 协程与事件循环」「第 2 章 异步 HTTP 请求」均被当成正文，全部内容挤进兜底章节「开篇（第 1 页）」，只剩 1 章 | `CN_CHAPTER_RE` 不允许「第」与数字之间有空格，中文排版常见的「第 1 章」不匹配 | 正则改为 `^第\s*[…]{1,4}\s*[章节篇部]…`，仍不匹配「第 1 页」 |
| 2 | PDF 知识点正文被静默丢弃 | 每个知识点的 `content` 为空，`excerpt` 为空字符串 | `_collect_code()` 里 `sink.append(line)` 只在「刚关闭一个代码块」的分支执行，普通正文行在缓冲区为空时被丢弃 | 非代码行无条件写入 `sink`，代码块用内部 `flush()` 收口 |
| 3 | PDF 缩进代码永远识别不出 | `codeBlocks` 恒为 0 | 该函数被按「单行」调用（`_collect_code([line], …)`），跨行缩进无法聚成一个块 | 改为按知识点累积原始行，`flush_point()` 时一次性调用 |
| 4 | 改名后第一次点击被吞掉 | 章节改名后立刻点「上移」，顺序不变；改名后点工具栏任何按钮都要点两次 | 输入框 `blur` 触发改名保存 → `saving` 打开全列表 `v-loading` 遮罩 → 遮罩在 mousedown 与 mouseup 之间出现，`click` 事件不再派发到按钮 | `saveCourseTitle / saveChapterTitle / savePointTitle` 不再切换 `saving`；遮罩只用于增删、排序、创建等结构性操作 |

修复位置：

- `apps/api/app/services/pdf_parser.py`（缺陷 1、2、3）
- `apps/web/src/views/CourseImportView.vue`（缺陷 4）

复测证据：

| 缺陷 | 修复前 | 修复后 |
| --- | --- | --- |
| 1 | 1 章 / 4 点，章节名「开篇（第 1 页）」 | 2 章：第 1 章 协程与事件循环、第 2 章 异步 HTTP 请求 |
| 2 | 各知识点 `excerpt` 为空 | 正文完整（「普通函数调用一次执行到 return 才返回…」） |
| 3 | `codeBlocks=0` | `codeBlocks=1`（text / 2 行） |
| 4 | 点「上移」只发 `PATCH /chapters/4`，无 reorder | `PATCH /courses/2/reorder` 200，顺序 2→1→3 |

前端改动后 `pnpm run typecheck`（`vue-tsc --noEmit`）通过；后端改动后重启服务，PDF 上传与解析实测通过。

---

## 九、已知限制（当前版本行为，非缺陷）

1. **PDF 页脚会混入正文**：样本每页页脚「- 1 -」被当作正文留在知识点内容里（见 `parse-result.json` 中 `1.2 事件循环的角色` 的 excerpt 末尾）。真实书籍的页码/页眉同样会带进来。彻底解决需要版面分析，本阶段不做。
2. **PDF 代码块语言一律记为 `text`**：PDF 里没有语言信息，不做猜测，交由后续教师模型或用户判断。
3. **章节下没有子标题时，知识点与章节同名**：第 3 章只有一段正文，于是生成「第 3 章 练习」知识点承载正文。这是为了避免空章节的兜底策略，用户可在预览页改名或删除。
4. **改名会发两次相同的 PATCH**：Enter 与随后的 blur 各触发一次保存；请求幂等，结果正确，只是多一次写入（接口流水中的两条 `PATCH /chapters/4` 即此现象）。

---

## 十、风险与建议

| 风险 | 说明 | 建议 |
| --- | --- | --- |
| WAL 未及时落盘 | 服务运行中主库文件仅 4 KB，实际数据在约 1.5 MB 的 `mastery_lab.db-wal`；若只拷贝 `mastery_lab.db` 会丢数据 | 备份/搬移时连同 `-wal`、`-shm` 一起复制；或在停机流程里加一次 `PRAGMA wal_checkpoint(TRUNCATE)` |
| 停服务是按进程树强杀 | `scripts/stop.ps1` 用 `taskkill /T /F`，SQLite 没有优雅关闭机会 | 后续可改为先发关闭信号并等待，再强制清理 |
| PDF 结构强依赖排版 | 教材若用字号/加粗而不是编号区分标题，会被按页组织 | 已在 `warnings` 中提示，后续可加「按字号聚类」的启发式 |
| 导入后无内容摘要 | 课程卡片只显示章/点/代码数 | P1.2 进入教学对话时再补 `description` 展示 |

---

## 十一、如何复跑

```powershell
cd "E:\前端转AI_Agent全栈\Mastery Lab"
powershell -ExecutionPolicy Bypass -File scripts\dev.ps1   # 后台启动前后端

# 解析器级核对（不写库）
apps\api\.venv\Scripts\python.exe docs\qa\parse_check.py

# 端到端 UI + 截图（脚本会先清理上次遗留的草稿）
python docs\qa\ui_flow.py

# SQLite 直连校验（可停机后再跑一次做对照）
apps\api\.venv\Scripts\python.exe docs\qa\db_check.py
```

注意：`ui_flow.py` 会在数据库里留下两门正式课程（Markdown 与 PDF 各一门）。如需回到干净状态，可在课程中心删除它们，或调用 `DELETE /api/v1/courses/{id}`。
