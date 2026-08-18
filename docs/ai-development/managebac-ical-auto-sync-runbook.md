# ManageBac 个人 iCal 自动同步部署与验收手册

## 1. 部署前配置

在项目根目录的 `.env` 中配置独立的 Fernet 密钥。该密钥不能复用 JWT `SECRET_KEY`：

```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

将输出写入：

```dotenv
INTEGRATION_CREDENTIAL_KEY=<生成的 Fernet 密钥>
MANAGEBAC_SYNC_INTERVAL_MINUTES=10
```

注意：

- 不要把 `.env`、密钥或个人 iCal URL 提交到 Git。
- 已有用户连接后不能直接更换或丢失密钥，否则旧连接无法解密，需要用户重新连接。
- iCal URL 是 bearer credential，应像密码一样管理；曾在聊天、截图或日志中暴露过的 URL 应先在 ManageBac 中重新生成。

其余可选网络限制见根目录 `.env.example`。

## 2. 数据库

后端启动时会通过 SQLAlchemy metadata 创建三张新增表：

- `managebac_connections`
- `managebac_task_links`
- `managebac_sync_runs`

需要由 DBA 显式执行变更时，使用：

```text
backend/migrate_managebac_sync.sql
```

迁移只新增表，不修改现有 `task` 表。

## 3. 服务启动

`docker-compose.yml` 已包含独立 `worker`。它同时运行现有提醒调度和 ManageBac 轮询，并在后端健康、数据库建表完成后启动。

```bash
docker compose up -d --build mysql backend worker frontend
```

后台每 60 秒查找一次到期连接；每个连接默认每 10 分钟拉取一次。实际可见延迟还会受到 ManageBac Feed 缓存影响。

非 Docker 部署必须额外保持以下进程常驻：

```bash
cd backend
python reminder_worker.py
```

## 4. 首次灰度验收

请使用重新生成、未在对话或日志中公开过的测试订阅 URL：

1. 登录 IBuddy，打开“设置 → ManageBac 同步”。
2. 粘贴个人 `webcal://` 或 `https://` URL，先点击“验证地址”。
3. 确认预览只包含 Task/Deadline，不包含普通校园活动。
4. 点击“连接并首次同步”。
5. 在任务页确认 ManageBac 来源标签、标题、科目和官方截止时间。
6. 在日历中确认该任务出现在对应日期。
7. 在提醒设置中保留默认偏移，确认任务继承默认提醒。
8. 在 ManageBac 修改测试任务的标题或截止时间，等待一个轮询周期或点击“立即同步”。
9. 确认远端字段被更新，而本地优先级、个人截止时间、提醒覆盖和进度没有被覆盖。
10. 暂停、恢复和断开连接各验证一次；断开时分别验证“保留导入任务”和“删除导入任务”。

## 5. 状态与故障处理

- `active`：同步正常。
- `paused`：用户暂停自动同步，仍可手动同步。
- `error`：暂时失败，worker 会指数退避重试。
- `reconnect_required`：订阅连续返回 `401/404/410`，或加密凭据无法解密；用户需生成新 URL 并重新连接。
- `403`：ManageBac/Cloudflare 可能因日历客户端兼容策略拒绝请求，即使同一地址可被 Google Calendar 读取；IBuddy 使用 iCal 兼容请求并保留重试，不把它误判为 Token 失效。
- `429`：尊重 ManageBac 的 `Retry-After` 后再试。

同步记录只保存脱敏状态和计数，保留 90 天；API、数据库审计记录和应用 INFO 日志均不应出现完整订阅 URL。

## 6. 回滚

应用级回滚优先让用户在设置中断开连接；这会删除加密凭据和同步映射，并可选择是否删除导入任务。

部署级回滚可停止 `worker`，再回滚应用镜像。新增表不会影响旧代码；确认不再需要审计数据后，再由 DBA 单独删除新增表。不要在未经备份的情况下直接删除用户任务。
