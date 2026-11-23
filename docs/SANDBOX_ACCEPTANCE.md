# 隔离沙盒验收环境（2026-11-23）

运行平台：GitHub-hosted Ubuntu Docker Runner。资源使用独立容器、一次性数据卷和测试密钥，不连接 NAS、BlackRoom 正式服务或真实账户。

## 真实运行的组件

- Prefect 3 Server、Process Worker、FastAPI Gateway：真正的容器和 HTTP 调度。
- fixture-api：使用 Python 标准库实现的 Gitea Commit Status、GitHub Search、ComfyUI Prompt、LLM 和通知接口模拟服务。
- n8n + PostgreSQL：由现有的 n8n-postgres-smoke CI 任务分别验证工作流导入/导出与临时库备份/恢复。

## 执行方式

在安装 Docker Compose v2、Python 3 的全新测试主机上执行以下命令：

    GATEWAY_API_KEY=<independent-test-key> \
    GITEA_WEBHOOK_SECRET=<independent-test-hmac-secret> \
    PREFECT_API_URL=http://prefect-ci:4200/api \
    N8N_DB_PASSWORD=<test-db-secret> \
    N8N_ENCRYPTION_KEY=<test-encryption-secret> \
    python3 scripts/sandbox-acceptance.py

GitHub Actions 的 sandbox-acceptance Job 自动提供非生产测试值。命令执行期间创建镜像和容器，测试完成或失败后都会尝试删除容器及卷。

## 验收覆盖

- Compose、容器镜像、实际 Deployment 注册和 Prefect readiness。
- Gateway 未授权访问、非白名单任务、错误参数均被拒绝。
- Gitea HMAC 错误签名被拒绝、错误内容类型被拒绝、无关事件忽略、有效 Push 成功，重复提交验证 Prefect 幂等 Run ID。
- NAS 健康检查、Gitea 状态检查、ComfyUI 提交、GitHub 摘要四个 Flow 通过真实 Prefect Process Worker 运行至 Completed。
- 不存在的 ComfyUI 模板应使 Flow Run 失败而不是假成功。
- 检查模拟端实际收到查询、通知、LLM 调用、ComfyUI Prompt 文本替换，且只有一次 ComfyUI 提交。
- 生成 artifacts/sandbox-acceptance.json 并上传到 CI Artifact，保留通过项、失败项、Flow Run ID 和模拟服务调用计数。

## 范围边界

这不是真实 Gitea、GitHub、LLM 或 ComfyUI GPU 的业务验收；模拟 API 不能证明图片真正生成。现有 n8n 工作流只验证导入/导出，没有实际自动定时触发。也不覆盖跨 NAS/Mac/VPS 的远程 Worker、正式密钥、生产备份恢复、实际 Webhook 签名兼容性或长期稳定性。全部隔离测试通过仍不代表可以批准生产发布。
