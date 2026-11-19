# Mastery Lab 数据库（P0 至 P1.3 实际结构）

- 引擎：SQLite 3（Python 内置 `sqlite3` 驱动）
- 文件：`data/mastery_lab.db`（可用 `MASTERY_LAB_DATABASE_URL` 覆盖）
- ORM：SQLAlchemy 2.0（`DeclarativeBase` + `Mapped` 类型注解）
- 连接参数：`check_same_thread=False`，连接时执行 `PRAGMA journal_mode=WAL`、`PRAGMA foreign_keys=ON`
- 建表方式：应用启动（lifespan）时 `Base.metadata.create_all()`，随后执行 `db/__init__._ensure_columns()` 的**增量加列**迁移；**不使用迁移框架**

## 1. 表结构

当前共七张表：`model_configs`、`app_settings`、`courses`、`chapters`、`knowledge_points`，以及 P1.3 的 `learning_sessions`、`chat_messages`。
字段以 `apps/api/app/db/models.py` 为准。P1.5 完成后 schema 版本为 **6**；P1.4 为 5，P1.3 为 4。升级只做加表/加列，不删除用户课程、对话与学习记录。升级前建议备份 `data/mastery_lab.db`。

### 1.1 `model_configs` — 模型接入配置

| 字段 | 类型 | 约束 | 说明 |
| --- | --- | --- | --- |
| `id` | INTEGER | PK, 自增 | |
| `name` | VARCHAR(80) | NOT NULL, UNIQUE, INDEX | 配置名称，界面里用来识别；重名返回 409 |
| `base_url` | VARCHAR(500) | NOT NULL | OpenAI 兼容地址，保存前去掉尾部 `/` |
| `model_name` | VARCHAR(160) | NOT NULL | 传给 `/chat/completions` 的 `model` |
| `api_key_cipher` | TEXT | NOT NULL | 密文，带方案前缀：`dpapi:v1:...` 或 `fernet:v1:...` |
| `api_key_hint` | VARCHAR(16) | NOT NULL, 默认 `''` | 新写入固定 `****`；历史行可能保留旧尾码，接口统一覆盖为固定掩码 |
| `api_key_scheme` | VARCHAR(32) | NOT NULL, 默认 `''` | `windows-dpapi` / `fernet-local-key`，便于排查 |
| `is_default` | BOOLEAN | NOT NULL, 默认 false | 业务层保证「最多一条为 true」 |
| `last_test_at` | DATETIME | NULL | 最近一次连接测试时间（UTC） |
| `last_test_ok` | BOOLEAN | NULL | 已保存参数的探测结果；换地址、模型名或密钥后清空，不记录不同参数的草稿结果 |
| `last_test_message` | VARCHAR(300) | NOT NULL, 默认 `''` | 最近一次测试的可读结论 |
| `created_at` | DATETIME | NOT NULL | UTC |
| `updated_at` | DATETIME | NOT NULL | UTC，更新时自动刷新 |

建表 DDL（SQLAlchemy 生成的实际语句）：

```sql
CREATE TABLE model_configs (
    id INTEGER NOT NULL,
    name VARCHAR(80) NOT NULL,
    base_url VARCHAR(500) NOT NULL,
    model_name VARCHAR(160) NOT NULL,
    api_key_cipher TEXT NOT NULL,
    api_key_hint VARCHAR(16) NOT NULL,
    api_key_scheme VARCHAR(32) NOT NULL,
    is_default BOOLEAN NOT NULL,
    last_test_at DATETIME,
    last_test_ok BOOLEAN,
    last_test_message VARCHAR(300) NOT NULL,
    created_at DATETIME NOT NULL,
    updated_at DATETIME NOT NULL,
    PRIMARY KEY (id)
);
CREATE UNIQUE INDEX ix_model_configs_name ON model_configs (name);
```

### 1.2 `app_settings` — 运行时元信息

| 字段 | 类型 | 约束 | 说明 |
| --- | --- | --- | --- |
| `key` | VARCHAR(64) | PK | 目前只写入 `schema_version` |
| `value` | TEXT | NOT NULL | 当前为 `1` |
| `updated_at` | DATETIME | NOT NULL | UTC |

用途：给后续迁移判断基线版本，以及存放不需要建表的零散开关。


### 1.3 `courses` — 课程（P1.1）

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `id` | INTEGER PK | |
| `title` | VARCHAR(200) | 课程名（默认取教材首个 H1 / PDF 标题） |
| `description` | TEXT | 课程简介（默认取首段正文） |
| `source_type` | VARCHAR(16) | `markdown` / `pdf` |
| `source_name` | VARCHAR(255) | 原始文件名（仅展示） |
| `source_file` | VARCHAR(400) | 相对 `data/` 的路径，如 `courses/ab12cd34ef56/xxx.md` |
| `source_sha256` | VARCHAR(64) | 原文哈希，可用于去重与排查 |
| `source_bytes` | INTEGER | 文件大小 |
| `status` | VARCHAR(16) | `draft`（导入预览中）/ `active`（正式课程），带索引 |
| `parse_meta` | TEXT | JSON：`{warnings:[...], stats:{chapters,knowledgePoints,codeBlocks,characters,pages}}` |
| `icon` | VARCHAR(16) | P1.2 新增：单字符图标（用户可选），空串表示按来源类型显示 MD/PDF 徽标 |
| `last_studied_at` | DATETIME | P1.2 新增：最近一次学习时间（UTC，naive 存库），没学过为 NULL |
| `created_at` / `updated_at` | DATETIME | UTC |

### 1.4 `chapters` — 章节

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `id` | INTEGER PK | |
| `course_id` | INTEGER FK → `courses.id` ON DELETE CASCADE，索引 | |
| `title` | VARCHAR(200) | 章节名 |
| `description` | TEXT | 章节首段摘要 |
| `sort_order` | INTEGER | 从 0 递增，重排时整体重写 |
| `code_count` | INTEGER | 本章代码块数（含章节级、未归属知识点的代码块） |

### 1.5 `knowledge_points` — 知识点

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `id` | INTEGER PK | |
| `chapter_id` | INTEGER FK → `chapters.id` ON DELETE CASCADE，索引 | |
| `title` | VARCHAR(200) | 知识点名（来自 H3–H6 或 PDF 子标题） |
| `description` | TEXT | 首段摘要，用于列表展示 |
| `content` | TEXT | 该小节的正文（保留 Markdown 与代码围栏及语言标识） |
| `sort_order` | INTEGER | 章节内顺序 |
| `code_count` | INTEGER | 该知识点的代码块数 |
| `mastery_level` | INTEGER | 0–5，P1.2 **不写**该字段（掌握度留到后续阶段） |
| `learning_status` | VARCHAR(16) | P1.2 四态：`not_started` / `in_progress` / `review` / `completed`，创建时统一为 `not_started` |
| `last_studied_at` | DATETIME | P1.2 新增：该知识点最近一次状态变更时间（UTC，naive 存库） |

关系与删除：

- `Course.chapters`、`Chapter.knowledge_points` 都是 `cascade="all, delete-orphan"`，
  删除课程会连带删除章节与知识点；同时服务层删除 `data/courses/<dir>/` 下的教材文件。
- 外键声明了 `ON DELETE CASCADE`，即使有人直接用 SQL 删课程行也不会留下孤儿数据（连接时已开 `PRAGMA foreign_keys=ON`）。
- 草稿（`status='draft'`）与正式课程共用这三张表：草稿不进课程中心列表，用户取消导入时整条草稿被删除。

### 1.6 学习状态与进度（P1.2）

`knowledge_points.learning_status` 只有四个合法值，进度由状态分布推导，**不额外建进度表**：

| 值 | 含义 | 进度权重 |
| --- | --- | --- |
| `not_started` | 未学习 | 0 |
| `in_progress` | 学习中 | 0.4 |
| `review` | 待复习 | 0.7 |
| `completed` | 已完成 | 1 |

课程与章节进度都用这一个公式（实现在 `apps/api/app/services/learning.py`）：

```
进度 = round(Σ 状态权重 / 知识点总数 × 100)      # 总数为 0 时进度为 0
```

- 章节进度只在章节内的知识点上计算，章节行不落库、每次按需求值。
- 状态变更会同时写 `knowledge_points.last_studied_at` 与 `courses.last_studied_at`，
  课程中心的「最近学习」排序和课程详情的「最近学习」列表都基于这两个字段。
- 时间在库里以 naive UTC 保存，接口输出时统一补 `Z`（`course_service._utc`），
  避免前端按本地时区解析时凭空偏移。

## 2. 业务不变量

| 规则 | 实现位置 | 说明 |
| --- | --- | --- |
| 名称唯一 | `services/model_registry._ensure_name_available` | 数据库唯一索引兜底 |
| 默认唯一 | `create_config` / `update_config` → `_clear_other_defaults` | 设为默认时把其他行的 `is_default` 置 false |
| 首条自动默认 | `create_config` | 空表时插入的记录 `is_default=true`，避免「有配置但没有默认」 |
| 删除默认后补位 | `delete_config` | 删除的是默认配置时，把剩余第一条设为默认 |
| 换 Key 清空测试结论 | `update_config` | 旧结论对新密钥无意义 |
| 明文永不入库 | `core/security.encrypt_secret` | 只在内存里短暂存在 |
| 状态值合法 | `services/learning.normalize_status` | 只接受四态与两个历史别名，其他值 422 |
| 进度公式唯一 | `services/learning.progress_from_counts` | 课程 / 章节 / 测试脚本都引用同一份权重 |
| 归属校验 | `course_service._get_chapter` / `_get_point` | 带 `courseId` 的接口校验章节/知识点属于该课程，否则 404 |
| 排序全量校验 | `reorder_chapters` / `reorder_points` | 必须提交该课程/章节全部 ID 的一个排列，缺项或重复都 422 |
| 删除不留孤儿 | ORM 级联 + `ON DELETE CASCADE` | 删课程/章节会连带删除子行与学习状态 |

上述规则在服务层用事务实现；SQLite 单写者仍可能产生竞争，不能视为没有并发问题。P1.3 用会话唯一约束与进程内生成锁减少冲突，只支持单 worker。

## 3. 密钥密文格式

| 前缀 | 含义 | 解不开的典型原因 |
| --- | --- | --- |
| `dpapi:v1:` | base64 的 Windows DPAPI 密文（用户作用域） | 换机器、换 Windows 用户、系统重装 |
| `fernet:v1:` | Fernet token，主密钥在 `data/secrets/master.key` | 主密钥文件丢失或被替换 |

`decrypt_secret` 遇到解不开的情况会抛出 `SecretError`，服务层转成 422 + 提示「请重新填写该配置的 API Key」。

## 4. 数据目录

```
data/
├── mastery_lab.db          # 主库（WAL 模式，会伴随 -wal / -shm 文件）
├── secrets/                # Fernet 主密钥回退方案用（DPAPI 生效时不会生成）
├── uploads/                # P1 教材上传目录（当前为空，含 .gitkeep）
└── run/                    # 运行期文件：api.pid / web.pid / *.log / api-deps.hash
```

`data/` 下除 `uploads/.gitkeep` 外全部被 `.gitignore` 忽略。

## 5. 变更策略（重要）

- **v1 → v2（P1.1）**：只新增表（`courses` / `chapters` / `knowledge_points`），P0 的 `model_configs`、`app_settings`
  一字未改。已有数据库启动时 `create_all()` 会补建缺失表，无需手工迁移。
- **v2 → v3（P1.2）**：只做两件兼容性调整，**没有删表、没有删列、没有重建**：
  1. 新增列：`courses.icon`、`courses.last_studied_at`、`knowledge_points.last_studied_at`。
     `create_all()` 不会给已存在的表补列，因此启动时 `db/__init__._ensure_columns()` 会用
     `PRAGMA table_info` 判断并按需 `ALTER TABLE ... ADD COLUMN`（幂等，老数据原样保留）。
  2. 状态归一：`_migrate_learning_status()` 把 `learning` → `in_progress`、`mastered` → `completed`，
     一个人工确认过的映射（P1.1 只有三种状态，语义一一对应），同样幂等。

  实测：本机旧库（3 门课程 / 9 章 / 16 个知识点）升级后行数与内容不变，日志输出三行「增量迁移：表新增列」。
- **v3 → v4（P1.3）**：只新增 `learning_sessions` / `chat_messages` 两表，由 `create_all()` 幂等补建，旧课程、进度和模型配置不重建。
- 现阶段不允许静默修改已有列或删库；未来字段类型/名称变化必须先设计备份和可回滚迁移。
- 引入 Alembic 的时机：下一次需要修改已有列，或需要保留真实学习进度做结构升级时。届时把 v3 结构作为
  baseline revision，并在 `scripts/start-api.ps1` 里执行 `alembic upgrade head`。

## 6. 备份与检查

```powershell
# 查看表与数据（不启动应用也可以）
cd "E:\前端转AI_Agent全栈\Mastery Lab\apps\api"
.venv\Scripts\python.exe -c "import sqlite3;c=sqlite3.connect(r'..\..\data\mastery_lab.db');print(c.execute('select name from sqlite_master where type=\"table\"').fetchall());print(c.execute('select id,name,model_name,is_default,api_key_hint from model_configs').fetchall())"

# 看课程 / 章节 / 状态分布（P1.2）
.venv\Scripts\python.exe -c "import sqlite3;c=sqlite3.connect(r'..\..\data\mastery_lab.db');print(c.execute('select id,title,status,icon,last_studied_at from courses').fetchall());print(c.execute('select learning_status,count(*) from knowledge_points group by 1').fetchall())"

# 检查是否残留孤儿行（两个查询都应返回 0）
.venv\Scripts\python.exe -c "import sqlite3;c=sqlite3.connect(r'..\..\data\mastery_lab.db');print(c.execute('select count(*) from chapters where course_id not in (select id from courses)').fetchone());print(c.execute('select count(*) from knowledge_points where chapter_id not in (select id from chapters)').fetchone())"

# 备份（应用停止后复制即可，WAL 模式下建议同时复制 -wal）
Copy-Item data\mastery_lab.db data\mastery_lab.backup.db
```

注意：DPAPI 密文只能在同一台机器、同一 Windows 用户下解开，因此「换机器恢复」时旧配置必须重新填写 API Key。

## 7. P1.3 会话表

### `learning_sessions`

| 字段 | 类型/约束 | 用途 |
| --- | --- | --- |
| id | INTEGER PK | 会话 ID |
| course_id | FK courses.id，CASCADE，索引 | 所属课程 |
| knowledge_point_id | FK knowledge_points.id，CASCADE，索引 | 所属知识点 |
| model_config_id | 可空 FK model_configs.id，SET NULL | 上次选择模型 |
| last_message_at | 可空 DATETIME | 最近消息时间 |
| created_at / updated_at | DATETIME | UTC，会话读出时补时区 |

`UNIQUE(course_id, knowledge_point_id)` 保证恢复同一会话；服务同时校验知识点所属章节属于该课程。不存在云端 user_id，本地用户以数据目录为边界。

### `chat_messages`

| 字段 | 类型/约束 | 用途 |
| --- | --- | --- |
| id | INTEGER PK | 消息顺序，重生成最后回答可能复用 SQLite ID |
| session_id | FK learning_sessions.id，CASCADE，索引 | 所属会话 |
| role | VARCHAR(16) | user / assistant |
| content | TEXT | 正文或已收到的部分正文 |
| status | VARCHAR(16) | streaming / completed / interrupted / failed |
| model_name | VARCHAR(160) | 生成时模型名 |
| error_message | VARCHAR(500) | 安全错误提示 |
| created_at | DATETIME | UTC |

system 消息、密钥及原始上游错误不写入聊天表。按 ID 顺序恢复。停止保留正文；重生成替换最后助手消息（无版本历史），最后一条为用户时直接补答。进程中断遗留 streaming 在无活动任务时读为 interrupted，下次生成开始前将旧状态归一为 interrupted；不改用户历史正文。删除课程/知识点会级联清除相关会话和消息。

## 8. P1.5 学习档案结构（schema 6）

P1.5 新增 6 张表，并在 `knowledge_points` 增加 `mastery_state`、`mastery_updated_at`。
完整字段、口径与 API 见 `docs/LEARNING_RECORDS.md`；本节只列结构变化。

### 8.1 `knowledge_points` 增量列

| 列 | 类型 | 说明 |
| --- | --- | --- |
| `mastery_state` | VARCHAR(24) NOT NULL DEFAULT 'NOT_STARTED' | 6 态掌握状态，只由教学证据更新 |
| `mastery_updated_at` | DATETIME NULL | 最近一次状态变化时间 |

迁移时 `_backfill_mastery()` 幂等回填：复制已有 `teaching_progress.mastery_state`；由 VERIFY 完成的补为
`INDEPENDENT`；历史手工完成（`legacy_manual`）不推断为已掌握。回填同时写入一条来源为「迁移」的
`mastery_history`（仅在该知识点没有历史时）。

### 8.2 新表

| 表 | 主键/唯一约束 | 主要列 | 删除策略 |
| --- | --- | --- | --- |
| `learning_activities` | `id`；`session_id` 部分唯一（仅 `status='active'`） | 课程、知识点、会话、状态、`started_at`、`last_heartbeat_at`、`ended_at`、`active_seconds`、阶段与尝试快照 | 课程/知识点/会话删除时级联 |
| `learning_breakpoints` | `session_id` | 当前阶段/状态、`revision`、`paused`、`draft_answer`、当前问题、计数、最后消息、`client_seq` | 会话删除时级联 |
| `mastery_history` | `id` | `from_state`、`to_state`、`reason`、`evidence`、会话、活动 | 课程/知识点级联；活动置空 |
| `mistake_records` | `id`；`dedupe_key` 索引 | 原始问题、用户回答、参考答案、错误原因、纠正讲解、偏差、`status`、`occurrence_count` | 课程/知识点级联 |
| `mistake_occurrences` | `id` | `mistake_id`、活动、会话、阶段、评价、当次问答与反馈 | 错题级联 |
| `learning_events` | `id` | 活动、课程、知识点、会话、事件类型、详情 | 课程/知识点级联；活动置空 |

### 8.3 时间字段

所有时间按 UTC 存储，接口输出 UTC 带时区；前端按浏览器本地时区展示。
有效学习时长只取 `learning_activities.active_seconds`，与 `started_at`/`ended_at` 的墙钟差无关。

### 8.4 已有数据兼容

- 不新增对旧表的必填字段；`chat_messages`、`teaching_*`、`learning_sessions` 保持原结构；
- P1.4 的 `teaching_progress` 仍是教学阶段与评价的事实来源，P1.5 不复制一套教学状态；
- 删除课程会同时删除该课程的活动与错题；若用户需要保留历史，应在删除前导出数据库备份。
