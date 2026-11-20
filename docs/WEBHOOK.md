# Gitea Webhook 签名接入

必须在网关上配置独立 GITEA_WEBHOOK_SECRET（至少 32 字符随机值），并在 Gitea 仓库 Webhook 设置中填写相同的 Secret，不要与 GATEWAY_API_KEY 复用。

- 目标 URL：https://<trusted-gateway-host>/v1/webhooks/gitea
- 内容类型：application/json
- 事件：Push
- 签名：X-Gitea-Signature，原始请求体 HMAC-SHA256 十六进制摘要
- 服务端最大请求体：256 KiB
- 仅接受合法 owner、repo、sha，固定执行白名单任务 gitea-status。
- 对同一仓库与提交生成稳定的 SHA-256 Prefect idempotency_key。最终幂等性依赖真实 Prefect Server 实现。

默认 Gateway 仅绑定 127.0.0.1。外部 Gitea 要经由可信 HTTPS 反向代理连接，需在反代层增加访问控制、限速和 body 限制。/healthz 表示进程存活；/readyz 检查 Prefect API 可访问。

升级时务必停止并删除之前导入的 n8n/workflows/gitea-status-webhook.json，它无签名验证，已从仓库移除。新 Gitea Push 事件直接通过签名 Gateway 进入 Prefect；n8n 仍负责定时和其他可信触发。

当前仅完成隔离测试，真实 Gitea、反向代理、Prefect Server/Worker 的连通性仍需生产环境验收。
