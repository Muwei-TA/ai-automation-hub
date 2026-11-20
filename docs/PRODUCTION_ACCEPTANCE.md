# AI Automation Hub 生产验收门槛（当前不合格）

本项目采取 fail-closed 验收：所有带 [ ] 的项目都需要真实环境证据，缺一项不能标记为 Production Ready。

## 一、构建与静态检查

- [x] 全量 Python 代码可编译；Pytest 测试通过；整体覆盖率 >=90%（在 AIO Sandbox 验证）。
- [x] 配置预检查对默认凭据占位符拒绝启动建议；不输出密钥。
- [x] Gitea Webhook HMAC-SHA256 校验、无效签名拒绝、请求体上限、Push 白名单已通过模拟 HTTP 测试。
- [x] GitHub Actions Verify #7（提交 a7d0ebe）共四项任务通过：Python、Docker 镜像冒烟、Prefect 容器 E2E、n8n/PostgreSQL 备份恢复。
- [x] GitHub-hosted Docker Runner 已执行 docker compose config --quiet。
- [ ] 在目标 NAS Docker Engine 上执行 docker compose config --quiet，并进行端口/卷/网络冲突检查。
- [x] CI 上 Dockerfile.gateway 与 Dockerfile.worker 成功构建，容器默认用户为 uid 10001。
- [ ] 在目标 NAS 构建或拉取经签名/摘要锁定的同一版本镜像，并完成部署验证。
- [ ] 锁定镜像摘要/依赖版本并验证依赖安全扫描，记录 SBOM。

## 二、基础服务与网络

- [x] 隔离 CI 环境已分别启动 Gateway/Worker/Prefect 以及 n8n/PostgreSQL，并通过服务健康与 E2E 检查。

- [ ] n8n、专用 PostgreSQL、Gateway、Prefect Worker 实际启动；容器 healthcheck 状态正常。
- [ ] 复用已有 Prefect 3 Server，不更改生产数据库或已有实例配置。
- [x] CI 容器验证 /healthz=200、Prefect 可用时 /readyz=200、不可用时 /readyz=503。
- [ ] NAS 目标环境复测上述健康状态，并验证反向代理和自动重启。
- [ ] NAS/Worker 容器仅通过授权的内网地址访问 Prefect；禁止公网直接暴露 Prefect REST。
- [ ] HTTPS 反向代理具备认证/访问限制、请求速率限制、最大请求体限制、有效证书。

## 三、真实功能验收

- [x] AIO Sandbox 内独立 Prefect 3.9 Server + Process Worker 已验证 nas-health Flow Run 最终 Completed；通过明确 Process Worker working_dir 修复了临时目录找不到源码造成的 Crashed。
- [ ] 在目标 NAS 的隔离 work pool 中注册全部四个 Deployment，逐个手动提交并验证最终 Flow Run state=Completed。
- [x] CI 容器验证 n8n 启动及示例工作流 CLI 导入/导出成功。
- [ ] 目标 n8n 实例在 UI 中绑定 Header Auth 凭据，并实测手动执行、定时器和异常重试。
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
- [x] CI 已对临时 n8n PostgreSQL 执行 pg_dump，并在新建数据库中恢复和检查表结构数。
- [ ] 对生产 PostgreSQL + n8n-data + 加密密钥执行独立加密备份及完整恢复演练，并记录 RPO/RTO。
- [ ] 验证日志不打印 API Key、Token、Webhook Secret；对健康告警和错误分级。
- [ ] 人工审核生产配置并批准发布；有可执行的回滚命令和上一版镜像。

## 结果口径

当前阶段：**CI 级隔离验收通过，真实生产验收未通过**。GitHub Actions Verify #7（https://github.com/Muwei-TA/ai-automation-hub/actions/runs/44691738037）四项任务均成功：39 项 Python 测试和 93.71% 代码覆盖率、镜像构建与非 root 检查、独立 Prefect Docker E2E 真正完成 Flow Run，以及 n8n 工作流导入导出与 PostgreSQL 逻辑恢复。

AIO Sandbox 单独完成的 Prefect Server/Worker 任务也达到了 Completed，但诊断时发现沙箱时区与 Prefect 预取截止时间存在不一致，因此使用过扩大预取窗口来定位工作目录问题；该设置不应直接作为生产默认配置。

尚未获得 NAS 真实环境网络/容器/密钥状态、Mac/VPS Worker、Gitea 事件签名实际投递、ComfyUI GPU 任务、生产备份恢复、监控告警和人工批准的证据。**不能因为 CI 全绿就合并发布到生产。**

推荐先在独立 NAS VM 或隔离的 Docker 主机上执行第二、三部分；不得直接将本仓库部署到 BlackRoom 正式站或使用正式令牌作压力测试。

