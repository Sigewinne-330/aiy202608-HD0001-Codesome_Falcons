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

编辑 `backend/.env`，至少填写以下两项：

```
# 必填：MySQL 密码
DB_PASSWORD=你的MySQL密码

# 必填：豆包 API Key（从火山引擎控制台获取）
ARK_API_KEY=你的ARK_API_KEY
```

完整环境变量说明见下方 [环境变量](#环境变量)。

### 3. 初始化数据库

```bash
# 用 root 账户创建数据库并建表
mysql -u root -p < backend/init_db.sql
```

该脚本会创建 `ib_assistant` 数据库和以下表：
- `users` — 用户表
- `tasks` — 任务表
- `deadlines` — 截止日期表
- `chat_history` — 聊天历史表

同时预置了一个 demo 用户（用户名：`demo`，密码：`demo123`）。

### 4. 启动后端

```bash
cd backend

# 创建虚拟环境
python3 -m venv venv

# 激活虚拟环境
source venv/bin/activate   # macOS / Linux
# venv\Scripts\activate    # Windows

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

> **AI 引擎说明**：优先使用豆包（Ark），失败后自动降级到 DeepSeek。两个都不配置时使用内置 Mock 回复（仅返回模板回复，功能受限）。

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

---

## 常见问题

### MySQL 连接失败

确认 MySQL 服务已启动，用户密码正确，且已执行 `init_db.sql` 建库建表。

### AI 对话无响应

检查 `ARK_API_KEY` 是否已正确配置。如果两个 AI Key 都没填，系统会返回 Mock 回复（模板回复）。

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
venv\Scripts\activate
```

如果 PowerShell 报执行策略错误，先运行：

```powershell
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
```
