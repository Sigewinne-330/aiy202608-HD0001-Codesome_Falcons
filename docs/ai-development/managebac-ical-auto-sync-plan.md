# ManageBac 个人 iCal 自动同步开发计划

## 1. 目标

实现个人 ManageBac iCal 自动同步：用户只需绑定一次个人 iCal 订阅地址，IBuddy 后台定时拉取老师发布的任务，并自动同步到现有任务、日历、提醒和排期系统。

ManageBac 官方确认日历订阅属于从 ManageBac 到外部日历的持续单向同步，不需要保存用户的 ManageBac 密码，也不需要学校管理员 API Token。

- 官方说明：<https://help.managebac.com/hc/en-us/articles/360018804712-Managing-your-Calendars>

## 2. 功能范围

### 2.1 首版包含

- 每个 IBuddy 用户绑定一个个人 ManageBac iCal URL。
- 支持 `webcal://` 和 `https://` 地址。
- 默认每 10 分钟自动同步。
- 自动新增、更新老师发布的任务。
- 使用 iCal `UID` 去重。
- 自动进入现有 IBuddy 日历。
- 自动继承用户现有提醒配置。
- 支持立即同步、暂停、恢复和断开连接。
- 显示同步状态、最近同步时间、同步统计和错误。
- Token 失效时提示用户重新绑定。
- 支持简体中文、繁体中文和英文。

### 2.2 首版不包含

- ManageBac Public API。
- 浏览器插件或网页 DOM 抓取。
- 将 IBuddy 修改反向写回 ManageBac。
- 同步作业提交状态、成绩或附件。
- 保存 ManageBac 登录密码。
- 单个用户同时绑定多个 ManageBac 账号。
- 不提供严格筛选模式；个人 iCal 中所有具备 UID、标题和时间的项目统一导入任务。

## 3. 整体架构

```text
用户粘贴 webcal URL
       ↓
后端验证 URL、获取并解析 ICS
       ↓
加密保存订阅地址
       ↓
后台 Worker 每分钟扫描到期连接
       ↓
每个连接约每 10 分钟拉取一次
       ↓
VEVENT 标准化、分类、去重、比对
       ↓
创建或更新 IBuddy task
       ├─→ Calendar API 自动展示
       ├─→ Reminder Scheduler 自动安排提醒
       └─→ Scheduling Balancer 批量分析负载
```

这里的“自动同步”属于轮询，而不是 Webhook。预计任务在 ManageBac Feed 可见后的一个轮询周期内同步，默认约 10 分钟，但实际延迟仍受 ManageBac 自身 Feed 缓存影响。

## 4. 第一阶段：真实 Feed 结构验证

开发前使用重新生成的测试 iCal URL 完成一次只读验证，不使用曾公开展示过的 Token。

需要确认：

- 老师发布的 Task 是否生成 `VEVENT`。
- Feed 是否提供 Task、Deadline 与普通 Event 的类型字段；若未提供，则全部按任务导入。
- 截止日期使用 `DTSTART`、`DTEND` 还是自定义字段。
- 全天任务的 `DTEND` 是否采用 iCalendar 的排他日期规则。
- 是否包含稳定的 `UID`。
- 是否包含 `SEQUENCE`、`LAST-MODIFIED` 和 `STATUS`。
- 课程名称位于 `CATEGORIES`、标题、描述还是 URL。
- 是否包含 ManageBac 原任务链接。
- Feed 覆盖的过去和未来时间范围。
- 老师修改或取消任务后，Feed 如何变化。

验证后生成一组脱敏 `.ics` 测试 Fixture，后续自动化测试不再访问真实账号。

## 5. 数据库设计

新增三张表，不直接向现有 `task` 表写入同步控制字段。

### 5.1 `managebac_connections`

每个用户一条连接。

| 字段 | 用途 |
|---|---|
| `id` | 主键 |
| `user_id` | IBuddy 用户，唯一 |
| `encrypted_feed_url` | 加密后的订阅 URL |
| `feed_host` | 可安全展示的学校域名 |
| `status` | `pending/active/paused/error/reconnect_required` |
| `enabled` | 是否启用自动同步 |
| `sync_interval_minutes` | 同步间隔，默认 10 分钟 |
| `etag` | HTTP 条件请求标识 |
| `last_modified` | HTTP 条件请求时间 |
| `next_sync_at` | 下次同步时间 |
| `last_success_at` | 最近成功时间 |
| `consecutive_failures` | 连续失败次数 |
| `last_error_code` | 脱敏错误码 |
| `lease_owner` | Worker 租约持有者 |
| `lease_expires_at` | Worker 租约过期时间 |
| `created_at/updated_at` | 审计时间 |

### 5.2 `managebac_task_links`

维护远端事件与本地任务的映射。

| 字段 | 用途 |
|---|---|
| `connection_id` | 所属连接 |
| `external_uid` | iCal UID |
| `task_id` | IBuddy task ID |
| `remote_hash` | 远端受管字段摘要 |
| `remote_sequence` | iCal `SEQUENCE` |
| `remote_last_modified` | 远端修改时间 |
| `remote_snapshot` | 最近一次标准化字段快照 |
| `source_url` | ManageBac 任务地址 |
| `remote_state` | `active/cancelled` |
| `first_seen_at` | 首次发现时间 |
| `last_seen_at` | 最近出现时间 |
| `missing_count` | 连续未出现次数 |
| `created_at/updated_at` | 审计时间 |

唯一约束：

```text
(connection_id, external_uid)
```

### 5.3 `managebac_sync_runs`

保存最近同步结果：

- 触发方式：`automatic/manual/initial`。
- 开始与结束时间。
- HTTP 状态。
- 新增、更新、未变化、取消和跳过数量。
- 成功、部分成功或失败状态。
- 脱敏错误摘要。
- 建议只保留最近 90 天。

## 6. URL 与凭据安全

iCal 订阅 URL 内的 Token 视为密码。

具体措施：

- 前端只向后端提交一次完整 URL。
- 后端使用独立的 `INTEGRATION_CREDENTIAL_KEY` 加密。
- 不复用 JWT `SECRET_KEY`。
- API 响应只返回学校域名，不返回完整 URL。
- 日志、异常和同步记录不允许包含 Token。
- 不把 Token 写入 `.env.example`、测试 Fixture 或 Git。
- 只允许 `webcal://` 和 `https://`。
- `webcal://` 在后端转换为 `https://`。
- 默认只允许配置的 ManageBac 域名后缀。
- 检查 DNS 结果，禁止访问本机、内网和云元数据地址。
- 每次 HTTP 重定向后重新执行安全校验。
- 限制重定向次数、响应大小和连接超时。
- 断开连接时彻底清除加密凭据。

正式开发和测试不得使用曾在对话、截图或日志中公开过的 Token，应重新生成测试订阅地址。

## 7. iCal 解析和标准化

每个 `VEVENT` 标准化为内部对象：

```python
ManageBacCalendarItem(
    uid,
    kind,
    title,
    description,
    subject,
    deadline,
    source_url,
    sequence,
    last_modified,
    status,
    fingerprint,
)
```

字段映射：

| iCal 字段 | IBuddy 字段 |
|---|---|
| `UID` | 外部唯一标识 |
| `SUMMARY` | `task.title` |
| `DESCRIPTION` | `task.description` |
| `DTSTART/DTEND` | `task.deadline` |
| `CATEGORIES` | `task.subject`，前提是 Feed 中含义可靠 |
| `URL` | ManageBac 来源链接 |
| `SEQUENCE` | 更新版本 |
| `LAST-MODIFIED` | 远端修改时间 |
| `STATUS:CANCELLED` | 取消状态 |

解析限制：

- 标题、描述和 URL 做长度限制。
- HTML 描述清理为安全文本。
- 没有稳定 UID 的项目默认跳过并记录原因。
- 未能确认截止日期的事件不创建任务。
- ManageBac 未提供类型元数据时，普通 `VEVENT` 也按任务导入。
- 重复 UID 采用确定性规则保留最新版本。
- 不保存完整原始 ICS。

## 8. 同步规则

### 8.1 新任务

创建现有 `Task`：

```text
task_type = todo
status = todo
priority = medium
deadline = ManageBac 官方截止时间
reminder_offsets_minutes = null
effort_source = managebac
```

`reminder_offsets_minutes = null` 表示继承用户的默认提醒时间。

### 8.2 老师修改任务

ManageBac 负责以下字段：

- 标题。
- 描述。
- 学科。
- 官方截止时间。
- 来源链接。

IBuddy 负责以下字段：

- 个人提前截止时间。
- 提醒偏移。
- 优先级。
- AI 拆解结果。
- 估算工时。
- 排期。
- 用户进度。

同步只更新远端负责的字段，不覆盖本地规划字段。

### 8.3 截止时间改变

- 更新 `task.deadline`。
- 现有提醒校验会发现原截止时间不一致并取消旧提醒。
- 新截止时间自动生成新的提醒。
- 批次结束后只触发一次日程负载分析。

### 8.4 取消任务

只有 Feed 明确提供 `STATUS:CANCELLED` 时才视为取消：

- 将 `managebac_task_links.remote_state` 更新为 `cancelled`。
- 如果本地官方截止时间仍等于远端旧值，则清空官方截止时间，停止日历展示和提醒。
- 不删除任务。
- 不覆盖用户的个人截止时间和本地内容。
- 如果事件重新激活，则恢复远端截止时间。

### 8.5 Feed 中暂时消失

不自动删除，也不直接取消，只增加 `missing_count`。

原因是订阅 Feed 可能仅覆盖有限日期范围；部分 ManageBac 日历存在前后时间窗口。

- 官方示例：<https://help.managebac.com/hc/en-us/articles/360045878251-Viewing-Year-Group-Calendar-Discussions-Files>

只有显式取消才改变远端任务状态。

## 9. 后端接口

统一前缀：

```text
/api/integrations/managebac
```

计划接口：

```text
GET    /status
POST   /validate
POST   /connect
POST   /sync
PATCH  /settings
GET    /runs
DELETE /disconnect
```

接口行为：

- `validate`：验证 URL、解析 Feed，返回脱敏预览，不保存。
- `connect`：再次验证、加密保存，并执行首次同步。
- `sync`：手动立即同步，并进行频率限制。
- `settings`：暂停或恢复自动同步。
- `runs`：读取最近同步记录。
- `disconnect`：删除凭据，用户选择保留或删除已导入任务。
- 所有接口使用现有 JWT 用户认证和 `user_id` 隔离。

## 10. 后台 Worker

复用现有 APScheduler 基础设施：

- 每 60 秒查找 `next_sync_at <= now` 的连接。
- 默认每个连接 10 分钟同步一次。
- 使用数据库租约避免多 Worker 重复同步。
- 设置 `max_instances=1` 并开启 coalesce。
- 单个连接失败不影响其他用户。
- 网络失败指数退避，例如 10、20、40、60 分钟。
- 成功后重置失败计数。
- `401/404/410` 连续出现后转为 `reconnect_required`；`403` 作为可能的服务商客户端策略错误退避重试，不直接判定 Token 失效。
- `429` 尊重 `Retry-After`。
- `5xx` 和超时自动重试。
- 手动同步和自动同步使用同一同步引擎。

当前 `docker-compose.yml` 只启动 MySQL、后端和前端，开发时需要新增 Worker 服务，确保提醒与 ManageBac 同步在用户关闭网页后仍能运行。

## 11. 前端设计

在现有设置弹窗增加“ManageBac 同步”分节，不新增独立页面。

### 11.1 未连接状态

- 功能说明。
- iCal URL 输入框。
- “在哪里获取？”操作指引。
- “验证并连接”按钮。
- Token 安全提示。

### 11.2 已连接状态

- 学校域名。
- 状态：正常、暂停、异常或需要重新连接。
- 最近成功同步时间。
- 下次预计同步时间。
- 最近一次新增和更新数量。
- “立即同步”。
- “暂停/恢复”。
- “断开连接”。
- 最近同步记录。

### 11.3 任务展示

- 增加 ManageBac 来源标签。
- 有来源链接时提供“在 ManageBac 中打开”。
- 不在前端展示订阅 Token。

## 12. 计划修改的文件

### 12.1 新增

```text
backend/models/managebac.py
backend/schemas/managebac.py
backend/routers/managebac.py
backend/services/managebac_security.py
backend/services/managebac_ical.py
backend/services/managebac_sync.py
backend/migrate_managebac_sync.sql
backend/tests/test_managebac_security.py
backend/tests/test_managebac_ical.py
backend/tests/test_managebac_sync.py
backend/tests/test_managebac_api.py
backend/tests/fixtures/managebac_calendar.ics

frontend/src/services/managebac.js
frontend/src/components/ManageBacIntegrationPanel.vue
frontend/tests/managebac-state.test.mjs
```

### 12.2 修改

```text
backend/models/__init__.py
backend/main.py
backend/config.py
backend/requirements.txt
backend/reminder_worker.py
docker-compose.yml
.env.example

frontend/src/components/SettingsDialog.vue
frontend/src/locales/zh-CN.js
frontend/src/locales/zh-TW.js
frontend/src/locales/en.js
```

### 12.3 可能修改

```text
backend/schemas/task.py
frontend/src/views/TasksView.vue
frontend/src/components/TaskDrawer.vue
```

这些可能修改用于返回和展示来源标签，不改变任务核心行为。

## 13. 测试计划

### 13.1 单元测试

- `webcal` 转 `https`。
- URL 验证和 SSRF 防护。
- Token 加密、解密和日志脱敏。
- 全天日期、带时区日期和 UTC 日期。
- ICS 排他 `DTEND`。
- 重复 UID。
- `SEQUENCE` 和修改时间。
- 取消事件。
- 非任务事件过滤。
- 超大 Feed、格式损坏和缺少 UID。
- HTML 和恶意文本清理。

### 13.2 同步测试

- 首次同步创建任务。
- 重复同步不重复创建。
- 修改标题和截止时间。
- 保留本地提醒和个人截止时间。
- 显式取消后停止提醒。
- Feed 暂时缺项时不删除。
- 两个用户数据完全隔离。
- 多 Worker 租约互斥。
- 同步失败后事务回滚。
- 日程分析每批只触发一次。

### 13.3 集成测试

- 同步后 `/api/calendar` 能查到任务。
- 提醒调度器能生成默认提醒。
- 截止时间改变后旧提醒取消、新提醒生成。
- 断开连接后凭据不可恢复。
- API 响应和日志不泄露 Token。

### 13.4 前端测试

- 连接状态切换。
- URL 错误提示。
- 同步中禁用重复点击。
- 401 后退出登录。
- 三语文案完整。
- 移动端设置界面。

## 14. 验收标准

1. 用户只需复制一次 iCal URL。
2. 同一 Feed 重复同步 100 次仍只有一条对应任务。
3. 新 Task 在 Feed 可见后的一个轮询周期内进入 IBuddy。
4. 老师修改截止时间后，本地官方截止时间正确更新。
5. 用户的个人截止时间、提醒配置和规划内容不被覆盖。
6. 同步任务自动出现在日历。
7. 同步任务自动进入提醒系统。
8. Token 不出现在 API 响应、日志、数据库明文或 Git 中。
9. 单用户同步失败不影响其他用户。
10. 断开或失效时界面明确提示，不静默停止。
11. 后端、前端测试和构建全部通过。
12. 现有任务、日历、提醒和排期测试无回归。

## 15. 开发顺序

1. 脱敏 Feed 验证与 Fixture。
2. 数据表、加密和 URL 安全。
3. iCal 解析器。
4. 幂等同步引擎。
5. 后端接口。
6. Calendar 和 Reminder 集成测试。
7. Worker 和 Docker Compose。
8. 前端设置面板。
9. 来源标签和同步记录。
10. 全量回归与单账号灰度。

## 16. 开发授权边界

该功能需要修改后端、数据库和部署配置，原因是“用户关闭网页后仍能自动同步”必须由服务器持久保存连接并运行后台任务。

正式实施前，需要明确批准以下需求项：

- 新增三张 ManageBac 集成表。
- 新增 ManageBac 后端接口和同步服务。
- 增加 iCal 解析依赖与凭据加密配置。
- 修改后台 Worker。
- 修改 Docker Compose 以启动 Worker。
- 前端设置页增加 ManageBac 连接管理。
