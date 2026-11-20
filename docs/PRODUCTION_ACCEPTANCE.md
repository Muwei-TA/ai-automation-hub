# AI Automation Hub 生产验收门槛（当前不合格）

本项目采取 fail-closed 验收：所有带 [ ] 的项目都需要真实环境证据，缺一项不能标记为 Production Ready。

## 一、构建与静态检查

- [x] 全量 Python 代码可编译；Pytest 测试通过；整体覆盖率 >=90%（在 AIO Sandbox 验证）。
- [x] 配置预检查对默认凭据占位符拒绝启动建议；不输出密钥。
- [x] Gitea Webhook HMAC-SHA256 校验、无效签名拒绝、请求体上限、Push 白名单已通过模拟 HTTP 测试。
- [ ] GitHub Actions Verify（当前生产开发分支对应提交）通过。
- [ ] 在目标 Docker Engine 上执行 docker compose config --quiet。
- [ ] Dockerfile.gateway 与 Dockerfile.worker 成功构建；镜像运行不依赖 root 用户。
- [ ] 锁定镜像摘要/依赖版本并验证依赖安全扫描，记录 SBOM。

## 二、基础服务与网络

- [ ] n8n、专用 PostgreSQL、Gateway、Prefect Worker 实际启动；容器 healthcheck 状态正常。
- [ ] 复用已有 Prefect 3 Server，不更改生产数据库或已有实例配置。
- [ ] 进程健康接口 /healthz 返回 200，Prefect 连通时 /readyz 返回 200，断连时 /readyz 返回 503。
- [ ] NAS/Worker 容器仅通过授权的内网地址访问 Prefect；禁止公网直接暴露 Prefect REST。
- [ ] HTTPS 反向代理具备认证/访问限制、请求速率限制、最大请求体限制、有效证书。

## 三、真实功能验收

- [ ] 在隔离 work pool 中注册全部四个 Deployment，逐个手动提交并验证最终 Flow Run state=Completed。
- [ ] 真实 n8n 导入版本适配、Header Auth 凭据绑定与定时器执行正常。
- [ ] 使用测试仓库真实投递 Gitea Push：有效签名正确进入 Prefect、错误签名拒绝、重复投递不会制造重复任务。
- [ ] ComfyUI 使用专用测试模板、低资源工作流验证排队/状态查询/完成，异常后不造成重复 GPU 任务。
- [ ] NAS 健康检查读到预期磁盘和 HTTP 服务；异常产生正确告警。
- [ ] GitHub API 调用在请求限额内，通知和 LLM 配置不泄漏私有数据。
- [ ] Mac/VPS Worker 在各自主机独立运行、能从正确 work pool 领取任务、版本一致，并在断线后恢复。

## 四、安全和灾难恢复

- [ ] GATEWAY_API_KEY、GITEA_WEBHOOK_SECRET、N8N_ENCRYPTION_KEY、数据库密码均为不同的随机值，通过安全存储管理，并证明可轮换。
- [ ] Gitea 旧版无签名 n8n Webhook 已停用和删除。
- [ ] 默认不挂载 Docker Socket；开启任何特权权限必须单独评审。
- [ ] 记录容器异常退出、Prefect Server 离线、Webhook 重放、GPU 失败场景的故障恢复演练。
- [ ] 对 PostgreSQL + n8n data + 密钥进行加密备份，实际完成一次在隔离环境的恢复演练，记录 RPO/RTO。
- [ ] 验证日志不打印 API Key、Token、Webhook Secret；对健康告警和错误分级。
- [ ] 人工审核生产配置并批准发布；有可执行的回滚命令和上一版镜像。

## 结果口径

当前阶段：**未通过生产验收**。在 AIO Sandbox 已完成 Python 测试、模拟 HTTP 调度以及本地 Prefect Flow 执行，但没有 Docker Engine、真实 n8n/Prefect Work Pool、真实 Gitea/ComfyUI 测试环境的验收证据。

推荐先在独立 NAS VM 或隔离的 Docker 主机上执行第二、三部分；不得直接将本仓库部署到 BlackRoom 正式站或使用正式令牌作压力测试。
