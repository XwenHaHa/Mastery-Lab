# Mastery Lab 换机开发交接 · 2026-11-18

## P1.4 状态：可继续开发，不是已验收的版本

`TEACH → DEMO → CHECK → PAIR → VERIFY → NEXT` 已有后端、前端和持久化实现。阶段、证据与回退规则见 `TEACHING_STATE_MACHINE.md`；完成标准以 `plan/P1.4 教学状态机与智能教学流程开发任务.md` 为准。

- 2026-11-18：隔离库的后端测试 23/23；真实 Chromium + 本机模拟模型走完教学、刷新、服务重启，中途没有页面错误，最终 `passed=true`；同轮 P0/P1.1/P1.2 回归 53/53。先前 Windows 清理失败的旧 UI 结果已由本次成功重跑更新。见 `qa/p14-ui-result.json`。
- 2026-11-17：schema 4 快照连续两次启动升级验证通过，原数据摘要一致，见 `qa/p14-migration-result.json`。这是历史迁移证据，不是对另一台电脑数据库的验证。
- **仍缺：** 使用可用的 HTTPS 兼容端点，完成六阶段的真实 AI 教学验收（含错误、部分理解、提示与独立验证分支）。历史真实探测返回 429，不能代替教学记录；本次没有向外部模型发送请求。完成后按任务书整理全部回归、补齐核心文档和最终报告，再标记 P1.4 完成。

## 新 Windows 电脑

准备 Git、Python 3.11+、Node（已测 22.18）及 pnpm（已测 10.34）。首次安装依赖需要网络；已有锁文件在 `apps/web/pnpm-lock.yaml`。从远端克隆仓库，或使用单文件交接包：

```powershell
git clone -b main .\mastery-lab.bundle mastery-lab
cd mastery-lab
git status -sb
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\dev.ps1
```

浏览器访问 `http://127.0.0.1:5173/`，API 文档在 `http://127.0.0.1:8000/docs`。在「模型配置」中重新输入 Key；不要提交 Key。后端会创建新数据库。源码包不含课程、学习记录、原始日志、截图、`.env`、虚拟环境或 `node_modules`。原验收报告中的本机原始附件并非都随仓提供；纯测试样本在 `docs/qa/fixtures/`。

## 复测与持续同步

启动脚本安装依赖后，从根目录运行 `apps\api\.venv\Scripts\python.exe docs\qa\p14_backend_test.py`。浏览器流程需先 `pnpm --dir apps/web run build`，另在运行脚本的 Python 环境安装 Playwright 和 Chromium，再运行 `python docs/qa/p14_ui_flow.py`。这两项均使用临时数据和模拟模型。

bundle 只含生成时的历史，不会自动同步。用 bundle 克隆时，Git 会把文件路径设为 `origin`；有团队远程仓库后，用 `git remote set-url origin <仓库地址>` 改指真实远端。最初创建仓库的电脑若没有 `origin`，用 `git remote add origin <仓库地址>`。首次推送运行 `git push -u origin main`。若远端已有提交，先比较历史，不要强推覆盖。
