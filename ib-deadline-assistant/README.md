# 长期任务规划师 (ib-deadline-assistant)

一个全栈 Web 应用，帮助用户管理长期任务——输入目标和截止日期，系统自动生成分阶段执行计划，支持任务拆解、进度管理、AI 对话助手、日历视图和 Deadline 管理。

## 技术栈

| 层 | 技术 |
|---|------|
| 后端框架 | Python + FastAPI |
| ORM | SQLAlchemy |
| 数据库 | MySQL |
| 前端框架 | Vue 3 + Vite |
| UI 组件库 | Vuetify 3 |
| AI 引擎 | 豆包 (Ark API) 优先，DeepSeek 备选 |

## 环境要求

- **Python** ≥ 3.10
- **Node.js** ≥ 18
- **MySQL** ≥ 8.0
- **Git**

## 项目结构

```
ib-deadline-assistant/
├── backend/                  # 后端 FastAPI
│   ├── main.py               # 应用入口
│   ├── config.py             # 配置（从环境变量读取）
│   ├── database.py           # 数据库引擎 & 会话
│   ├── requirements.txt      # Python 依赖
│   ├── init_db.sql           # 数据库建表脚本
│   ├── models/               # SQLAlchemy 数据模型
│   ├── schemas/              # Pydantic 请求/响应模型
│   ├── routers/              # API 路由
│   └── services/             # 业务逻辑（认证、AI 服务）
│
├── frontend/                 # 前端 Vue 3
│   ├── package.json          # npm 依赖
│   ├── vite.config.js        # Vite 配置（含 API 代理）
│   └── src/
│       ├── App.vue           # 根组件
│       ├── router/           # 路由配置
│       ├── stores/           # 状态管理
│       ├── components/       # 公共组件
│       └── views/            # 页面组件
```

## 快速开始

### 1. 克隆仓库

```bash
git clone git@gitee.com:zejun090705/cf.git
cd ib-deadline-assistant
```

### 2. 配置环境变量

复制示例文件并填写实际值：

```bash
cp backend/.env.example backend/.env
```

编辑 `backend/.env`，至少填写数据库、AI（如需真实 AI 回复）和 SMTP 配置：

```
# 必填：MySQL 密码
DB_PASSWORD=你的MySQL密码

# 必填：豆包 API Key（从火山引擎控制台获取）
ARK_API_KEY=你的ARK_API_KEY

# 注册邮箱验证码发送
SMTP_HOST=smtp.example.com
SMTP_USERNAME=你的SMTP账号
SMTP_PASSWORD=你的SMTP应用专用密码或服务凭据
SMTP_FROM_EMAIL=no-reply@example.com
```

完整环境变量说明见下方 [环境变量](#环境变量)。

### 3. 初始化数据库

```bash
# 用 root 账户创建数据库并建表
mysql -u root -p < backend/init_db.sql
```

该脚本会创建 `ib_assistant` 数据库和以下表：
- `user` — 用户表
- `tasks` — 任务表
- `deadlines` — 截止日期表
- `chat_history` — 聊天历史表
- `email_verifications` — 注册邮箱验证码、一次性凭证和限流历史

同时预置了一个 demo 用户（用户名：`demo`，密码：`demo123`）。

### 4. 启动后端

```bash
cd backend

# 首次运行时创建项目虚拟环境
python3 -m venv .venv

# 激活虚拟环境
source .venv/bin/activate   # macOS / Linux
# .venv\Scripts\activate    # Windows

# 安装依赖
pip install -r requirements.txt

# 启动服务
uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

后端运行在 `http://127.0.0.1:8000`，API 交互文档：`http://127.0.0.1:8000/docs`

### 5. 启动前端

打开新终端：

```bash
cd frontend

# 安装依赖
npm install

# 启动开发服务器
npm run dev
```

前端运行在 `http://localhost:5173`，Vite 自动将 `/api` 请求代理到后端 `http://127.0.0.1:8000`。

浏览器打开 `http://localhost:5173` 即可使用。

### 6. 注册功能就绪检查

保持 MySQL、后端和前端同时运行，在项目根目录执行：

```bash
backend/.venv/bin/python backend/check_registration_readiness.py
```

该只读命令分别检查 Python 依赖、后端健康、Vite `/api` 代理、数据库验证码表和 SMTP 配置。它不会发送邮件、创建验证码记录或输出配置值。只有显示 `READY` 后才应开始真实邮箱验收；`NOT READY` 会指出需要修复的具体层。

如果前端改用了其他端口，可显式指定代理健康地址：

```bash
backend/.venv/bin/python backend/check_registration_readiness.py \
  --frontend-url http://127.0.0.1:5174/api/health
```

---

## 环境变量

| 变量名 | 默认值 | 说明 |
|--------|--------|------|
| `DB_HOST` | `127.0.0.1` | MySQL 主机地址 |
| `DB_PORT` | `3306` | MySQL 端口 |
| `DB_USER` | `root` | MySQL 用户名 |
| `DB_PASSWORD` | （空） | MySQL 密码 |
| `DB_NAME` | `ib_assistant` | 数据库名 |
| `ARK_API_KEY` | （空） | 豆包 API Key（主 AI 引擎） |
| `ARK_BASE_URL` | `https://ark.cn-beijing.volces.com/api/v3` | 豆包 API 地址 |
| `ARK_MODEL` | `doubao-1.5-pro-32k` | 豆包模型名 |
| `DEEPSEEK_API_KEY` | （空） | DeepSeek API Key（备选） |
| `DEEPSEEK_BASE_URL` | `https://api.deepseek.com` | DeepSeek API 地址 |
| `DEEPSEEK_MODEL` | `deepseek-chat` | DeepSeek 模型名 |
| `SECRET_KEY` | `ib-assistant-secret-key-change-me` | JWT 签名密钥 |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | `1440` | JWT 过期时间（分钟，默认 24h） |
| `EMAIL_VERIFICATION_CODE_TTL_SECONDS` | `600` | 注册验证码有效期（秒） |
| `EMAIL_VERIFICATION_PROOF_TTL_SECONDS` | `900` | 验证成功后的注册凭证有效期（秒） |
| `EMAIL_VERIFICATION_MAX_ATTEMPTS` | `5` | 单个验证码最多错误尝试次数 |
| `EMAIL_VERIFICATION_RESEND_COOLDOWN_SECONDS` | `60` | 同一邮箱重发冷却时间（秒） |
| `EMAIL_VERIFICATION_EMAIL_LIMIT_PER_HOUR` | `5` | 单邮箱每小时请求上限（含防枚举抑制请求） |
| `EMAIL_VERIFICATION_IP_LIMIT_PER_HOUR` | `20` | 单来源 IP 每小时请求上限 |
| `SMTP_HOST` | （空） | SMTP 服务器；留空时注册验证码发送会返回 503 |
| `SMTP_PORT` | `587` | SMTP 端口 |
| `SMTP_USERNAME` | （空） | SMTP 登录用户名 |
| `SMTP_PASSWORD` | （空） | SMTP 登录密码 |
| `SMTP_FROM_EMAIL` | （空） | 验证邮件发件地址（必填） |
| `SMTP_FROM_NAME` | `IB Deadline Assistant` | 验证邮件发件人名称 |
| `SMTP_USE_STARTTLS` | `true` | 使用 STARTTLS |
| `SMTP_USE_SSL` | `false` | 连接时直接使用 SSL；不能与 STARTTLS 同时启用 |
| `SMTP_TIMEOUT_SECONDS` | `10` | SMTP 网络超时（秒） |
| `APP_BASE_URL` | `http://localhost:5173` | 邮件内 AI 聊天绝对链接的站点根地址 |
| `REMINDER_WORKER_INTERVAL_SECONDS` | `60` | 独立提醒 Worker 扫描/重试间隔，最小 10 秒 |
| `LLM_MONTHLY_TOKEN_QUOTA` | `0` | 每用户月度 LLM token 上限；0 表示只记账不限制 |

> **AI 引擎说明**：主聊天优先使用豆包（Ark），失败后降级到 DeepSeek。提醒 Agent 最多进行三次 provider 调用；两个都不配置时提醒使用确定性模板，交互聊天会报告未配置。

### Gmail SMTP 示例

以下仅为 Gmail 示例，请优先核对邮件服务商的最新官方设置：

```dotenv
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USERNAME=your-account@gmail.com
SMTP_PASSWORD=你的Google应用专用密码
SMTP_FROM_EMAIL=your-account@gmail.com
SMTP_USE_STARTTLS=true
SMTP_USE_SSL=false
```

Gmail 官方说明 TLS/STARTTLS 使用 `smtp.gmail.com:587` 且需要认证；使用应用专用密码时，Google 账号必须启用两步验证。不要填写普通登录密码，也不要提交 `backend/.env`。参考 [Gmail SMTP 设置](https://support.google.com/mail/answer/7104828) 和 [Google 应用专用密码](https://support.google.com/accounts/answer/185833)。工作或学校账号可能由管理员限制此功能。

---

## 前端生产构建

```bash
cd frontend
npm run build       # 构建，产物在 dist/
npm run preview     # 本地预览构建产物
```

---

## API 概览

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/health` | 健康检查 |
| POST | `/api/auth/verification-codes` | 请求注册邮箱验证码（成功返回 202） |
| POST | `/api/auth/verification-codes/verify` | 验证邮箱验证码并取得一次性注册凭证 |
| POST | `/api/auth/register` | 用户注册 |
| POST | `/api/auth/login` | 用户登录 |
| GET | `/api/auth/me` | 获取当前用户信息 |
| GET | `/api/tasks` | 任务列表（支持 status 筛选） |
| POST | `/api/tasks` | 创建任务 |
| GET | `/api/tasks/{id}` | 任务详情 |
| PUT | `/api/tasks/{id}` | 更新任务 |
| DELETE | `/api/tasks/{id}` | 删除任务 |
| POST | `/api/tasks/breakdown` | AI 拆解任务 |
| POST | `/api/tasks/plan` | AI 生成分阶段计划 |
| GET | `/api/deadlines` | Deadline 列表 |
| POST | `/api/deadlines` | 创建 Deadline |
| PUT | `/api/deadlines/{id}` | 更新 Deadline |
| DELETE | `/api/deadlines/{id}` | 删除 Deadline |
| GET | `/api/deadlines/upcoming` | 即将到期的 Deadline |
| POST | `/api/chat` | 发送 AI 对话 |
| GET | `/api/chat/history` | 聊天历史 |
| GET | `/api/calendar` | 月度日历数据 |
| GET/PUT | `/api/reminders/preferences` | 当前用户提醒偏好 |
| GET | `/api/reminders/history` | 当前用户提醒与投递历史 |
| GET | `/api/reminder-role-cards` | 可选择的提醒角色卡 |
| GET | `/api/reminder-role-cards/{id}` | 角色卡详情 |
| POST/PATCH | `/api/admin/reminder-role-cards` | 管理员维护全局角色卡 |
| POST | `/api/admin/reminders/run` | 管理员 dry-run 或幂等手动执行 |

### 注册邮箱验证流程

1. 前端向 `POST /api/auth/verification-codes` 提交邮箱。响应不会透露邮箱是否已经注册。
2. 用户收到 6 位验证码后，向 `POST /api/auth/verification-codes/verify` 提交邮箱和验证码。
3. 验证成功会返回短期、一次性的 `verification_token`。
4. 调用 `POST /api/auth/register` 时必须同时提交用户名、邮箱、密码和 `verification_token`。凭证必须属于同一邮箱，且会与用户创建在同一事务中消费。

验证码和注册凭证只以摘要形式写入数据库。验证码默认 10 分钟过期、最多错误 5 次；发送请求同时受邮箱冷却、邮箱小时上限和 IP 小时上限保护。

示例注册请求：

```json
{
  "username": "student",
  "email": "student@example.com",
  "password": "secure123",
  "verification_token": "verify-endpoint-returned-token"
}
```

## 测试

后端自动化测试使用 SQLite 与假邮件发送器，不需要 MySQL 或真实 SMTP：

```bash
backend/.venv/bin/python -m unittest discover -s backend/tests -v
```

前端回归检查：

```bash
cd frontend
npm run build
```

这些检查不能证明真实 SMTP 认证、邮件投递或收件箱接收。完整验收还必须按照 [邮箱验证分层验收清单](docs/ai-development/email-verification-acceptance.md) 完成一次真实收信和注册。

## 后端日历提醒 Worker

提醒不在 FastAPI/Uvicorn 进程内自动启动。生产和本地联调均运行独立 Worker：

```bash
# 单次扫描，适合 cron、调试和验收
cd backend
.venv/bin/python reminder_worker.py --once

# 常驻进程，每 60 秒扫描一次用户本地 09:00 窗口和待重试投递
.venv/bin/python reminder_worker.py
```

运行真实 provider 验收前先执行只读 readiness：

```bash
cd backend
.venv/bin/python check_reminder_readiness.py
```

从早期提醒开发表升级时，依次执行 `backend/migrate_reminder_delivery_status.sql`（SMTP 崩溃保护与投递租约）和 `backend/migrate_reminder_role_card_scope.sql`（角色卡全局/私有边界）；全新数据库的 `init_db.sql` 已包含这些字段。

提醒覆盖未完成的顶层 todo、流程子任务和 Deadline，并在 D-2、D-1、D0、D+1、D+3、D+7 合并为每天每用户一份 digest。LLM 只生成标题和 1–2 句开场，后端确定性附加完整项目列表；同一内容独立写入聊天和邮件。

QQ Mail 可使用 `smtp.qq.com` 及服务商当前支持的 TLS 端口/模式。常见配置为 465 + SSL：

```dotenv
SMTP_HOST=smtp.qq.com
SMTP_PORT=465
SMTP_USERNAME=your-account@qq.com
SMTP_PASSWORD=从运行时 secret 注入的授权码
SMTP_FROM_EMAIL=your-account@qq.com
SMTP_USE_STARTTLS=false
SMTP_USE_SSL=true
APP_BASE_URL=https://your-app.example
```

账号和授权码只能写入未跟踪的 `backend/.env` 或部署平台 secret store。详细后端契约和未来前端接入字段见 [提醒后端与前端对接说明](docs/ai-development/reminder-backend.md)。

---

## 常见问题

### MySQL 连接失败

确认 MySQL 服务已启动，用户密码正确，且已执行 `init_db.sql` 建库建表。

### AI 对话无响应

检查 `ARK_API_KEY` 是否已正确配置。如果两个 AI Key 都没填，系统会返回 Mock 回复（模板回复）。

### 注册验证码无法发送

- 页面显示“无法连接服务器”：请求没有取得 HTTP 响应。确认后端监听 `127.0.0.1:8000`，再检查 Vite 代理目标。
- 页面显示“邮箱验证码服务暂时不可用”：后端可达但返回 HTTP 503。检查 SMTP 主机、端口、TLS/SSL、发件地址及账号凭据。
- SMTP 提交成功但未收到：等待片刻并检查垃圾邮件/推广分类，再查看邮件服务商的非敏感投递日志。
- 测试邮箱已注册：接口会按防枚举设计返回通用成功响应但不会再发送验证码，应换用一个受控且未注册的地址。

发送失败或网络超时时，后端会使本次验证码失效；修复后可在限流规则允许时重试。先运行 readiness 命令定位故障层，不要在日志或聊天中粘贴密码、验证码或注册凭证。

### 端口被占用

修改启动命令中的端口号即可：

```bash
# 后端换端口
uvicorn main:app --host 0.0.0.0 --port 8001 --reload

# 前端换端口（并同步 vite.config.js 中的代理目标）
# 编辑 frontend/vite.config.js，修改 server.port
```

### Windows 下虚拟环境激活

```powershell
.venv\Scripts\activate
```

如果 PowerShell 报执行策略错误，先运行：

```powershell
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
```
