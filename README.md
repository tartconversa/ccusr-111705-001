# 直播间 AI 会员权益的可证明采集

这是会员卡资料的本地演练门户与目录采集器。演练数据仅在环回地址提供，不会操作真实用户、订单或商户。当前 `app.capture.read_catalog` 读取目录；`app.capture.read_plan_page` 走卡片到详情并接收可选业务选择，`app.domain.interpret_entry` 确认业务身份，`app.records.save_detail_entries` 追加详情入口收据。

`app.capture.observe_plan` 在授权的本地详情页为每个规格独立走完「选择规格 → 打开权益 → 结算预览」：以页面 offer 版本号为轮次锚点防止跨轮拼接，等待弹层异步终态、超时如实标记未确认，识别活动失效与价格漂移，逐阶段保存截图与 HTML 证据，且只放行环回只读请求、不点击任何提交控件。`records.save_observations` 只追加观察收据，`review.review_observations` 给出逐轮逐阶段的核对视图。边界与状态约定见 `docs/portal.md`。

站点约定见 `docs/portal.md`；测试时从本地任意空闲端口启动演练站点。安装锁定依赖并准备 Chromium 后：

- `python -m unittest discover -s tests -v`：运行基线浏览器测试。
- `python -m compileall -q app tests`：检查代码。
- `python -m app.site`：启动本地演练站点。
- `python -m app.cli`：另一个终端观察目录输出。
- `python -m app.cli observe ai-basic --simulate-expiry --evidence-dir ./evidence --db ./obs.sqlite3`：对一张卡走完整观察流程，落证据与收据。

两个终端命令用于人工演示，自动测试不依赖固定端口。
