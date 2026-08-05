"""HTML 邮件模板。

设计原则：
- 兼容主流邮箱客户端（QQ 邮箱 / Gmail / Outlook）：只用 table 布局 + 内联样式，
  不使用 flex/grid/外部 CSS/JS/外部图片。
- 所有动态内容必须经过 html.escape()，防止 HTML 注入。
- 发送侧（email_service.send_message）会同时附带纯文本版本
  （multipart/alternative），HTML 仅作为增强展示。
"""

import html

BRAND_NAME = "IBuddy"

_BRAND_COLOR = "#185FA5"
_BRAND_COLOR_LIGHT = "#E6F1FB"
_DANGER_COLOR = "#A32D2D"
_DANGER_COLOR_LIGHT = "#FCEBEB"
_TEXT_PRIMARY = "#1F2933"
_TEXT_SECONDARY = "#6B7280"
_BORDER = "#E5E7EB"
_PAGE_BG = "#F5F7FA"
_CARD_BG = "#FFFFFF"


def brand_name() -> str:
    return BRAND_NAME


def _escape(text: object) -> str:
    return html.escape(str(text), quote=True)


def _text_to_html(text: str) -> str:
    """纯文本转 HTML 片段：逐行转义后，每行渲染为带间距的块级 <div>。

    用 <div> + padding 而非 <br> 或 <p>+margin：条目之间有清晰的分隔感，
    且 Outlook 桌面版对 <p> 的 margin 支持很差，padding 兼容性最好。
    """
    lines = (text or "").replace("\r\n", "\n").replace("\r", "\n").split("\n")
    blocks = []
    for i, line in enumerate(lines):
        is_last = i == len(lines) - 1
        padding = "0" if is_last else "0 0 12px 0"
        content = _escape(line) if line.strip() else "&nbsp;"
        blocks.append(f'<div style="padding:{padding};">{content}</div>')
    return "".join(blocks)


def _wrap(content_html: str) -> str:
    """品牌外壳：页头（产品名）+ 内容卡片 + 页脚。"""
    brand = _escape(brand_name())
    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{brand}</title>
</head>
<body style="margin:0;padding:0;background-color:{_PAGE_BG};">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background-color:{_PAGE_BG};">
<tr><td align="center" style="padding:32px 16px;">
<table role="presentation" width="600" cellpadding="0" cellspacing="0" style="max-width:600px;width:100%;">

<tr><td style="padding:0 8px 16px 8px;">
<span style="font-family:-apple-system,'PingFang SC','Microsoft YaHei',sans-serif;font-size:18px;font-weight:bold;color:{_BRAND_COLOR};">{brand}</span>
</td></tr>

<tr><td>
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background-color:{_CARD_BG};border:1px solid {_BORDER};border-radius:12px;">
<tr><td style="padding:32px 36px;font-family:-apple-system,'PingFang SC','Microsoft YaHei',sans-serif;font-size:14px;line-height:1.8;color:{_TEXT_PRIMARY};">
{content_html}
</td></tr>
</table>
</td></tr>

<tr><td style="padding:20px 8px 0 8px;font-family:-apple-system,'PingFang SC','Microsoft YaHei',sans-serif;font-size:12px;line-height:1.6;color:{_TEXT_SECONDARY};">
本邮件由 {brand} 系统自动发送，请勿直接回复。<br>
如果你未曾进行相关操作，请忽略本邮件。
</td></tr>

</table>
</td></tr>
</table>
</body>
</html>"""


def render_verification_code(code: str, expires_in_minutes: int) -> str:
    """注册验证码邮件的 HTML 正文。"""
    safe_code = _escape(code)
    minutes = int(expires_in_minutes)
    content = f"""
<p style="margin:0 0 8px 0;font-size:16px;">你好，</p>
<p style="margin:0 0 24px 0;">你正在注册 {_escape(brand_name())} 账号，本次验证码为：</p>
<table role="presentation" width="100%" cellpadding="0" cellspacing="0">
<tr><td align="center" style="padding:8px 0 24px 0;">
<div style="display:inline-block;background-color:{_BRAND_COLOR_LIGHT};border-radius:8px;padding:14px 40px;font-family:'SF Mono',Menlo,Consolas,monospace;font-size:32px;font-weight:bold;letter-spacing:8px;color:{_BRAND_COLOR};">{safe_code}</div>
</td></tr>
</table>
<p style="margin:0 0 8px 0;">验证码将在 <strong>{minutes}</strong> 分钟后失效，请尽快完成注册。</p>
<p style="margin:0;color:{_TEXT_SECONDARY};">为了账号安全，请勿将验证码转发或告知他人。</p>
"""
    return _wrap(content)


def render_reminder(subject: str, body_text: str, overdue: bool = False) -> str:
    """定时提醒邮件的 HTML 正文。body_text 为纯文本，会被转义并保留换行。

    overdue=True 时使用红色警示样式：标题前加「已逾期」徽标，引用块变红色系。
    """
    safe_subject = _escape(subject)
    safe_body = _text_to_html(body_text or "")
    accent = _DANGER_COLOR if overdue else _BRAND_COLOR
    badge = ""
    if overdue:
        badge = (
            f'<span style="display:inline-block;background-color:{_DANGER_COLOR};color:#FFFFFF;'
            'font-size:12px;font-weight:bold;border-radius:4px;padding:2px 8px;'
            'margin-right:8px;vertical-align:2px;">已逾期</span>'
        )
    footer = (
        "该任务已超过截止时间，请尽快处理。"
        if overdue
        else "请合理安排时间，祝你顺利。"
    )
    content = f"""
<p style="margin:0 0 20px 0;font-size:18px;font-weight:bold;color:{_TEXT_PRIMARY};">{badge}{safe_subject}</p>
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="border-left:3px solid {accent};background-color:{_PAGE_BG};">
<tr><td style="padding:14px 18px;color:{_TEXT_PRIMARY};">{safe_body}</td></tr>
</table>
<p style="margin:20px 0 0 0;color:{_TEXT_SECONDARY};font-size:13px;">{footer}</p>
"""
    return _wrap(content)
