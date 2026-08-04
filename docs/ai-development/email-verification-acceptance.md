# 注册邮箱验证分层验收清单

本清单用于防止把假邮件发送器或拦截 API 的 UI 测试误报为真实端到端通过。任何凭据、验证码、注册凭证、完整邮件正文和数据库连接串都不得写入验收记录。

## 判定规则

| 验收层 | 证明范围 | 是否能单独证明真实端到端 |
|---|---|---|
| 后端自动化 | 代码、凭证、限流、安全和错误分支；使用 SQLite 与假发送器 | 否 |
| 前端构建 | Vue 代码可生产构建 | 否 |
| 拦截 API 的浏览器测试 | 页面状态、提示、请求顺序、会话与跳转 | 否 |
| Runtime readiness | 服务、代理、表和 SMTP 设置存在 | 否，不能证明认证和投递 |
| 真实 SMTP/收件箱 | Provider 接受、邮箱收到、验证码验证、注册、会话与跳转 | 是 |

只有最后一层成功且其他必需层通过时，整体状态才能写为 `PASS`。真实层未执行、凭据缺失或收件箱不可用时，整体必须写为 `BLOCKED`；执行后失败则写为 `FAIL`。

## 自动化与 UI 门

- [ ] `backend/.venv/bin/python -m compileall -q backend`
- [ ] `backend/.venv/bin/python -m unittest discover -s backend/tests -v`
- [ ] `npm run build`（在 `frontend` 中）
- [ ] 后端停止时显示中文连接提示，不显示原始 `Failed to fetch`
- [ ] HTTP 503 显示邮件服务配置/稍后重试提示
- [ ] HTTP 202 后才显示“6 位邮箱验证码”输入框
- [ ] 拦截测试覆盖错误验证码、重发、修改邮箱、注册请求、会话和跳转
- [ ] 拦截结果明确标记为 `UI-only / intercepted API`

## Runtime readiness 门

同时启动 MySQL、FastAPI 和 Vite 后执行：

```bash
backend/.venv/bin/python backend/check_registration_readiness.py
```

- [ ] Python 依赖 PASS
- [ ] 后端健康 PASS
- [ ] 前端 API 代理 PASS
- [ ] 数据库与验证码表 PASS
- [ ] SMTP 配置 PASS
- [ ] 命令最终输出 `READY`

## 真实 SMTP/收件箱门

使用用户授权的 SMTP 凭据和一个受控、尚未注册的收件地址：

- [ ] 凭据仅存在于被 Git 忽略的 `backend/.env` 或进程环境
- [ ] readiness 全部通过
- [ ] 浏览器提交有效用户名、邮箱、密码和确认密码
- [ ] 请求验证码后出现六位验证码输入框
- [ ] 收件箱收到本次邮件；必要时检查垃圾邮件分类
- [ ] 在浏览器输入收到的验证码
- [ ] 验证接口返回一次性注册凭证且页面完成注册
- [ ] 浏览器保存会话并进入已认证页面
- [ ] 服务器日志、API 响应和验收记录均未暴露验证码或凭据

## 非敏感证据模板

```text
构建/版本：<commit 或本地变更说明>
执行时间：<时区明确的时间>
环境：<local/demo/staging>
邮件服务：<provider 名称；不写账号>
收件域名：<可选；不写完整地址>
自动化门：PASS/FAIL
拦截 UI 门：PASS/FAIL（UI-only）
Readiness 门：PASS/FAIL
真实 SMTP/收件箱门：PASS/FAIL/BLOCKED/NOT RUN
整体状态：PASS/FAIL/BLOCKED
失败阶段与安全摘要：<不得包含密钥、验证码、token 或邮件正文>
```
