import unittest

from services.email_templates import (
    brand_name,
    render_reminder,
    render_verification_code,
)


class RenderVerificationCodeTests(unittest.TestCase):
    def test_contains_code_and_expiry(self):
        html = render_verification_code("123456", 10)
        self.assertIn("123456", html)
        self.assertIn("10", html)
        self.assertIn(brand_name(), html)

    def test_escapes_malicious_code(self):
        html = render_verification_code('<script>alert("x")</script>', 10)
        self.assertNotIn("<script>", html)
        self.assertIn("&lt;script&gt;", html)

    def test_is_complete_html_document(self):
        html = render_verification_code("123456", 10)
        self.assertTrue(html.startswith("<!DOCTYPE html>"))
        self.assertIn('lang="zh-CN"', html)
        self.assertIn("</html>", html)


class RenderReminderTests(unittest.TestCase):
    def test_contains_subject_and_body(self):
        html = render_reminder("数学作业截止", "明天 23:59 前提交\n记得检查格式")
        self.assertIn("数学作业截止", html)
        self.assertIn('<div style="padding:0 0 12px 0;">明天 23:59 前提交</div>', html)
        self.assertIn('<div style="padding:0;">记得检查格式</div>', html)

    def test_escapes_user_generated_content(self):
        html = render_reminder(
            '<img src=x onerror=alert(1)>',
            '任务标题 <b>加粗</b> & "引号"',
        )
        self.assertNotIn("<img src=x", html)
        self.assertNotIn("<b>加粗</b>", html)
        self.assertIn("&lt;b&gt;加粗&lt;/b&gt;", html)
        self.assertIn("&quot;引号&quot;", html)

    def test_normalizes_crlf_newlines(self):
        html = render_reminder("提醒", "第一行\r\n第二行\r第三行")
        self.assertIn("<div", html)
        self.assertIn("第一行</div>", html)
        self.assertIn("第二行</div>", html)
        self.assertIn("第三行</div>", html)

    def test_blank_line_becomes_spacer(self):
        html = render_reminder("提醒", "第一段\n\n第二段")
        self.assertIn("&nbsp;", html)

    def test_empty_body_does_not_crash(self):
        html = render_reminder("提醒", "")
        self.assertIn("提醒", html)

    def test_overdue_uses_danger_style(self):
        html = render_reminder("逾期任务", "已逾期 2 天", overdue=True)
        self.assertIn("已逾期", html)
        self.assertIn("#A32D2D", html)
        self.assertIn("请尽快处理", html)

    def test_normal_reminder_has_no_overdue_badge(self):
        html = render_reminder("普通提醒", "明天截止", overdue=False)
        self.assertNotIn("#A32D2D", html)
        self.assertIn("祝你顺利", html)


if __name__ == "__main__":
    unittest.main()
