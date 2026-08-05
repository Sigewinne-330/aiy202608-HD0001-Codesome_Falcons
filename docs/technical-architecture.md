# IBuddy 技术架构文档

> AIY 黑客松 2026 深圳站 · 团队 Codesome Falcons (HD0001)

---

## 目录

1. [系统总览](#1-系统总览)
2. [整体架构](#2-整体架构)
3. [后端架构](#3-后端架构)
4. [前端架构](#4-前端架构)
5. [数据库设计](#5-数据库设计)
6. [AI Agent 引擎](#6-ai-agent-引擎)
7. [提醒系统](#7-提醒系统)
8. [日程负载均衡](#8-日程负载均衡)
9. [积分计费系统](#9-积分计费系统)
10. [部署架构](#10-部署架构)
11. [API 设计概览](#11-api-设计概览)
12. [安全设计](#12-安全设计)

---

## 1. 系统总览

IBuddy 是一个面向 IB 学生的 AI 驱动长周期任务规划助手，核心能力包括：

- **多模态 DDL 捕获**：通过 Web Chat UI 接收文字和图片输入，AI 自动识别任务和截止日期
- **智能任务拆解**：从 DDL 逆向推导，生成分阶段子任务和执行计划
- **全模态日程管理**：Todo / Process 双模式任务 + 月历视图 + 碰撞检测
- **幽默催更引擎**：多角色卡 AI 提醒 + 多通道投递（站内 + 邮件）
- **日程负载均衡**：预检拦截 + 多策略排期 + 一键应用 / 撤销

系统采用前后端分离架构，后端基于 FastAPI，前端基于 Vue 3 + Vuetify 3，通过 Docker Compose 三容器部署。

---

## 2. 整体架构

```
┌─────────────────────────────────────────────────────────────────┐
│                         Nginx (Port 80)                         │
│                                                                 │
│  ┌─────────────────────┐    ┌──────────────────────────────┐   │
│  │   静态资源服务        │    │  反向代理 (/api/*, /uploads/*)  │   │
│  │   Vue SPA (dist/)    │    │  → backend:8000               │   │
│  │   + SPA fallback     │    │  SSE 代理 (proxy_buffering    │   │
│  │   缓存: 1y immutable │    │   off, read_timeout 600s)     │   │
│  └─────────────────────┘    └──────────────┬───────────────┘   │
└──────────────────────────────────────────────┼──────────────────┘
                                               │
┌──────────────────────────────────────────────┼──────────────────┐
│                        FastAPI (Port 8000)   │                  │
│                                              ▼                  │
│  ┌───────────────────────────────────────────────────────────┐ │
│  │                    8 Router Modules                        │ │
│  │  auth │ tasks │ deadlines │ chat │ calendar │ billing │    │ │
│  │  reminders │ scheduling                                   │ │
│  └──────────────────────────┬────────────────────────────────┘ │
│                             │                                   │
│  ┌──────────────────────────┼────────────────────────────────┐ │
│  │                    Service Layer                           │ │
│  │  ai_service │ auth │ billing │ email │ task_tools │        │ │
│  │  scheduling_* │ reminder_* │ knowledge_base               │ │
│  └──────────────────────────┬────────────────────────────────┘ │
│                             │                                   │
│  ┌──────────────────────────┼────────────────────────────────┐ │
│  │              Models (SQLAlchemy ORM)                       │ │
│  │  20 张业务表 + 启动自动迁移                                 │ │
│  └──────────────────────────┬────────────────────────────────┘ │
└──────────────────────────────┼──────────────────────────────────┘
                               │
┌──────────────────────────────┼──────────────────────────────────┐
│                MySQL 8.0 (Port 3306)                            │
│  utf8mb4 / pool_size=10 / max_overflow=20 / pool_pre_ping      │
└─────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────┐
│          Reminder Worker (独立进程, APScheduler)                 │
│  60s 间隔扫描 → 生成 LLM 催更 → 双通道投递 (站内 + SMTP)        │
│  + 每日一次 schedule load 分析                                   │
└─────────────────────────────────────────────────────────────────┘
```

### 核心数据流

```
用户输入 (文字/图片)
      │
      ▼
┌──────────────┐    ┌─────────────────┐    ┌──────────────────┐
│  Chat Router  │───▶│  AI Service     │───▶│  Doubao /        │
│  (SSE Stream) │    │  (multi-engine) │    │  DeepSeek        │
└──────┬───────┘    └───────┬─────────┘    └──────────────────┘
       │                    │
       │ tool_calls         │ function results
       ▼                    ▼
┌──────────────┐    ┌──────────────────┐
│  Tool        │───▶│  Database        │
│  Dispatch    │    │  (CRUD + KB)     │
└──────────────┘    └──────────────────┘
       │
       │ final text
       ▼
┌──────────────────────────────────────┐
│  SSE Push → Frontend Render          │
│  + notifyTasksChanged (CustomEvent)  │
└──────────────────────────────────────┘
```

---

## 3. 后端架构

### 3.1 技术栈

| 组件 | 选型 | 版本 |
|------|------|------|
| Web 框架 | FastAPI | 0.115.6 |
| ASGI 服务器 | Uvicorn | 0.34.0 |
| ORM | SQLAlchemy | 2.0.36 |
| 数据库驱动 | PyMySQL | 1.1.1 |
| 认证 | python-jose (JWT) + bcrypt | 3.3.0 / 4.2.1 |
| HTTP 客户端 | httpx + openai | 0.28.1 / 1.58.1 |
| 定时任务 | APScheduler | 3.10.4 |
| 数据验证 | Pydantic v2 | ≥2.10.3 |

### 3.2 模块分层

```
backend/
├── main.py              # FastAPI 应用工厂 + 路由挂载
├── config.py            # 环境变量配置 (pydantic-settings)
├── database.py          # 引擎/Session/自动迁移/外键修复
├── reminder_worker.py   # 独立提醒 Worker 入口
├── models/              # ORM 模型层 (20 张表)
│   ├── app_user.py      # 用户表
│   ├── task_new.py       # 任务表 (TaskType/TaskCategory/Priority 枚举)
│   ├── sub_task.py      # 子任务表
│   ├── deadline.py      # 独立截止日表
│   ├── conversation.py  # 对话表
│   ├── chat_message_new.py  # 聊天消息表
│   ├── token_ledger.py  # 积分账本
│   ├── billing_order.py # 充值订单
│   ├── email_verification.py  # 邮箱验证
│   ├── reminder.py      # 提醒系统 (8 张表)
│   └── scheduling.py    # 调度系统 (8 张表)
├── routers/             # HTTP 路由层 (8 个模块)
├── schemas/             # Pydantic 请求/响应 Schema
├── services/            # 业务逻辑层
│   ├── ai_service.py         # 多引擎 LLM 客户端
│   ├── system_prompt.md      # AI 系统提示词
│   ├── task_tools*.py        # 任务工具定义与实现
│   ├── knowledge_base_tools.py  # 知识库检索
│   ├── scheduling_tools*.py  # 调度工具定义与实现
│   ├── schedule_*.py         # 调度核心算法
│   ├── reminder_*.py         # 提醒全流程
│   ├── email_service.py      # SMTP 邮件服务
│   └── knowledge_base/       # IB 学科指南 (.md)
└── tests/               # 测试套件
```

### 3.3 路由模块一览

| Router | 前缀 | 核心功能 |
|--------|------|---------|
| `auth` | `/api/auth` | 注册(邮箱验证)、登录(JWT)、用户信息 |
| `tasks` | `/api/tasks` | 任务 CRUD、AI 规划/拆解、子任务管理 |
| `deadlines` | `/api/deadlines` | 截止日 CRUD、碰撞检测 |
| `chat` | `/api/chat` | SSE 流式对话、工具调用循环、会话管理 |
| `calendar` | `/api/calendar` | 月视图日历数据聚合 |
| `billing` | `/api/billing` | 积分余额、充值套餐、账本查询 |
| `reminders` | `/api/reminders` | 提醒偏好、角色卡、历史记录 |
| `scheduling` | `/api/scheduling` | 负载分析、干预、计划创建/应用/撤销 |

### 3.4 数据库启动流程

启动时 `main.py` 按序执行：

1. **文件锁获取**：跨平台非阻塞锁 (`fcntl` / `msvcrt`)，防止多 worker 竞争
2. **`Base.metadata.create_all()`**：创建 ORM 定义的新表
3. **`auto_sync_tables()`**：检测 ORM 模型中的**新增列**，以 `ALTER TABLE ADD COLUMN` 自动追加入库（支持 ENUM/VARCHAR/INT/TEXT/DATETIME/JSON 等类型）
4. **`sync_reminder_user_foreign_keys()`**：将遗留的 `users` 外键引用修复到 `user` 表
5. **`sync_reminder_legacy_foreign_keys()`**：将 `reminder_digests.chat_message_id` 外键从 `chat_history` 修复到 `chat_message`
6. **预置角色卡种子数据**：将内置的提醒角色卡写入 `reminder_role_cards`

该设计做到**代码即 Schema**，开发者只需修改 ORM 模型，启动时自动同步到数据库。

### 3.5 连接池配置

```python
engine = create_engine(
    settings.database_url,
    pool_size=10,       # 核心连接数
    max_overflow=20,    # 峰值溢出连接
    pool_pre_ping=True,  # 连接保活检测
)
```

每次连接建立时，自动执行 `SET time_zone = '+00:00'` 确保 MySQL 会话时区与 Python `utcnow()` 一致。

---

## 4. 前端架构

### 4.1 技术栈

| 组件 | 选型 | 版本 |
|------|------|------|
| 框架 | Vue 3 (Composition API) | ^3.5.0 |
| 构建工具 | Vite | ^6.0.0 |
| UI 框架 | Vuetify 3 (Material Design 3) | ^3.9.0 |
| 路由 | Vue Router | ^4.5.0 |
| 国际化 | vue-i18n | ^10.0.8 |
| Markdown | markdown-it + KaTeX | ^15.0.0 / ^0.18.1 |
| 图标 | @mdi/font | ^7.4.0 |

### 4.2 目录结构

```
frontend/src/
├── main.js                    # 应用入口 (Vue + Router + Vuetify + i18n)
├── App.vue                    # 根布局 (App Bar + 抽屉 + FAB)
├── plugins/
│   └── vuetify.js             # Vuetify 主题 + 三语 locale 适配
├── router/
│   └── index.js               # 16 条路由 + 全局导航守卫
├── stores/
│   └── auth.js                # 认证状态 (Composition API refs) + API 工具
├── services/
│   ├── agentContext.js         # CustomEvent 跨组件通信 (打开 Agent)
│   ├── imageCompress.js        # 客户端图片压缩 (Canvas + JPEG)
│   ├── reminders.js            # 提醒 API 封装
│   └── taskSync.js             # CustomEvent 任务变更通知
├── i18n/
│   └── index.js                # vue-i18n 配置 (浏览器语言检测)
├── locales/
│   ├── zh-CN.js                # 简体中文
│   ├── zh-TW.js                # 繁體中文
│   ├── en.js                   # English
│   └── progress.js             # 进度模块共享文案
├── components/                 # 可复用组件
│   ├── AgentDrawer.vue         # AI 对话面板 (SSE 流式 + Markdown + 图片)
│   ├── CalendarPanel.vue       # 月历网格视图
│   ├── TaskDrawer.vue          # 左侧任务抽屉
│   ├── SettingsDialog.vue      # 设置弹窗 (5 个 Tab)
│   ├── TimelineManager.vue     # 进度时间线
│   ├── ReminderSettingsPanel.vue
│   ├── ReminderHistoryList.vue
│   ├── ReminderOffsetsEditor.vue
│   └── RoleCardPicker.vue
└── views/                      # 页面级组件
    ├── LandingView.vue         # 营销首页 (公开)
    ├── LoginView.vue           # 登录
    ├── RegisterView.vue        # 注册 (邮箱验证)
    ├── CalendarView.vue        # 主日历工作台
    ├── ChatView.vue            # 独立对话页 (含会话侧栏)
    ├── TasksView.vue           # 任务管理
    ├── TaskPlanView.vue        # AI 任务规划
    ├── DeadlinesView.vue       # 截止日管理
    ├── UrgentView.vue          # 紧急项队列
    ├── ProgressView.vue        # 进度与风险追踪
    ├── DashboardView.vue       # 仪表盘
    ├── BillingView.vue         # 积分与充值
    └── RemindersView.vue       # 提醒中心
```

### 4.3 状态管理方案

**不使用 Pinia**。采用 Vue 3 Composition API 的模块级 `ref()` + 工厂函数模式：

```javascript
// stores/auth.js
const token = ref(localStorage.getItem('ib_auth_token') || '')
const user = ref(loadUser())
const isAuthenticated = computed(() => !!token.value)

export function useAuth() {
  return { token, user, isAuthenticated, login, logout, ... }
}
```

跨组件通信使用 **CustomEvent 事件总线**：

```javascript
// services/taskSync.js
window.dispatchEvent(new CustomEvent('ibuddy:tasks-changed'))
// 其他组件监听
window.addEventListener('ibuddy:tasks-changed', handler)
```

该设计满足以下场景：
- AI 对话创建/修改任务后 → 日历视图自动刷新
- 从进度页面点击任务 → 自动打开 Agent 并传入上下文

### 4.4 路由设计

| 路径 | 页面 | 认证 | 说明 |
|------|------|------|------|
| `/` | LandingView | 公开 | 营销首页 |
| `/login` | LoginView | 公开 | 已登录重定向 `/` |
| `/register` | RegisterView | 公开 | 已登录重定向 `/` |
| `/plan` | TaskPlanView | 需登录 | AI 任务规划 |
| `/chat` | ChatView | 需登录 | 全屏对话 |
| `/tasks` | TasksView | 需登录 | 任务管理 |
| `/deadlines` | DeadlinesView | 需登录 | 截止日管理 |
| `/calendar` | CalendarView | 需登录 | 主日历工作台 |
| `/urgent` | UrgentView | 需登录 | 紧急项 |
| `/progress` | ProgressView | 需登录 | 进度概览 |
| `/progress/:category` | ProgressView | 需登录 | 分类钻取 |
| `/progress/:category/:taskId` | ProgressView | 需登录 | 任务时间线 |
| `/dashboard` | DashboardView | 需登录 | 仪表盘 |
| `/billing` | BillingView | 需登录 | 积分管理 |
| `/reminders` | RemindersView | 需登录 | 提醒中心 |

**导航守卫**：
- `beforeEach`：未认证访问需登录页面 → 重定向 `/login?redirect=xxx`
- `afterEach`：根据 `meta.titleKey` 动态设置 `document.title`

### 4.5 国际化 (i18n)

- **3 种语言**：简体中文 (zh-CN)、繁體中文 (zh-TW)、English (en)
- **检测优先级**：`localStorage('ibuddy_locale')` → `navigator.language` → `zh-CN`
- **Vuetify 联动**：通过 `watch` 监听 `i18n.global.locale`，同步更新 `vuetify.locale.current`，使 Vuetify 内置组件（日期选择器等）自动切换语言
- **特殊处理**：zh-TW/HK/Hant → 映射到 Vuetify 的 `zhHant` locale

---

## 5. 数据库设计

### 5.1 表结构全景

系统共有 **20 张业务表**，按功能域划分：

#### 核心用户

| 表名 | 模型 | 关键字段 |
|------|------|---------|
| `user` | AppUser | id, username, nickname, password(bcrypt), email, grade, balance, is_admin |

#### 任务管理

| 表名 | 模型 | 关键字段 | 关系 |
|------|------|---------|------|
| `task` | Task | id, user_id, task_type(todo/process), title, deadline, category(IA/EE/TOK/CAS), priority, estimated_hours, status, energy_intensity, schedule_version | FK → user |
| `sub_task` | SubTask | id, task_id, name, notice_time, level, status, estimated_hours, energy_intensity, schedule_version | FK → task |
| `deadlines` | Deadline | id, user_id, title, due_date, priority, status, estimated_hours | FK → user |

#### 对话与消息

| 表名 | 模型 | 关键字段 |
|------|------|---------|
| `conversation` | Conversation | id, user_id, title |
| `chat_message` | ChatMessage | id, user_id, conversation_id, role(user/assistant/system), content, token, extra(JSON) |

#### 积分计费

| 表名 | 模型 | 关键字段 |
|------|------|---------|
| `token_ledger` | TokenLedger | id, user_id, change_type(consume/recharge/gift), change_amount, balance_after, ref_id, ref_type |
| `billing_orders` | BillingOrder | id, user_id, plan_code, amount, credits, status(pending/paid) |

#### 邮箱验证

| 表名 | 模型 | 关键字段 |
|------|------|---------|
| `email_verifications` | EmailVerification | id, email, code_salt, code_digest, registration_token_digest, expires_at, verified_at |

#### 提醒系统 (8 张)

| 表名 | 用途 |
|------|------|
| `reminder_role_cards` | AI 催更人设定义 (slug, personality, system_prompt) |
| `reminder_preferences` | 用户提醒设置 (cadence_offsets, daily_dispatch_time, channels) |
| `reminder_occurrences` | 按 cadence 偏移生成的提醒事件 |
| `reminder_digests` | LLM 生成/模板降级的每日摘要 |
| `reminder_deliveries` | 各通道投递状态追踪 |
| `task_reminder_notifications` | 任务级别 deadline 通知 |
| `task_reminder_deliveries` | 任务通知投递状态 |
| `llm_usage_records` | LLM 调用审计日志 |

#### 调度系统 (8 张)

| 表名 | 用途 |
|------|------|
| `scheduling_preferences` | 用户调度参数 (capacity_hours=4h, reserve_ratio=0.20) |
| `schedule_capacity_overrides` | 单日容量例外 |
| `schedule_item_dependencies` | 任务依赖关系 |
| `schedule_allocations` | 任务到日历日期的映射 |
| `schedule_interventions` | 超载干预建议 |
| `schedule_plans` | 完整调度计划 (含版本号) |
| `schedule_plan_items` | 计划中的单项变动详情 |
| `schedule_audit_events` | 调度审计日志 |

### 5.2 枚举设计

```python
# 任务类型
class TaskType(str, enum.Enum):
    todo = "todo"        # 轻量待办，一键勾选
    process = "process"  # 长程流程，时间线 + 里程碑

# 任务分类 (IB 学科)
class TaskCategory(str, enum.Enum):
    IA = "IA"    # Internal Assessment
    EE = "EE"    # Extended Essay
    TOK = "TOK"  # Theory of Knowledge
    CAS = "CAS"  # Creativity, Activity, Service

# 优先级
class Priority(str, enum.Enum):
    low = "low"
    medium = "medium"
    high = "high"
    urgent = "urgent"

# 状态
class TaskStatus(str, enum.Enum):
    not_started = "not_started"
    in_progress = "in_progress"
    completed = "completed"
    overdue = "overdue"
```

---

## 6. AI Agent 引擎

### 6.1 多引擎架构

```
         用户请求
            │
            ▼
    ┌──────────────┐
    │  ai_service   │
    │  engine       │
    │  selector     │
    └──┬────────┬──┘
       │        │
       ▼        ▼
   ┌──────┐ ┌──────────┐
   │ Ark  │ │ DeepSeek │
   │(主)  │ │ (降级)   │
   └──┬───┘ └────┬─────┘
      │          │
      └────┬─────┘
           ▼
      OpenAI-compatible client
```

- **主引擎**：Doubao Seed 2.1 Pro，通过火山引擎 Ark API 调用
- **备用引擎**：DeepSeek Chat，主引擎不可用时自动切换
- **视觉模型**：独立的 `ARK_VISION_MODEL`，处理图片输入
- **统一接口**：两个引擎均通过 OpenAI 兼容的 `openai` 库 (v1.58.1) 调用

### 6.2 工具调用循环 (Tool-Calling Loop)

```
┌──────────────────────────────────────────────────────────┐
│  POST /api/chat/stream                                   │
│                                                          │
│  1. 加载系统提示词 (system_prompt.md + 角色卡增强)         │
│  2. 加载历史消息 (最近 20 条)                              │
│  3. 构建消息列表: system + history + user                 │
│                                                          │
│  ┌─────────────────────────────────────┐                 │
│  │  Tool-Calling Loop (最多 30 轮)      │                 │
│  │                                     │                 │
│  │  ① 调用 AI (with tools)             │                 │
│  │  ② 判断 finish_reason:              │                 │
│  │     ├─ "stop" → 流式输出最终文本    │                 │
│  │     └─ "tool_calls" →              │                 │
│  │         ③ 提取 tool_name + args     │                 │
│  │         ④ 路由到对应工具:            │                 │
│  │            ├─ create_task → preflight → DB          │
│  │            ├─ update_task → task_tools → DB          │
│  │            ├─ create_subtask → preflight → DB        │
│  │            ├─ list_tasks → DB 查询                   │
│  │            ├─ get_subject_guidelines → 知识库        │
│  │            └─ schedule_* → scheduling_tools          │
│  │         ⑤ 将工具结果追加到消息列表    │                 │
│  │         ⑥ 回到 ① (若未达上限)        │                 │
│  └─────────────────────────────────────┘                 │
│                                                          │
│  5. 保存消息到 chat_message                               │
│  6. 记录 LLM 用量到 llm_usage_records                     │
│  7. 发送 task-changed 通知                                │
└──────────────────────────────────────────────────────────┘
```

### 6.3 16 个可用工具

#### 任务工具 (始终可用)
| 工具名 | 功能 |
|--------|------|
| `create_task` | 创建任务（带 preflight 检查） |
| `list_tasks` | 列出用户所有任务 |
| `update_task` | 更新任务 |
| `delete_task` | 删除任务 |
| `create_subtask` | 创建子任务（带 preflight 检查） |
| `list_subtasks` | 列出任务的子任务 |
| `update_subtask` | 更新子任务 |
| `delete_subtask` | 删除子任务 |
| `get_subject_guidelines` | 检索 IB 学科知识库 |

#### 调度工具 (feature-flagged)
| 工具名 | 功能 |
|--------|------|
| `preflight_create_calendar_item` | 创建前负载检查 |
| `resolve_overload_intervention` | 解决超载干预 |
| `analyze_schedule` | 分析日程负载 |
| `create_schedule_plan` | 创建排期计划 |
| `apply_schedule_plan` | 应用排期计划 |
| `undo_schedule_plan` | 撤销排期计划 |
| `replan_schedule` | 重新排期 |

### 6.4 知识库系统

内置 5 个学科的 IB 规划指南（Markdown 格式）：

```
services/knowledge_base/
├── IB_Chemistry_IA.md      # 化学 IA 规划指南
├── IB_Economics_IA.md      # 经济学 IA 规划指南
├── IB_Physics_IA.md        # 物理 IA 规划指南
├── IB_Extended_Essay.md    # 拓展论文 (EE) 规划指南
└── IB_TOK.md               # 知识论 (TOK) 规划指南
```

- **动态 Schema 生成**：`get_subject_guidelines` 工具的参数枚举从 `knowledge_base/` 目录中的 `.md` 文件名自动生成
- **检索逻辑**：Agent 在用户提及相关学科时自动调用，返回对应的 Markdown 内容作为 AI 上下文

### 6.5 系统提示词策略

AI 被设定为 "IBuddy 规划助手"，核心约束包括：

- **角色边界**：只做任务规划和时间管理，不批改作业、不提供学术反馈
- **日期感知**：每条消息前自动插入当前日期，防止 LLM 的时间偏差
- **双模式判定**：单步提醒任务 (小任务) vs 完整拆解规划 (大任务)，自动选择流程
- **图片理解**：从聊天截图/通知截图中提取任务名和日期，遇到模糊日期会追问确认
- **语言跟随**：用户用什么语言，AI 就用什么语言回复
- **日历感知**：创建任务时自动检查目标日期是否已超载

---

## 7. 提醒系统

### 7.1 架构

```
reminder_worker.py (独立进程)
        │
        ▼
┌───────────────────────┐
│  APScheduler          │
│  BlockingScheduler    │
│  interval: 60s        │
│                       │
│  ┌─────────────────┐  │
│  │ _run_job()       │  │
│  │  ↓               │  │
│  │  Orchestrator    │  │
│  │  .run()          │  │
│  └────────┬────────┘  │
└───────────┼───────────┘
            │
            ▼
┌───────────────────────────────┐
│  ReminderOrchestrator         │
│                               │
│  1. 扫描所有启用提醒的用户     │
│  2. 计算 cadence 偏移：       │
│     D-2, D-1, D0, D+1, D+3,  │
│     D+7 + 自定义偏移          │
│  3. 匹配到期 occurrence       │
│  4. 生成 Digest:              │
│     ├─ LLM 模式 (角色卡风格)  │
│     └─ 模板模式 (降级)        │
│  5. 双通道投递:               │
│     ├─ 站内消息 (chat_message)│
│     └─ 邮件 (SMTP)            │
│  6. 记录投递状态 + 重试       │
└───────────────────────────────┘
```

### 7.2 提醒节奏 (Cadence)

默认 6 个时间节点：
- **D-2**：截止前 2 天
- **D-1**：截止前 1 天
- **D0**：截止当天
- **D+1**：逾期 1 天
- **D+3**：逾期 3 天
- **D+7**：逾期 7 天

用户可追加自定义偏移量（最长 D+365）。

### 7.3 角色卡系统

AI 催更支持三种预设人设：

| 角色卡 | 风格 | 场景 |
|--------|------|------|
| 友好学长 | 温暖鼓励 | "嘿，别忘了明天有个 IA 初稿哦，写完请你喝奶茶~" |
| 技术极客 | 理性硬核 | "[WARNING] Task deadline proximity detected. Recommended action: START NOW." |
| 甜美学妹 | 软萌催促 | "学长/学姐~ 你的 EE 大纲还没交呢，人家帮你记着呢 😊" |

生成失败时自动降级为确定性模板，确保提醒不丢失。

### 7.4 投递机制

- **双通道**：站内消息 (写入 `chat_message` 表，前端展示为特殊提醒气泡) + 邮件 (SMTP via QQ Mail SSL)
- **状态追踪**：每条投递记录在 `reminder_deliveries` 表，含 `attempt_count`、`next_attempt_at`
- **自动重试**：失败后最多重试 3 次

---

## 8. 日程负载均衡

### 8.1 系统架构

```
┌─────────────────────────────────────────────────────┐
│                  SCHEDULING_BALANCER                 │
│               (env: ENABLED=true/false)             │
├─────────────────────────────────────────────────────┤
│                                                     │
│  ┌──────────────┐   ┌──────────────┐               │
│  │ Preflight     │   │ Intervention │               │
│  │ (创建前拦截)   │──▶│ (超载干预)    │               │
│  │              │   │              │               │
│  │ 阈值: 单日    │   │ 展示:         │               │
│  │ ≥4 项触发    │   │ - 当前负载    │               │
│  │              │   │ - 建议日期    │               │
│  │              │   │ - 理由编码    │               │
│  └──────────────┘   └──────┬───────┘               │
│                            │                        │
│                            ▼                        │
│  ┌─────────────────────────────────────────────┐   │
│  │            Schedule Plan Lifecycle           │   │
│  │                                             │   │
│  │  create_plan ──▶ apply_plan ──▶ undo/replan │   │
│  │  (预览无副作用)    (原子化写入)   (回滚/重算)  │   │
│  └─────────────────────────────────────────────┘   │
│                                                     │
│  ┌─────────────────────────────────────────────┐   │
│  │           Mutation Hooks                     │   │
│  │                                             │   │
│  │  每次 task/subtask/deadline 变更后:          │   │
│  │  • analyze_after_mutation()                 │   │
│  │  • 检测相关日期是否超载                      │   │
│  │  • 触发自动重新分析                          │   │
│  └─────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────┘
```

### 8.2 算法参数

算法名称：`energy-waterline-v1`

```python
# 默认参数 (scheduling_preferences 表)
default_capacity_hours = 4        # 每日默认容量 (小时)
reserve_ratio = 0.20              # 预留缓冲比例 (20%)
balanced_target_ratio = 0.85      # 均衡策略目标利用率
min_chunk_hours = 0.5             # 最小任务块
max_chunk_hours = 2.0             # 最大任务块
max_major_items_per_date = 3      # 单日最大主要项数
same_kind_soft_limit = 2          # 同类别软上限

# 干预阈值: 第 4 项进入时触发
```

### 8.3 三种排期策略

| 策略 | 目标利用率 | 特点 |
|------|-----------|------|
| Balanced (均衡) | 85% | 默认策略，平衡负载与缓冲 |
| Conservative (保守) | 70% | 最大缓冲，最低风险 |
| Sprint (冲刺) | 100% | 充分利用容量，最小缓冲 |

### 8.4 计划生命周期

1. **Preflight**：创建带日期的任务/子任务前，检查目标日期是否超载
2. **Intervention**：若超载，生成带排名的建议日期 + 理由编码
3. **Resolve**：用户选择 `keep_original` / `accept_recommendation` / `choose_date`
4. **Create Plan**：生成无副作用的排期预览，展示变更对照
5. **Apply Plan**：原子化写入 `schedule_allocations`，校验 `input_revision` 版本号
6. **Undo/Replan**：回滚或重新计算

### 8.5 乐观并发控制

每个 task/subtask/deadline 都有 `schedule_version` 字段，每次修改递增。Apply Plan 时校验 `input_revision == current_version`，防止并发编辑冲突。

---

## 9. 积分计费系统

### 9.1 积分模型

```
1 积分 = 1000 tokens

Token 估算:
  - CJK 字符: 1 token / 字符
  - 其他字符: 0.25 token / 字符

新用户注册: 赠送 10,000 积分
```

### 9.2 当前模式

```python
UNLIMITED_TOKENS = True  # 开发阶段，不实际扣费
```

系统记录每笔 LLM 调用到 `llm_usage_records` 和 `token_ledger`，但在 `UNLIMITED_TOKENS=True` 时跳过余额检查和扣费，仅展示用量。

### 9.3 充值套餐

| 金额 | 积分 | 单价 |
|------|------|------|
| ¥6 | 600 | ¥0.01/token |
| ¥30 | 3,500 | ¥0.0086/token |
| ¥68 | 8,000 | ¥0.0085/token |
| ¥128 | 18,000 | ¥0.0071/token |

支付流程为模拟实现（`POST /api/billing/orders/{id}/pay`）。

---

## 10. 部署架构

### 10.1 Docker Compose 三容器

```yaml
services:
  mysql:       # MySQL 8.0
    image: mysql:8.0
    volumes: mysql_data + init SQL
    healthcheck: mysqladmin ping

  backend:     # FastAPI (4 workers)
    build: ./backend
    depends_on: mysql (healthy)
    volumes: ./backend:/app (热加载代码)
    env: DB/AI/JWT/SMTP 配置

  frontend:    # Nginx + Vue SPA
    build: ./frontend (multi-stage)
    depends_on: backend
    ports: 80:80
```

### 10.2 前端 Nginx 配置

```
/api/*     → proxy_pass backend:8000
/uploads/* → proxy_pass backend:8000

SSE 支持:
  proxy_buffering off
  proxy_cache off
  proxy_read_timeout 600s

SPA Fallback:
  try_files $uri $uri/ /index.html

静态资源:
  *.js/*.css/*.woff* → 1 年 immutable 缓存
  max_body_size: 20MB (图片上传)
```

### 10.3 部署流程

```
本地代码 → rsync 同步到服务器 → docker compose build → docker compose up -d
```

支持 `--rebuild-backend` 参数在依赖变更时重建后端镜像。

---

## 11. API 设计概览

### 11.1 通用约定

- **认证**：Bearer Token (JWT HS256, 24h 过期)
- **内容类型**：`application/json` (请求), `application/json` / `text/event-stream` (响应)
- **错误格式**：`{ "detail": "错误描述" }` (FastAPI 标准)
- **CORS**：全开放 (`allow_origins=["*"]`)

### 11.2 核心端点

```
认证 (auth)
  POST   /api/auth/register              注册 (邮箱验证)
  POST   /api/auth/login                 登录 (JWT)
  GET    /api/auth/me                    当前用户信息

任务 (tasks)
  GET    /api/tasks                      任务列表 (树形)
  POST   /api/tasks                      创建任务
  PUT    /api/tasks/{id}                 更新任务
  DELETE /api/tasks/{id}                 删除任务
  POST   /api/tasks/plan                 AI 生成阶段计划
  POST   /api/tasks/breakdown            AI 拆解子任务
  POST   /api/tasks/{id}/subtasks        创建子任务

对话 (chat)
  POST   /api/chat/stream                SSE 流式对话 (核心)
  GET    /api/chat/conversations          会话列表
  GET    /api/chat/history               消息历史

日历 (calendar)
  GET    /api/calendar?year=&month=      月视图数据聚合

计费 (billing)
  GET    /api/billing/summary            余额概览
  GET    /api/billing/ledger             积分账本

提醒 (reminders)
  GET    /api/reminders/preferences      提醒偏好
  GET    /api/reminders/history          提醒历史
  GET    /api/reminder-role-cards        角色卡列表

调度 (scheduling)
  POST   /api/scheduling/interventions/preflight   创建前检查
  POST   /api/scheduling/plans                     创建排期计划
  POST   /api/scheduling/plans/{id}/apply          应用计划
```

---

## 12. 安全设计

### 12.1 认证与授权

- **JWT**：HS256 算法，24 小时过期
- **密码哈希**：bcrypt (`bcrypt==4.2.1`)
- **邮箱验证**：验证码加盐哈希存储 (`code_salt + code_digest`)，多层限流保护
- **注册流程**：请求验证码 → 邮箱收码 → 验证 → 拿到 registration_token → 注册

### 12.2 数据库安全

- **连接**：PyMySQL over TCP，环境变量管理密码
- **SQL 注入防护**：全部使用 SQLAlchemy ORM 参数化查询
- **外键约束**：CASCADE 删除确保数据一致性
- **时区一致性**：所有连接强制 `SET time_zone = '+00:00'`

### 12.3 输入验证

- **Pydantic v2**：所有请求体经过 Schema 校验
- **文件上传**：仅限图片格式，客户端 + 服务端双重大小限制
- **速率限制**：邮箱验证码请求实施 IP 级别限流

### 12.4 Feature Flag

```python
SCHEDULING_BALANCER_ENABLED = os.getenv("SCHEDULING_BALANCER_ENABLED", "false").lower() == "true"
```

调度系统可通过环境变量独立开关，未启用时：
- 调度相关路由返回 404
- 调度工具从 AI 工具列表中移除
- 调度相关的数据库表仍可正常读写（不阻塞其他功能）

---

## 附录 A：关键文件索引

| 文件 | 作用 |
|------|------|
| `backend/main.py` | FastAPI 应用工厂，8 个路由挂载，启动自检 |
| `backend/config.py` | 全部环境变量定义 |
| `backend/database.py` | 引擎、Session、自动迁移、外键修复 |
| `backend/reminder_worker.py` | 独立提醒 Worker 入口 |
| `backend/services/ai_service.py` | 多引擎 LLM 客户端 |
| `backend/services/system_prompt.md` | AI 系统提示词 |
| `backend/services/schedule_engine.py` | 调度核心算法 |
| `backend/services/reminder_orchestrator.py` | 提醒全流程编排 |
| `frontend/src/components/AgentDrawer.vue` | AI 对话面板 |
| `frontend/src/router/index.js` | 路由定义 + 导航守卫 |
| `frontend/src/stores/auth.js` | 认证状态 + API 工具 |
| `docker-compose.yml` | 三容器编排 |
| `deploy.sh` | 一键部署脚本 |

## 附录 B：依赖清单

### 后端 (requirements.txt)

```
fastapi==0.115.6          # Web 框架
uvicorn[standard]==0.34.0 # ASGI 服务器
sqlalchemy==2.0.36        # ORM
pymysql==1.1.1            # MySQL 驱动
cryptography==44.0.0      # 加密库
pydantic>=2.10.3,<3       # 数据验证
email-validator>=2.2.0    # 邮箱格式校验
python-jose[cryptography]==3.3.0  # JWT
bcrypt==4.2.1             # 密码哈希
python-multipart==0.0.18  # 文件上传
httpx==0.28.1             # HTTP 客户端
openai==1.58.1            # LLM API 客户端
python-dotenv==1.2.2      # 环境变量
apscheduler==3.10.4       # 定时任务
```

### 前端 (package.json)

```json
{
  "vue": "^3.5.0",
  "vuetify": "^3.9.0",
  "vue-router": "^4.5.0",
  "vue-i18n": "^10.0.8",
  "markdown-it": "^15.0.0",
  "katex": "^0.18.1",
  "@mdi/font": "^7.4.0",
  "vite": "^6.0.0",
  "@vitejs/plugin-vue": "^5.2.0",
  "vite-plugin-vuetify": "^2.1.0"
}
```
