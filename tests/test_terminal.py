"""
entrypoints.terminal 终端样式模块的测试。
"""

import io
import unittest
from unittest import mock

import entrypoints.terminal as term


class TestTerminal(unittest.TestCase):

    def test_plain_when_not_tty(self):
        """非终端环境（StringIO）：全部原样输出，不带 ANSI 码。"""
        buf = io.StringIO()

        with mock.patch.object(term.sys, "stdout", buf):
            self.assertFalse(term.enabled())
            self.assertEqual(term.paint("文字", term.RED), "文字")
            self.assertEqual(term.sep(), "=" * 40)
            self.assertEqual(term.status("COMPLETED"), "✅ COMPLETED")
            self.assertEqual(term.task_id(5), "#5")
            self.assertEqual(
                term.line_style("任务状态：NEW"),
                "任务状态：NEW",
            )

    def test_paint_wraps_ansi_when_enabled(self):
        with mock.patch("entrypoints.terminal.enabled", return_value=True):
            self.assertEqual(
                term.paint("x", term.RED),
                "\033[38;5;203mx\033[0m",
            )
            # 任务 ID 加粗
            self.assertIn("1;", term.task_id(3))

    def test_line_style_keywords(self):
        with mock.patch("entrypoints.terminal.enabled", return_value=True):
            # 状态行：状态值着色
            out = term.line_style("任务状态：WAITING_USER")
            self.assertTrue(out.startswith("任务状态：\033"))
            self.assertIn("38;5;220", out)  # 黄

            # 分隔线淡蓝
            self.assertIn("38;5;117", term.line_style("=" * 32))

            # 注意/缺少/列表项 → 黄
            self.assertIn("38;5;220", term.line_style("注意：危险"))
            self.assertIn("38;5;220", term.line_style("还缺少以下信息："))
            self.assertIn("38;5;220", term.line_style("- 手机号"))

            # 成功绿 / 失败红
            self.assertIn("38;5;114", term.line_style("模拟提交成功"))
            self.assertIn("38;5;203", term.line_style("提交失败"))

    def test_no_color_env_disables(self):
        with mock.patch.dict("os.environ", {"NO_COLOR": "1"}):
            self.assertFalse(term.enabled())
            self.assertEqual(term.paint("x", term.RED), "x")


if __name__ == "__main__":
    unittest.main()
