# 测试与验收（v0.2 开发阶段）

## 1. 离线验证（无需 NAS 账号与 API Token）

```bash
python -m pip install -e '.[gateway,worker,dev]'
python -m compileall -q src
python -m pytest -q --cov=automation_hub --cov-report=term-missing --cov-fail-under=90
```

测试覆盖 Gateway API Key 鉴权、任务白名单、参数校验、模拟 Prefect API 调度；四个 Flow 的成功与拒绝路径（通过 `.fn()` 直接调用业务逻辑，不运行 Prefect 任务调度）；LLM/通知服务的模拟 HTTP；以及部署前配置检查。网络测试使用 `httpx.MockTransport`，不会使用真实凭据、发送通知或触发 GPU 工作流。

> 注意：覆盖率只衡量上述 Python 代码语句；并不证明容器、n8n 节点或真实 Prefect Worker 可以正确运行。CI 对总代码覆盖率设置 90% 阈值。

## 2. 部署前配置检查

复制 `.env.example` 到 `.env`，填入独立随机密钥后执行：

```bash
python scripts/preflight.py --env-file .env
```

此操作不会输出配置值，也不尝试访问 Prefect。示例 `.env.example` 因含占位符会故意检查失败。

## 3. 真实环境分级验收

1. 在 NAS 上执行 `docker compose config`；仅在确认不会覆盖已有服务端口后部署独立 n8n/PostgreSQL/Gateway。
2. 使用既有 Prefect Server，创建 work pool、注册四个 Deployment，再启动可执行相同版本代码的 Worker。
3. 执行 `scripts/smoke-test.sh` 并在 Prefect UI 检查对应 flow run 为 `Completed`；`202` 仅代表调度请求被接受。
4. 在隔离的 n8n 实例中导入 JSON、绑定凭据、**手动**执行工作流后再启用调度。
5. 对 Gitea/ComfyUI/LLM 的真实联调使用测试仓库、测试模板与限流；不得以现有 `gitea-status-webhook.json` 的未验证签名入口直接开放公网。

## 4. 尚未自动化验收的内容

Docker 镜像构建与运行、n8n UI 导入兼容性、真实 Prefect Server+Worker 跨主机调度、NAS 盘挂载及 GPU 队列、网络断连恢复。这些必须在有 Docker 和隔离测试服务的环境中继续验收；不可把当前测试结果当作生产就绪证明。


生产就绪验收门槛参见 [PRODUCTION_ACCEPTANCE.md](PRODUCTION_ACCEPTANCE.md)。如未完成真实容器、工作池和故障恢复验收，不得将单元测试通过认定为生产就绪。
