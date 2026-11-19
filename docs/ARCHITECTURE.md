# 设计文档

## 明确的职责边界

1. **n8n**：面向人和外部系统的入口。负责 Cron/Webhook、数据过滤、调用 HTTP Gateway；不持有 Prefect 管理凭据。
2. **Gateway**：隔离入口和调度层。拒绝未经授权的请求、只承认 JOB_REGISTRY 中的任务、用 Pydantic 校验任务参数，再读取 Prefect Deployment 并创建 Flow Run。
3. **Prefect 3 Server**：管理运行状态、失败重试、工作池和队列。此仓库不重复部署用户现有 Prefect。
4. **Worker**：在 NAS/Mac/VPS 上运行实际 Python Flow。`prefect.yaml` 默认四个 Flow 使用 NAS 的 process work pool。其他设备作为新 pool，必须在部署中明确选择。
5. **Integrations**：GitHub/Gitea/ComfyUI 和 OpenAI-compatible LLM API。LLM 不直接决定是否拥有 shell、Docker、Gitea 写权限。
6. **数据**：n8n 使用独立 PostgreSQL volume；Prefect 继续维护其现有数据库；Flow 结果记在 Prefect，可通过 Webhook 发简要通知。长历史报告存储、全局计费及队列限流属于未来版本。

## 内部 API

- `GET /healthz`：基础探活，不做深度健康检查。
- `POST /v1/jobs/nas-health`：`{"parameters": {}}`
- `POST /v1/jobs/github-digest`：`{"parameters": {"query":"topic:self-hosted","max_items":10}, "idempotency_key":"daily-2026-11-19"}`
- `POST /v1/jobs/gitea-status`：`{"parameters": {"owner":"org","repo":"demo","sha":"a1b2c3d4"}}`
- `POST /v1/jobs/comfyui-submit`：`{"parameters": {"workflow_name":"sample-txt2img","prompt_text":"a red flower"}}`

全部 `POST` 请求需要 `X-Automation-Key`；`idempotency_key` 推荐按任务源事件唯一 ID 生成。注意 Prefect 的幂等性是 Flow Run 层面的能力，不代替外部平台 API 本身的去重和结果核对。

## 扩展新任务的步骤

1. 在 `src/automation_hub/flows` 中创建带 `@flow(name="...")` 的函数。
2. 在 `prefect.yaml` 增加部署，选择明确的 work pool。
3. 在 `gateway.py` 定义参数 schema 和登记 `JOB_REGISTRY`，不要直接接受 shell 命令和任意外部 URL。
4. 为 n8n 创建 Schedule / Webhook + HTTP Request 的 JSON 模板。
5. 增加测试，包括未授权和非法参数路径，再进行人工验收。
6. 如果需要有破坏性的写操作，新增显式审批步骤、审计记录和回滚方案，不要复用只读任务的权限。

## 多机器工作池

- `nas-local`：默认通用任务，Worker 在 NAS。
- `mac-local`：Mac 上需要本地 GUI / Apple 平台工具的任务，独立部署、独立工作池。
- `vps-remote`：外部监测/远程任务，独立配置 API、网络和凭据。

Process Worker 启动的是本机进程，不会自动把 NAS 的代码复制到 Mac/VPS。每台机器必须安装并更新相同版本代码（或者采用可审计的 Git pull / 容器镜像发布流程）。
