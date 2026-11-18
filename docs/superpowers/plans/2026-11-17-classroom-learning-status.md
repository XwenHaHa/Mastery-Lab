# 教室内学习完成标记 Implementation Plan

> 执行方式：按 executing-plans 与 test-driven-development 顺序在现有工作区实现；不创建仓库、分支或提交。

**Goal:** 用户无需离开教室即可标记当前知识点完成或改回学习中，同时保留对话和当前位置。

**Architecture:** 复用 `courseLibraryApi.setPointStatus` 的课程详情响应作为学习状态与进度的数据来源，聊天会话只负责对话。状态保存独立于生成过程；课程请求序号隔离跨课程的迟到响应，切换知识点后只更新对应目录，不将旧状态套到当前知识点。

**Tech Stack:** Vue 3、TypeScript、Element Plus、既有 FastAPI 接口、Playwright。

## 已确认设计

- 当前知识点标题旁显示状态及「标记为已完成」；完成后提供「改为学习中」。不增加状态管理弹窗。
- 仅手工点击改变状态，AI 回答完成不自动改变状态；不引入掌握度评估或 P1.4。
- 保存成功同步目录、课程进度、已学习数量，不刷新页面、不清空输入与对话、不自动进入下一点。
- 复用独立的上一点/下一点按钮，保存中禁用重复提交；生成中仍可标记。
- 请求失败显示错误，保留原状态，可再次点击重试；切换课程后忽略旧响应。
- 保持现有深色主题与布局，窄屏标题和操作区可换行。

## 文件边界

- 修改 `apps/web/src/views/ClassroomView.vue`：按钮、保存状态、进度来源及窄屏样式。
- 新增 `docs/qa/classroom_status_ui.py`：浏览器测试，拦截并明确模拟课程/会话 API，不使用用户数据或模型额度。
- 更新 `docs/qa/p13_backend_test.py`：临时数据库内验证课程状态与教室会话的持久化契约。
- 更新 `README.md`：说明教室内标记完成与改回学习中的操作。
- 更新 `docs/TEST_REPORT_P1.3.md`：补充本次交互变更及实际验证证据。

## 任务

- [x] 添加浏览器测试：完成/改回、刷新保留、目录/数量/进度同步、请求失败重试、重复提交防护、延迟响应后切知识点/课程、生成结束的旧快照不覆盖状态、窄屏布局。
- [x] 先运行测试并确认因缺少「标记为已完成」按钮而失败。
- [x] 在 `ClassroomView.vue` 复用既有 PATCH，不更改后端 schema/API；让进度读取 `course`，并按当前会话知识点 ID 从目录读取状态。
- [x] 保存函数捕获课程序号和知识点 ID；保存成功只替换当前课程数据，不触碰消息、输入和路由；失败单独反馈。
- [x] 运行浏览器回归 8/8、后端 26/26（新增状态同步测试 1 项）/前端 6/6 及 Vue 类型检查/构建，检查截图与控制台。
- [x] 更新验收说明及真实执行结果。

## 验证命令

```powershell
$env:PYTHONPATH='E:/tmp/playwright-python'
$env:PLAYWRIGHT_BROWSERS_PATH='E:/tmp/ms-playwright'
python docs/qa/classroom_status_ui.py
python docs/qa/p13_validate.py
```

浏览器测试记录保存到 `docs/qa/classroom-status-ui-result.json`，截图保存到 `docs/review/p1-3/status-*.png`。测试网关只存在浏览器路由拦截层；生产接口和用户数据库不发生写入。
