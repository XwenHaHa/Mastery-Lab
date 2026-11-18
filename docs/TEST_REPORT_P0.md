# Mastery Lab P0 复核交付 · 2026-11-18

**结论：10 项验收中 9 项实测通过；第 8 项（外部提供商成功响应）本轮未验证。** 默认配置是非本机 HTTP 地址。真实探测在解密和发请求前跳过，不把本地模拟或历史的外部响应算成本次成功。

## 已运行的版本

Windows，Node v22.18.0、pnpm 10.34.5、npm 10.9.3、Python 3.13.1、Git 2.42.0；本目录未初始化 Git。本次基于已有源码工作，没有另起一份工程，也没有新增 P1 教学或 P2 运行器功能。

| 目录 | 实际内容 |
| --- | --- |
| `apps/web/` | Vue 3 / TypeScript / Vite，Element Plus、Pinia、Router，侧栏、顶栏、概览、模型配置、设置 |
| `apps/api/app/` | FastAPI 路由、Pydantic 契约、模型服务、SQLAlchemy/SQLite、凭据处理 |
| `data/` | 日常数据；本次工作实例独立使用 `data/qa-p0-20261118/` |
| `scripts/` | Windows 环境检查、启停、进程启动辅助脚本 |
| `runtime/runner/` | 占位，不执行用户代码 |
| `docs/` | 产品、架构、数据库、开发计划；`qa/p0*` 为本次证据及复测脚本 |

## 验收和证据

| 原验收项 | 结果 | 可复核证据（相对 `docs/`） |
| --- | --- | --- |
| 1–2 前后端启动 | 通过；隔离 API 18080、Web 15173 | `qa/p0-final-start.log` |
| 3–4 首页与 API 通信 | 1440×900 Chromium 渲染首页，默认深色；前端代理命中隔离库；首页、health、Swagger HTTP 200 | `qa/p0-dashboard.png`、`qa/p0-browser-result.json`、`qa/p0-final-runtime.json` |
| 5 SQLite 建库、读写 | 从无库启动；查到 DPAPI 密文，删除后对应行不存在；quick_check=ok | `qa/p0_browser.py`、`qa/p0-browser-result.json` |
| 6–7 配置页面与保存 | 页面新建、刷新恢复、编辑留空保留 Key、删除；草稿和已保存配置各收到一次本地网关回复。检查了浏览器存储和服务日志，未发现测试 Key | `qa/p0-browser-result.json` |
| 8 真实模型成功响应 | **未完成**。当前默认外部地址并非 HTTPS，没有发送密钥。要补验：在模型页输入 HTTPS 地址、模型名和 Key，点「测试连接」，确认有实际文本回复。不要将 Key 发到聊天里 | `qa/p0-real-result.json` |
| 9 Windows 启停 | 端口冲突退出 1；按 PID 和创建时间停止测试进程树；确认 15173、18080 释放，重启后可访问 | `qa/p0-port-conflict.log`、`qa/p0-stop.log`、`qa/p0-restart.log` |
| 10 操作文档 | 隔离启动、停止及访问方式与实机一致，见 README 第 2 节 | `qa/p0-final-start.log` |

后端离线回归 8/8：改地址不复用凭据、草稿不污染已保存结论、改模型清空旧结果、固定掩码、非空文本才算成功、默认配置切换/删除、Windows 加密失败拒绝保存。见 `qa/p0-model-green.log`；初始失败见 `qa/p0-model-red.log` 和 `qa/p0-dpapi-red.log`。前端 `npm --prefix apps/web run build` 退出 0（含 vue-tsc）；Vite 提示部分包超过 500 kB，见 `qa/p0-build.log`。复用已有依赖，未测试全新机器首次下载安装。

## 运行与复测

已启动的**验收实例**：首页 `http://127.0.0.1:15173/`、Swagger `http://127.0.0.1:18080/docs`。从项目根目录按 README 第 2 节设置数据目录后启停。重跑离线测试：`apps\api\.venv\Scripts\python.exe docs\qa\p0_model_test.py`；重跑 UI：准备好 Python Playwright 和 Chromium 后执行 `python docs\qa\p0_browser.py`，只对上述隔离实例生效。

## 风险及下一步

- **日常实例未作为本轮交付地址。** 初检日常库为 schema 4，默认端口最初有监听；19:16 北京时间快照中，默认 8000/5173 拒绝连接，日常库为 schema 5、1 个模型，quick_check=ok。本次成功发起的启动及停止均指定隔离数据目录；无法据现有证据确定日常库变化及默认服务停止的来源，未做回滚。quick_check 不是业务数据完整性的证明。对日常库做任何进一步操作前，先保留一致性备份并核对课程/会话。
- Windows 首版以 DPAPI 保护密钥，不应把 SQLite 当作可跨用户恢复的凭据库；远端 HTTP 无传输保密性，应提供 HTTPS 地址。页面的通用 Base URL 入口仍兼容 HTTP 本地网关，本轮探测脚本不会向远端 HTTP 发送凭据。
- P1.1–P1.3 已有实现。建议先在隔离库回归一条「导入教材 → 打开知识点 → 教师首次讲解」链路，再单独验收现有 P1.4 迁移与恢复；不要用本次 P0 结果替代 P1.4 验收。
