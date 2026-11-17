# 本地来源行为

会员卡目录列出稳定的 `data-key` 和详情路径；详情需由浏览器导航读取，`规格`选择改变当前页面状态，`权益`和`结算预览`是分步出现的可见内容。切换规格后权益弹层仍可能显示旧版本。详情接口是浏览器页面，不是业务 API；运行时只允许访问环回来源。

`fixtures/portal.json` 提供合成业务资料，不包含真实个人数据。`records.save_catalog` 覆盖同一目录身份；`records.save_detail_entries` 以业务键追加入口访问，不把入口访问等同于资格、授权、可预约或正式提交。测试均只访问本地环回页面。

## 完整观察流程（`capture.observe_plan`）

在授权的本地详情页为每个规格独立走一轮「选择规格 → 打开权益 → 结算预览」，把同一轮所见的价格与权益条件连同页面证据交给运营核对：

- **轮次锚点**：详情页 `#offer-revision` 的 `data-revision` 在每次规格切换或活动失效时递增。每轮记录业务键 `卡片:规格:v版本`，权益与结算文本必须带当前规格前缀并属于当前版本，否则判为未确认——不把前后两轮拼成一份报价。同值重复选择不会制造空转新版本。
- **异步弹层**：`#rights-revision`、`#checkout-revision` 先显示「读取中」再落终态。采集器只读等待终态，超时如实记为 `unconfirmed`（如 `checkout_panel_pending`），重试只是再次只读等待，不重复任何写操作。
- **活动失效**：`#offer-revision` 出现 `data-expired="true"` 后，权益区仍可能渲染带新版本号的权益文本；有效性一律以 offer 状态为准，失效轮的三阶段都标 `offer_expired`，不产生完整报价。`observe_plan(..., simulate_expiry=True)` 用页面自带控件追加一轮失效观察。
- **价格漂移**：结算预览价与该规格 `#summary` 价格不一致时标 `checkout_price_drift`，两份价格原文都保留，不合并成一个数字。
- **无真实订单**：浏览器路由只放行环回来源的 GET/HEAD，其余请求（外发域名、POST 等）在浏览器内即被拦截；页面若存在任何提交控件（form、submit 按钮）采集器直接拒绝运行；点击白名单仅 `#tier`、`#rights`、`#preview`、`#expire`。
- **证据**：每阶段一张全页截图，每轮一份 HTML 快照，结构化记录里同时保存定位器原文（`#rights-revision` / `#checkout-revision` 与次级输出 `#rights-text` / `#result`）。
- **收据**：`records.save_observations` 只追加 `plan_observations` 表，每个规格轮次一行；`review.review_observations` 输出逐轮、逐阶段的中文核对视图，列出每一步状态与未确认原因。

观察状态三态：`observed`（已确认）、`offer_expired`（活动失效）、`unconfirmed`（未能确认，附原因码）。只有三阶段全部 `observed` 的轮次才标 `complete=true`。
