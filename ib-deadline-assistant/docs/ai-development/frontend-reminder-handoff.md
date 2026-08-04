# 前端交接：日历提醒功能（后端已完成，前端待实现）

**适用代码基线：** `1283099`
**目标读者：** Vue 3 / Vuetify 前端开发人员
**接口前缀：** `/api`（Vite 开发环境已代理到 FastAPI）
**认证：** 所有本文接口均需登录，并沿用现有 `Authorization: Bearer <token>` 请求方式。

## 1. 本次需要开发什么

后端的日历提醒能力已经完成，但前端尚未提供设置和历史入口。建议实现以下四块：

1. **提醒设置页或设置抽屉**：总开关、语言、时区、邮件/站内聊天渠道、角色卡选择。
2. **角色卡选择器与详情弹窗**：展示三个内置角色卡，并允许用户选择其中之一。
3. **提醒历史页**：展示每日 digest、命中事项和每个渠道的投递状态。
4. **聊天中的提醒呈现**：识别后端写入的提醒消息，增加“日程提醒”标识和“查看详情”入口。

注册邮箱验证码页面已经实现，**无需重复开发**。本期也不需要做角色卡自建、SillyTavern 导入、短信或第三方软件连接器。

## 2. 产品规则（前端不可改写）

- 只提醒未完成的顶层 todo、流程子任务和 Deadline。
- 基础提醒档位固定包含 `D-2、D-1、D0、D+1、D+3、D+7`。用户可在此基础上**追加** `D+2` 至 `D+365` 的整数天数；不可删除或修改基础档位，不支持自定义 D-N（截止日前）档位。
- 系统以用户时区的本地上午 09:00 为判断窗口；前端只负责保存时区，不自行计算或触发提醒。
- 每位用户每天会将命中事项合并成一份提醒 digest。
- 邮件和站内聊天是独立渠道；关闭邮件不应关闭站内聊天，反之亦然。
- 文案语言由 `language` 决定；角色卡只影响语气，不影响语言和提醒规则。
- 后端保存的提醒正文已经包含完整事项列表和 `/chat` 链接；前端应原样展示正文，不自行改写或让 LLM 再生成。

## 3. 建议信息架构与路由

可以在现有侧栏/个人设置中新增：

```text
设置
└─ 提醒设置 (/settings/reminders)       [新增]

提醒中心 (/reminders)                   [新增，可放在侧栏]
└─ 提醒历史

AI 聊天 (/chat)                         [已有，增强提醒消息样式]
```

如果产品暂时不希望新增两个独立路由，可将“提醒设置”放入个人设置页，将“提醒历史”做成该页的第二个 tab；接口契约不变。

## 4. 页面一：提醒设置

### 4.1 首次加载

并行请求：

```http
GET /api/reminders/preferences
GET /api/reminder-role-cards
```

`GET /api/reminders/preferences` 响应示例：

```json
{
  "enabled": true,
  "language": "zh-CN",
  "timezone": "Asia/Shanghai",
  "cadence_offsets": [2, 1, 0, -1, -2, -3, -7, -30],
  "email_enabled": true,
  "chat_enabled": true,
  "role_card": {
    "id": 1,
    "slug": "friendly-warm-guy",
    "name": "友好暖男",
    "description": "温和、可靠的提醒风格",
    "personality": "关怀且有分寸",
    "speaking_style": "简洁、友善",
    "creator": "IB Deadline Assistant",
    "version": "1.0",
    "is_builtin": true
  }
}
```

### 4.2 建议 UI 字段

| 区块 | 控件 | 字段 | 交互规则 |
|---|---|---|---|
| 总开关 | `v-switch` | `enabled` | 关闭时禁用其他提醒控件，但保留其当前值；保存后 Worker 不再为该用户生成新提醒。|
| 提醒语言 | `v-select` | `language` | MVP 可提供“简体中文 `zh-CN`、繁體中文 `zh-TW`、English `en`”；允许未来扩展 BCP 47 语言标识。|
| 时区 | 可搜索 `v-autocomplete` | `timezone` | 传 IANA 名称，如 `Asia/Shanghai`、`America/Los_Angeles`；不得传 GMT 文本或 UTC 偏移字符串。|
| 提醒时间 | 只读说明 | 无 | 显示“系统将在当地时间上午 09:00 后发送”，不要做时间选择器。|
| 提醒节点 | 基础 chips + 自定义 chips | `cadence_offsets` | 基础 `D-2 / D-1 / 当天 / D+1 / D+3 / D+7` 永远展示且不可删；允许新增、删除自定义的 `D+2` 至 `D+365`。|
| 邮件提醒 | `v-switch` | `email_enabled` | 只影响邮件；建议说明“需配置邮件服务”。|
| 站内聊天提醒 | `v-switch` | `chat_enabled` | 只影响聊天消息。|
| 提醒语气 | 卡片选择器 | `role_card_id` | 打开角色卡弹窗选择；无选择时传 `null` 以恢复默认卡。|

### 4.3 保存

使用部分更新；只有用户改动的字段才发送。例如仅关闭邮件：

```http
PUT /api/reminders/preferences
Content-Type: application/json

{"email_enabled": false}
```

选择角色卡：

```json
{"role_card_id": 2}
```

新增逾期第 2 天和第 30 天提醒（必须传完整集合）：

```json
{"cadence_offsets":[2,1,0,-1,-2,-3,-7,-30]}
```

编码约定：正数表示截止日前（`2` 即 D-2），`0` 为 D0，负数表示逾期后（`-30` 即 D+30）。

恢复默认角色卡：

```json
{"role_card_id": null}
```

成功后以后端返回的完整 preferences 覆盖本地状态，并提示“提醒设置已保存”。不要乐观地假定保存成功。

### 4.4 错误处理

| 状态 | 前端处理 |
|---|---|
| `401` | 复用现有登录失效处理。|
| `422` | 展示 `detail`：例如时区非法、语言格式非法、未保留基础档位、D+N 超出 2–365 范围或角色卡不可用。|
| 网络错误 | 展示“无法保存提醒设置，请检查网络后重试”。|

前端可辅助提示，但保存时必须以后端校验为准：请求需传完整集合，且不可移除基础档位。不得把任意文本、`0`、正数或小于 `-365` 的值作为自定义 D+N 发送。

## 5. 页面二：角色卡选择器

### 5.1 列表与详情接口

```http
GET /api/reminder-role-cards
GET /api/reminder-role-cards/{id}
```

列表仅返回当前用户可选的、启用的全局角色卡。当前有三张：

| slug | 建议显示名 | 视觉/文案方向 |
|---|---|---|
| `friendly-warm-guy` | 友好暖男 | 温和、有分寸、鼓励式 |
| `tech-geek` | 技术宅 | 清晰、结构化、效率导向 |
| `sweet-high-school-girl` | 高中甜美少女 | 轻快、积极、友善 |

建议使用单选卡片，每张展示 `name`、`description` 与选中状态；点击“查看示例/详情”后再请求详情接口，展示 `personality`、`speaking_style` 和 `example_messages`。

### 5.2 本期边界

- 不提供新增、编辑、停用角色卡 UI。
- 不实现 SillyTavern 角色卡 JSON/PNG 导入。
- 不把 `system_prompt` 当作可编辑/可执行内容；仅管理员 API 可维护全局卡，普通用户界面不能调用管理员 API。
- 不渲染 `extensions` 中未知的 HTML、脚本或宏；使用纯文本安全呈现。

## 6. 页面三：提醒历史

### 6.1 接口

```http
GET /api/reminders/history?limit=20&offset=0
```

响应示例：

```json
{
  "items": [
    {
      "id": 42,
      "local_date": "2026-08-05",
      "subject": "日程提醒：2 个项目需要关注",
      "body_text": "……",
      "generation_mode": "llm",
      "role_card_id": 1,
      "item_snapshot": [
        {
          "item_type": "task",
          "item_id": 99,
          "title": "准备答辩",
          "due_date": "2026-08-07",
          "cadence_label": "D-2",
          "priority": "high",
          "subject": "毕业设计",
          "progress": 20
        }
      ],
      "created_at": "2026-08-05T01:00:00",
      "deliveries": [
        {
          "channel": "chat",
          "status": "delivered",
          "attempt_count": 1,
          "last_error_code": null,
          "delivered_at": "2026-08-05T01:00:01"
        },
        {
          "channel": "email",
          "status": "retryable",
          "attempt_count": 1,
          "last_error_code": "smtp_transient_failure",
          "delivered_at": null
        }
      ]
    }
  ],
  "limit": 20,
  "offset": 0
}
```

### 6.2 建议呈现

- 使用按创建时间倒序的卡片/时间线；先展示 `subject`、`local_date`、生成方式和渠道状态。
- 卡片展开后显示 `body_text` 与 `item_snapshot` 的事项列表；`item_type` 建议映射为“任务 / 子任务 / Deadline”。
- 状态 chip 映射：

| 后端状态 | 建议 UI | 含义 |
|---|---|---|
| `delivered` | 成功（绿色） | 渠道已投递。|
| `pending` / `attempting` | 处理中（蓝/灰） | 等待或正在投递。|
| `retryable` | 将重试（橙色） | 暂时性故障，Worker 会重试。|
| `failed` | 失败（红色） | 不会自动继续重试。|
| `skipped` | 已跳过（灰色） | 用户关闭了该渠道或不适用。|

- `last_error_code` 只显示为友好文案，例如 `smtp_auth_failed` → “邮件服务认证失败，请联系管理员”；不要展示原始堆栈、SMTP 账号或技术异常。
- 分页用 `limit` 与 `offset`；首次 `limit=20`，加载更多时 `offset += 当前返回数量`，返回为空时停止。

### 6.3 空状态

显示：“暂时没有提醒记录。创建一个有截止日期的未完成事项后，系统会在提醒窗口内发送通知。”并提供跳转到任务/日历的按钮。

## 7. 页面四：聊天中的提醒消息

提醒会以普通 `assistant` 消息写入标题为“日程提醒”的会话。现有 `/api/chat/history` 的消息响应新增可选字段：

```json
{
  "id": 123,
  "conversation_id": 8,
  "role": "assistant",
  "content": "提醒正文……",
  "metadata": {
    "source": "reminder",
    "digest_id": 42,
    "role_card_id": 1,
    "items": [
      {"item_type": "task", "item_id": 99, "due_date": "2026-08-07"}
    ]
  }
}
```

### 实现要求

- 若 `metadata?.source === 'reminder'`，在消息气泡顶部加“日程提醒”chip/图标。
- 保持 `content` 原样显示；它已包含完整事项列表与聊天链接。
- 可增加“查看提醒详情”按钮，跳转 `/reminders`；不需要、也不应根据 `items` 在前端直接读取或修改任务。
- `metadata` 可能不存在，所有已有聊天消息必须保持原有渲染逻辑。
- 不要信任/执行 metadata 中的任意 URL 或未知字段；该字段只用于显示提醒来源和导航。

## 8. 管理员接口（默认不做普通用户界面）

后端还提供管理员接口，供受控运营后台或联调用：

```text
POST  /api/admin/reminder-role-cards
PATCH /api/admin/reminder-role-cards/{id}
POST  /api/admin/reminders/run
```

`/api/admin/reminders/run` 可接受：

```json
{
  "evaluation_time": "2026-08-05T01:00:00Z",
  "user_id": 123,
  "deliver": false
}
```

仅管理员可调用；`deliver=false` 是安全 dry-run，`deliver=true` 可能发送真实邮件。普通用户端不得暴露该按钮。若未来实现管理员后台，必须在 UI 上明确标注投递风险并二次确认。

## 9. 推荐实现顺序

1. 增加 `src/services/reminders.js`（或现有 API 层）统一封装上述请求，并复用现有 token 注入与 401 处理。
2. 实现提醒设置页：读取 → 表单编辑 → 部分 `PUT` 保存。
3. 实现角色卡弹窗和详情展示。
4. 实现提醒历史列表、展开详情、分页与状态映射。
5. 增强 ChatView / AgentDrawer 的提醒消息 chip 与“查看详情”导航。
6. 为加载、空状态、422、网络失败和登录过期补齐 UI 测试。

## 10. 联调验收清单

- [ ] 已登录用户可读取默认提醒偏好。
- [ ] 关闭并重新开启邮件/聊天渠道后刷新页面，状态保持一致。
- [ ] 选择任一内置角色卡后刷新，选中状态保持一致。
- [ ] 非法时区或不可用角色卡能够展示后端 422 错误。
- [ ] 历史页能显示 digest、事项、邮件和聊天的独立状态。
- [ ] `metadata` 缺失时普通聊天消息不受影响。
- [ ] `source=reminder` 的聊天消息带有提醒标识，并可跳转提醒历史。
- [ ] 不存在角色卡创建、导入或手动投递的普通用户入口；提醒档位入口仅允许追加/删除自定义 D+2 至 D+365，基础档位不可编辑。

## 11. 与后端沟通时的注意事项

- 语言传 BCP 47 标识（如 `zh-CN`），时区传 IANA 名称（如 `Asia/Shanghai`）。
- 当前提醒档位是服务端强约束：必须保留 D-2、D-1、D0、D+1、D+3、D+7；仅可追加 D+2 至 D+365 的整数天数。
- 邮件成功与否不影响聊天提醒；历史状态必须按渠道分别展示。
- 不要把 SMTP 配置、授权码、验证码、LLM key、完整内部错误带到前端或日志。
- 角色卡文本是展示内容，不是脚本或 HTML；始终按纯文本渲染。
