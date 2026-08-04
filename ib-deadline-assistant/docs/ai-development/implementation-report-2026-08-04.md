# IB Deadline Assistant 实施与交接报告

**报告日期：** 2026-08-04
**代码基线：** `1283099 merge: sync remote image upload fixes`
**远端仓库：** `https://gitee.com/zejun090705/cf.git`
**范围：** 注册邮箱验证、日历到期提醒后端、提醒邮件与聊天同步、LLM 提醒 Agent、角色卡、运行与验收配置。

## 1. 交付概览

本次完成两条后端能力链路：

1. **注册邮箱验证**：用户必须取得并验证邮箱验证码，才能完成注册；验证码、注册凭证、限流和 SMTP 异常都在服务端处理。
2. **日历到期提醒**：独立 Worker 在每位用户本地时区的上午 09:00 后扫描未完成事项。命中提醒档位的事项会合并为每日 digest，由专用 Reminder Agent 生成标题及 1–2 句提示，并分别投递到邮件和站内 AI 聊天。

此外，已保留并合并云端已有的图片压缩、图片持久化和部署相关修改；推送前先同步远端，再以普通 merge 方式整合，未覆盖云端提交。

## 2. 总体架构

```text
Vue 3 + Vite 前端
  └─ 注册页：请求验证码 → 验证验证码 → 携带一次性凭证注册

FastAPI API
  ├─ /api/auth/*：注册、登录、验证码申请与验证
  ├─ /api/reminders/*：偏好、角色卡、历史记录
  └─ /api/admin/reminders/run：管理员 dry-run/手动执行

MySQL + SQLAlchemy
  ├─ user / task / sub_task / deadlines / conversation / chat_message
  ├─ email_verifications
  └─ reminder_* / llm_usage_records

独立 reminder_worker.py
  └─ 扫描 → 幂等 claim → 生成 digest → 投递聊天和邮件 → 重试/审计

外部服务
  ├─ QQ SMTP：注册验证码和日历提醒邮件
  └─ Ark（优先）/ DeepSeek（备选）：Reminder Agent 与主聊天
```

### 2.1 进程边界

- **FastAPI/Uvicorn** 仅承载 HTTP API、用户操作与管理入口。
- **Reminder Worker** 是独立进程，不能嵌入每一个 Uvicorn worker；否则多实例部署会重复调度。
- **SMTP** 通过 `EmailTransport` 抽象接入，未来短信、软件连接器等只需实现同一渠道协议，不可绕过调度和审计层。
- **Reminder Agent** 是独立于主聊天 Agent 的纯文本子 Agent：没有主聊天的对话历史，不执行写操作或外部操作，只可使用受限的只读日程工具。

## 3. 注册邮箱验证实现

### 3.1 API 流程

1. `POST /api/auth/verification-codes` 接收邮箱，创建验证码记录并尝试 SMTP 投递，成功时返回 `202`。
2. `POST /api/auth/verification-codes/verify` 校验六码验证码，返回短时有效、一次性使用的 `verification_token`。
3. `POST /api/auth/register` 必须同时携带用户名、邮箱、密码和该 token；服务端在同一事务中创建用户、赠送初始积分并消费凭证。

前端在验证码邮件请求成功前不展示验证码输入框；服务不可用时显示中文可操作提示，而不是浏览器原始的 `Failed to fetch`。

### 3.2 安全与可靠性

- 验证码和注册凭证仅存储摘要，原文不会持久化。
- 默认验证码有效期 10 分钟、最多 5 次错误尝试。
- 同一邮箱存在重发冷却、每小时邮箱/IP 限流；对已注册邮箱采用通用响应以避免枚举。
- SMTP 认证、网络、内容错误转换为受控错误码/HTTP 503，不向页面回显底层异常或凭据。
- `SMTP_USE_STARTTLS` 与 `SMTP_USE_SSL` 互斥校验；QQ Mail 使用 465 + SSL 的配置模式。

## 4. 日历提醒实现

### 4.1 候选事项与提醒时间

调度器扫描三类**未完成**事项：

- 顶层 `todo` 任务（不含子任务的任务）；
- 流程任务中的未完成 `sub_task`；
- 未完成 `Deadline`。

用户偏好保存 IANA 时区、语言、渠道开关、角色卡和提醒档位。当前固定档位为：`D-2、D-1、D0、D+1、D+3、D+7`。Worker 以用户本地时区判断，在本地 09:00 后执行；同一用户、同一天的事项合并为一封 digest。

### 4.2 幂等、并发与数据模型

提醒使用持久化 claim，而不是仅依赖内存定时器：

- `reminder_occurrences` 以“用户 + 事项 + 截止日 + 档位”唯一约束避免同一事项重复进入提醒。
- `reminder_digests` 以“用户 + 本地日期”唯一约束实现每日合并。
- `reminder_deliveries` 以“digest + 渠道”唯一约束跟踪邮件与聊天的独立状态。
- 投递状态包含 `pending / attempting / delivered / retryable / failed / skipped`，并保存尝试次数、重试时间和非敏感错误码。
- 对 SMTP 提交结果未知的中断场景不盲目重发，降低重复邮件风险；可重试故障最多尝试三次。

### 4.3 专用 Reminder Agent

Reminder Agent 的系统提示与主 Agent 分离，输出契约为一个 JSON 对象：

```json
{"subject":"清晰单行标题","framing":"一到两句纯文本提醒"}
```

- 根据用户 BCP 47 语言生成中文或其他语言内容。
- 角色卡只影响语气，不能覆盖语言、身份、权限、输出格式或投递目标。
- 日程标题、描述、角色卡示例都作为不可信数据处理，降低提示注入风险。
- 最多调用 provider 三次；provider 缺失、输出不合法、调用失败或额度受限时回退至确定性本地模板。
- 最终项目清单和 `/chat` 链接由后端确定性拼接，避免 LLM 漏列或伪造项目。
- 每次 LLM 尝试记录到 `llm_usage_records`，用于 token 记账和配额控制。

预置全局角色卡：`friendly-warm-guy`、`tech-geek`、`sweet-high-school-girl`。当前普通用户只可读取、选择活跃全局卡；用户自建卡和 SillyTavern JSON/PNG 导入已作为后续扩展边界保留，未提前暴露写接口。

### 4.4 投递渠道

同一个不可变 digest 被分别投递：

- **邮件**：通过 SMTP 发送标题、提示语、完整项目列表和 AI 聊天链接。
- **站内聊天**：写入或复用标题为“日程提醒”的 `conversation`，再写入普通 `assistant` 消息。消息 `metadata` 标注 `source=reminder`、digest ID、角色卡 ID 和最小化事项引用，前端后续可据此展示“查看详情”。

邮件失败不会阻止聊天投递，聊天失败也不会阻止邮件投递。

## 5. 主要文件与职责

| 区域 | 关键文件 | 职责 |
|---|---|---|
| 注册验证 | `backend/routers/auth.py` | 验证码、注册、登录 API 及事务编排 |
| 邮件 | `backend/services/email_service.py` | SMTP 配置、验证码邮件与通用邮件发送 |
| 验证凭证 | `backend/services/email_verification.py` | 摘要、过期、限流、凭证消费 |
| 调度 | `backend/reminder_worker.py` | 独立循环或单次执行入口 |
| 编排 | `backend/services/reminder_orchestrator.py` | 候选、digest、生成、投递、重试协调 |
| 候选与 claim | `backend/services/reminder_scheduler.py` | 时区、D-N 计算、幂等 claim、快照重校验 |
| 提醒内容 | `backend/services/reminder_agent.py` | 专用提示、工具白名单、格式验证、模板回退 |
| 渠道 | `backend/services/reminder_channels.py` / `reminder_delivery.py` | 聊天/邮件投递与状态机 |
| 偏好和角色卡 | `backend/services/reminder_preferences.py` / `reminder_seeds.py` | 默认值、校验、内置角色卡 |
| 数据模型 | `backend/models/reminder.py` / `email_verification.py` | 提醒、使用记录、验证码持久化 |
| API | `backend/routers/reminders.py` | 偏好、角色卡、历史和管理员运行入口 |
| 前端注册 | `frontend/src/views/RegisterView.vue` | 邮箱验证分步注册和中文错误提示 |

## 6. 配置与部署

敏感配置只能放在未跟踪的 `backend/.env` 或部署平台 secret store，不可提交至 Git。QQ SMTP 的运行配置形态为：

```dotenv
SMTP_HOST=smtp.qq.com
SMTP_PORT=465
SMTP_USERNAME=<QQ 邮箱>
SMTP_PASSWORD=<QQ SMTP 授权码>
SMTP_FROM_EMAIL=<QQ 邮箱>
SMTP_FROM_NAME=IBuddy
SMTP_USE_STARTTLS=false
SMTP_USE_SSL=true
SMTP_TIMEOUT_SECONDS=10
```

生产还需要设置 `APP_BASE_URL` 为真实 HTTPS 域名，并运行第二个进程：

```bash
cd backend
.venv/bin/python reminder_worker.py
```

单次验收/cron 可使用：

```bash
.venv/bin/python reminder_worker.py --once
```

## 7. 验收与实际结果

### 已通过

- Python 全量编译：`python -m compileall -q .` 通过。
- 前端生产构建：`npm run build` 通过（仅存在 Vite 大 bundle 提示，不阻断构建）。
- 后端与前端代理健康检查：`/api/health` 均返回正常状态。
- 提醒 runtime readiness：数据库结构、聊天链接、Worker 配置、LLM 配置检测、SMTP 配置均通过。
- QQ SMTP 连接与认证检查通过（未在报告中记录账号或授权码）。
- 真实 Worker 单次运行正常：现有数据库无日程候选时，返回 0 个候选、0 次生成、0 次投递。
- 使用临时 D-2 未完成任务执行 dry-run：成功识别 1 个候选事项；测试数据随后已删除。
- 本地改动已与云端图片相关提交合并，并推送到 `origin/main`；最终本地与远端为 `0 ahead / 0 behind`。

### 未完成或待补充的真实验收

- 当前数据库在测试时没有真实待提醒事项，因此未对真实用户完成“生成 → 邮件收件箱 → 聊天消息”全链路验收。
- Reminder Agent 的真实 provider smoke gate 未完成：测试环境使用的 Ark key 为测试值，无法证明真实 LLM 生成；确定性模板回退路径已纳入设计。
- 注册邮箱真实收信、输入验证码并最终完成注册的人工验收仍应按 `docs/ai-development/email-verification-acceptance.md` 执行。
- 部署到云端时必须在部署平台配置 SMTP/数据库/AI 等 secrets；这些值不在 Git 仓库内，云端仅有代码无法自动携带本机 `.env`。

## 8. 风险与后续建议

1. **立即轮换泄露凭据**：任何曾粘贴到聊天、终端截图或其他不受控位置的 SMTP 授权码、Gitee 私人令牌都应立即撤销并重新生成。
2. **补做真实验收**：创建一个受控的 D-2 未完成事项，在用户时区 09:00 后执行一次 Worker，确认邮件收件、聊天消息、内容语言、角色卡语气和幂等重跑。
3. **生产调度**：将 `reminder_worker.py` 作为独立 service、cron 或容器进程托管，不能只启动 FastAPI。
4. **数据库迁移**：已有旧环境先执行提醒相关迁移 SQL；新环境可使用完整初始化脚本并由 SQLAlchemy 启动时补齐模型表。
5. **前端后续工作**：可接入提醒偏好、角色卡选择和投递历史 API；用户自建角色卡和 SillyTavern 导入应在权限、私有作用域和内容审查明确后再开放。

## 9. 结论

本次代码已完成并推送：注册邮箱验证、可扩展的日历提醒后端、独立 Reminder Agent、角色卡、邮件/聊天双渠道、幂等与重试审计、运行检查及前端注册交互均已落地。构建、运行检查和受控调度 dry-run 已通过；真实 SMTP 认证已通过。剩余工作集中在使用真实 AI 密钥和真实待提醒日程完成最终人工收件验收，以及在实际部署环境安全注入 secrets。
