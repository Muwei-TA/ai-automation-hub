# 部署与安全清单

## 1. 先确认 Prefect API

请在 NAS 上用 `curl -fsS http://<prefect-host>:4200/api/health` 测试，并从 **Docker 容器内** 复测该地址。`localhost` 在容器中不等于 NAS 宿主机。若 Prefect 使用 HTTP Basic Auth，配置 `PREFECT_API_AUTH_STRING=user:password`。

## 2. 数据隔离与备份

本项目独立的 n8n PostgreSQL 不使用现有 Prefect/PostgreSQL 的 volume。不要直接把别的数据库目录挂入 n8n-db。备份方式：

```bash
docker compose exec -T n8n-db pg_dump -U n8n -d n8n > n8n-backup.sql
```

备份 `n8n-data` volume 和 `.env` 到**独立安全存储**，尤其不要丢失 `N8N_ENCRYPTION_KEY`，否则 n8n 已存凭据无法正常解密。恢复到新的数据库版本前要确认 PostgreSQL 主版本兼容性。

## 3. Worker 权限

示例默认不挂载宿主的 Docker socket、不挂载 NAS 的数据目录。要让 `nas-health` 看见真实宿主盘：可以只读挂载所需目录到 Worker，并将 `HEALTH_DISK_PATH` 指向该路径；但 `statvfs` 统计的是文件系统，而不是 Docker overlay 的虚拟视图。要查询 Docker 容器，建议优先通过只读监控导出器或受限代理，而不是直接传递 Docker socket。

## 4. 网络接入

n8n 与 Gateway 绑定 127.0.0.1，外部浏览器不能直接从另一个电脑访问 `http://NAS-IP:5678`。如需远程访问，在 HTTPS 反向代理或 Tailscale 后面开放，更新 `N8N_EDITOR_BASE_URL`、`WEBHOOK_URL` 和 `N8N_SECURE_COOKIE=true`；不要把 Prefect REST API 暴露公网。

n8n 流程里使用 `http://gateway:8099` 是因为两者在 Compose 内同一后端网络。从本机终端测试则使用 `http://127.0.0.1:8099`。

## 5. 验收顺序

1. `docker compose config` 验证配置替换。
2. 启动 `n8n gateway`，访问 Gateway 的 `/healthz`。
3. 在 Prefect 创建 `nas-local` pool，注册 4 个部署。
4. 启动 Worker 并确认从 Prefect UI 显示为健康。
5. `./scripts/smoke-test.sh`，观察返回的 `flow_run_id`。
6. 在 Prefect UI 确认该任务 `Completed`，不要把 HTTP 202 当成成功。
7. 导入 n8n `github-digest`，绑定 Header Auth 并手动执行，再激活定时器。
8. 最后开启 Gitea 和 ComfyUI 集成；将它们配置为可访问但不公开的内部服务。

## 6. 未来版本的建设任务

- 统一消息通知适配器（Telegram/Discourse/邮件），外加重试与死信队列。
- Gitea Webhook HMAC 校验，限定来源 + IP allowlist。
- NAS exporter 与容器指标/资源竞争监控。
- 执行日志敏感信息脱敏和 Token 计量。
- Mac/VPS Worker 的自动化代码分发和版本锁定。
- ComfyUI 图片结果回传、状态轮询和 GPU 队列限制。
- 只读 Gitea PR 审查 + 人工授权之后才可写回/合并。

## 7. GitHub 仓库

源代码托管在 [Muwei-TA/ai-automation-hub](https://github.com/Muwei-TA/ai-automation-hub)。该仓库当前为**公开仓库**；不要提交 `.env`、令牌、SSH 私钥、NAS 内网凭据或数据库备份。克隆方式：

```bash
git clone https://github.com/Muwei-TA/ai-automation-hub.git
cd ai-automation-hub
```

在部署主机上创建 `.env`，依据本文件逐项配置。生产配置应在主机端或专用密钥管理器中维护，不应写入 Git 历史。
