# Issue #191：Remote MCP 测试与修复记录

日期：2026-10-09。基线：`b45409c`，openinvest 0.39.0。
对应 [issue #191](https://github.com/longsizhuo/openInvest/issues/191) 及维护者要求的
[第二台机器实测](https://github.com/longsizhuo/openInvest/issues/191#issuecomment-6066387480)。

## 环境与范围

- 客户端：macOS，Python 3.14.7，官方 MCP Python SDK `ClientSession` + `streamable_http_client`，mcp 1.28.1。
- 服务端：另一台物理电脑 M1 Pro，macOS，Python 3.13.2；通过已有 Tailscale 网络连接。
- 反向代理：M1 Pro 上 nginx 1.29.0，向后端设置测试域名 Host，关闭响应缓冲，`proxy_read_timeout 20s`。
- 后端：Uvicorn 0.38.0、mcp 1.28.1、sse-starlette 3.4.5，loopback 绑定；Bearer token + 显式 Host 白名单。
- 数据：独立临时 `INVEST_HOME`，虚拟 CNY 20,000 现金、空持仓；不使用真实投资账本。
- 基础远端测试直接启动修复后的 `openinvest-mcp --http`；`status` / `strategy` 走真实业务服务，行情依赖未 mock。
- 长耗时测试只替换委员会 service 为受控的 130 秒模拟任务，验证传输、心跳、进度与并发；这不是一次真实 LLM 委员会分析。
- **未经过 Cloudflare / Access，不是公网 HTTPS 测试，也未验证断线中的任务恢复。**
- 本机另用 nginx 1.31.6 做旧 JSON 模式与修复后 SSE 模式的对照。

## 实测结果

| 场景 | 结果 |
|---|---|
| 第二台机器上的服务：initialize + tools/list | 通过，21 个工具，与 stdio 契约一致 |
| 真实远端 `status` | 通过，首次 19.07 秒，虚拟现金余额正确 |
| 真实远端 `strategy` | 通过，首次 0.22 秒 |
| 两个独立远端客户端并发 | 均通过；status 分别 0.17 / 1.11 秒 |
| 退出后重新 initialize，再调用工具 | 通过；stateless，无 session ID |
| 无 Bearer 请求 / 无鉴权 health | 分别为 401 / 200 |
| 本机 nginx：旧 JSON 模式、25 秒模拟委员会 | 在约 20.00 秒收到 504（代理 read timeout 20 秒） |
| 本机 nginx：SSE、130 秒模拟委员会 | 130.01 秒成功；首个进度立即到达，期间另一客户端 status 成功 |
| M1 Pro nginx：130 秒模拟委员会 | **130.40 秒成功**；首个进度 0.17 秒到达；期间第二客户端 status 1.92 秒、strategy 0.44 秒成功 |
| Claude Code 2.1.281 | 未验收：本机未登录；工具调用尝试 90 秒未完成，`claude auth status` 返回 loggedIn=false |

基础跨机器测试与长耗时测试使用不同后端进程，后者的模拟范围如上。
成功完成一个长调用不能证明所有代理均不会断连，也不代表 stateless 支持恢复执行。
验收后已停止本次创建的 M1 Pro MCP/nginx 进程并移除临时 token 文件；
源码、依赖和虚拟测试数据仍保留在独立临时目录，方便后续继续测试。

## 复现并修复的问题

1. **一个同步工具会阻塞所有客户端。** FastMCP 1.28.1 直接在事件循环执行同步函数。
   当 status 等待行情时，第二个客户端 tools/list 和 health 也无法响应。
   工具注册现在保留原函数签名、schema、annotations 和直接 Python 调用方式，
   将同步业务函数交给 AnyIO worker；写入继续使用原服务层事务锁。
2. **HTTP 委员会进度丢失、长调用静默直到结束。** JSON 响应等待最终结果；
   此外该 SDK 的 `Context.report_progress` 没有关联请求 ID，通知会被路由到独立 GET 流，
   stateless POST 客户端收不到。改用请求内 SSE，并显式传递 `related_request_id`。
   SDK 心跳可以在阶段回调之间保持流量；客户端总调用超时仍需单独配置。
3. **重新配置无 token 模式时会继承旧的 Host 防护状态。**
   `_configure_http_settings` 缺少无 token/无显式白名单分支，先配置 token 模式再取消时，
   陌生 Host 仍返回 200。现在显式恢复 loopback 白名单；回归预期为 421。
4. **原有锁测试在 macOS spawn 模式失败。** 子进程目标是不可 pickle 的局部 lambda。
   换成可 pickle 的 `os.getpid`，保留“真实子进程退出后回收死 PID 锁”的测试语义。

部署文档同步补充 SSE 反代配置、Access-only 模式必须显式配置 Host 白名单、
客户端总超时与非幂等写操作不能盲目重试的限制。

## 自动化验证

```bash
uv sync --frozen
uv run pytest tests/test_mcp_http.py tests/test_mcp_http_integration.py tests/test_mcp_server.py -q
DEEPSEEK_API_KEY=test-fake-key INVEST_LLM_BASE_DELAY=0.01 uv run pytest tests/ -q
uv run lint-imports --no-cache
uv build
```

- 修复前原有 MCP 测试：24 passed。
- 新增真实 TCP 测试在修复前复现慢查询阻塞、进度缺失；Host 重新配置回归同样失败。
- 修复后完整测试：**1334 passed**（72.36 秒）；3 项 import-linter 契约通过；sdist/wheel 构建通过。
- TCP 测试使用真实 loopback socket，不是 ASGITransport；业务依赖用受控替身，CI 不调用 LLM。
- 新增两客户端同时向临时账本执行 10 次独立入金，最终余额严格增加 10，验证线程化后无丢失更新。

## 尚待验证

- 真实域名 + HTTPS + Cloudflare Access Service Token 与应用 Bearer 的组合。
- 已登录的 Claude Code / Cursor 等交互式 agent 客户端实际调用。
- 有效 LLM 配置下的一次真实委员会缓存未命中，以及该调用经过 Cloudflare 时的行为。
- Docker Compose、systemd 模板及默认端口 8766 的全新 Linux 部署。

这些缺项不应标记为已通过；本记录不足以移除 Remote MCP 的 BETA 标签。
