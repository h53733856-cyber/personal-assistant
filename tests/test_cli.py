"""
entrypoints.cli 的行为测试（LLM 全部 mock）。
"""

import contextlib
import io
import unittest
from unittest import mock

import config
import agent.task_manager as tm
import agent.task_processor as tp
import entrypoints.cli as cli

from tests.helpers import TempDataDir

ANALYSIS = {
    "type": "宿舍报修",
    "core": "宿舍水龙头坏了，需要报修",
    "time": None,
    "deadline": None,
    "need_action": True,
    "action": "在 EHALL 提交宿舍报修申请",
}


class TestCli(unittest.TestCase):

    def setUp(self):
        self._ctx = TempDataDir()
        self._ctx.__enter__()
        self._echo = tp.ECHO
        tp.ECHO = False

    def tearDown(self):
        tp.ECHO = self._echo
        self._ctx.__exit__(None, None, None)

    def test_interact_quits_when_no_tasks(self):
        with mock.patch("entrypoints.cli.check_emails", return_value=[]), \
             mock.patch("builtins.input", side_effect=["q"]):
            cli.interactive_loop()

    def test_create_task_from_text(self):
        outcome = tp.Outcome(ok=True, events=["开始处理任务"])

        with mock.patch("agent.user_agent.analyze_user_request",
                        return_value=ANALYSIS), \
             mock.patch("entrypoints.cli.process_task",
                        return_value=outcome):
            cli.create_task_from_text("我要报修宿舍水龙头")

        tasks = tm.load_tasks()
        self.assertEqual(len(tasks), 1)
        self.assertEqual(tasks[0]["source"], "user")
        self.assertEqual(tasks[0]["subject"], "我要报修宿舍水龙头")

    def test_interact_waits_for_input_and_processes(self):
        """用户选择 WAITING_USER 任务并补充信息。"""
        task = tm.create_user_task("报修", ANALYSIS)
        tm.update_task_status(task["id"], "WAITING_USER")

        outcome = tp.Outcome(ok=True, events=["用户输入已经保存"])

        with mock.patch("builtins.input", side_effect=[
                str(task["id"]),   # 选择任务
                "补充的信息",       # WAITING_USER 回复
                "w",               # 按 W 返回任务列表
                "q",               # 退出任务交互
        ]) as fake_input, \
             mock.patch("entrypoints.cli.continue_task",
                        return_value=outcome) as fake_continue:
            cli.interactive_loop()

        # 用户补充的信息被交给 continue_task
        fake_continue.assert_called_once_with(task["id"], "补充的信息")


class TestEmailConsole(unittest.TestCase):

    def setUp(self):
        self._ctx = TempDataDir()
        self._ctx.__enter__()
        self._echo = tp.ECHO
        tp.ECHO = False

    def tearDown(self):
        tp.ECHO = self._echo
        self._ctx.__exit__(None, None, None)

    MAILS = [
        {
            "message_id": "m1", "subject": "行动邮件",
            "sender": "a@b", "date": "2026-09-20", "body": "x",
        },
        {
            "message_id": "m2", "subject": "通知邮件",
            "sender": "a@b", "date": "2026-09-20", "body": "x",
        },
    ]

    STATUSES = [
        {
            "mail": MAILS[0], "status": "todo",
            "status_label": "待办：需要你行动",
            "analysis": {"need_action": True}, "done_at": None,
        },
        {
            "mail": MAILS[1], "status": "notice",
            "status_label": "通知类，无需行动",
            "analysis": {"need_action": False}, "done_at": None,
        },
    ]

    def _patch_console(self, statuses=None):
        return (
            mock.patch("services.email_service.fetch_recent_emails",
                       return_value=self.MAILS),
            mock.patch("entrypoints.cli.check_emails", return_value=[]),
            mock.patch("services.email_service.get_email_statuses",
                       return_value=statuses or self.STATUSES),
            mock.patch("services.email_service.filter_email_statuses",
                       side_effect=lambda s, view: s),
        )

    def test_console_quit(self):
        with mock.patch("builtins.input", side_effect=["q"]):
            with contextlib.ExitStack() as stack:
                for p in self._patch_console():
                    stack.enter_context(p)
                cli.email_console()

    def test_console_mark_done(self):
        """d 1 把第一封标记为已做完。"""
        with mock.patch("builtins.input", side_effect=["d 1", "q"]):
            with contextlib.ExitStack() as stack:
                for p in self._patch_console():
                    stack.enter_context(p)
                fake_mark = stack.enter_context(
                    mock.patch("services.email_service.mark_email_done",
                               return_value=True)
                )
                cli.email_console()

        fake_mark.assert_called_once_with("m1", done=True)

    def test_console_unmark(self):
        with mock.patch("builtins.input", side_effect=["u 1", "q"]):
            with contextlib.ExitStack() as stack:
                for p in self._patch_console():
                    stack.enter_context(p)
                fake_mark = stack.enter_context(
                    mock.patch("services.email_service.mark_email_done",
                               return_value=True)
                )
                cli.email_console()

        fake_mark.assert_called_once_with("m1", done=False)

    def test_console_mark_out_of_range(self):
        with mock.patch("builtins.input", side_effect=["d 9", "q"]):
            with contextlib.ExitStack() as stack:
                for p in self._patch_console():
                    stack.enter_context(p)
                fake_mark = stack.enter_context(
                    mock.patch("services.email_service.mark_email_done")
                )
                cli.email_console()

        fake_mark.assert_not_called()

    def test_console_rebuild_task(self):
        """t 1 重建任务并自动处理。"""
        with mock.patch("builtins.input", side_effect=["t 1", "q"]):
            with contextlib.ExitStack() as stack:
                for p in self._patch_console():
                    stack.enter_context(p)
                fake_rebuild = stack.enter_context(
                    mock.patch(
                        "services.email_service.rebuild_task_for_email",
                        return_value=(True, "任务 1 已重新打开", 1),
                    )
                )
                fake_process = stack.enter_context(
                    mock.patch("entrypoints.cli.process_task",
                               return_value=tp.Outcome(ok=True, events=[]))
                )
                cli.email_console()

        fake_rebuild.assert_called_once_with("m1")
        fake_process.assert_called_once_with(1)


class TestRepairConsole(unittest.TestCase):

    def setUp(self):
        self._ctx = TempDataDir()
        self._ctx.__enter__()
        self._echo = tp.ECHO
        tp.ECHO = False

    def tearDown(self):
        tp.ECHO = self._echo
        self._ctx.__exit__(None, None, None)

    def _repair_task(self, status):
        task = tm.create_user_task("报修任务", ANALYSIS)
        tm.update_task_status(task["id"], status)
        return task["id"]

    def test_new_repair_creates_and_drives(self):
        with mock.patch(
            "builtins.input",
            side_effect=["1", "空调坏了，需要维修", "w", "q"],
        ), mock.patch("entrypoints.cli.create_task_from_text",
                      return_value={"id": 1}), \
           mock.patch("entrypoints.cli.drive_task") as fake:
            cli.repair_console()

        fake.assert_called_once_with(1)

    def test_records_lists_repair_tasks(self):
        """查看报修记录：显示任务和状态，q 返回。"""
        self._repair_task("WAITING_CONFIRMATION")
        self._repair_task("FAILED")

        buf = io.StringIO()

        with mock.patch("builtins.input", side_effect=["2", "q", "q"]), \
             contextlib.redirect_stdout(buf):
            cli.repair_console()

        output = buf.getvalue()
        self.assertIn("报修记录（共 2 条）", output)
        self.assertIn("等你确认", output)
        self.assertIn("失败", output)

    def test_records_empty(self):
        buf = io.StringIO()

        with mock.patch("builtins.input", side_effect=["2", "q"]), \
             contextlib.redirect_stdout(buf):
            cli.repair_console()

        self.assertIn("还没有报修记录", buf.getvalue())

    def test_records_select_task_drives(self):
        tid = self._repair_task("WAITING_USER")

        with mock.patch("builtins.input",
                        side_effect=["2", str(tid), "w", "q"]), \
             mock.patch("entrypoints.cli.drive_task") as fake:
            cli.repair_console()

        fake.assert_called_once_with(tid)


class TestDataConsole(unittest.TestCase):

    def setUp(self):
        self._ctx = TempDataDir()
        self._ctx.__enter__()
        self._echo = tp.ECHO
        tp.ECHO = False

    def tearDown(self):
        tp.ECHO = self._echo
        self._ctx.__exit__(None, None, None)

    def test_clear_tasks_confirmed(self):
        tm.create_user_task("任务", ANALYSIS)

        with mock.patch("builtins.input", side_effect=["1", "y", "q"]):
            cli.data_console()

        self.assertEqual(tm.load_tasks(), [])
        # 新任务 ID 从 1 重新开始
        task = tm.create_user_task("新任务", ANALYSIS)
        self.assertEqual(task["id"], 1)

    def test_clear_tasks_cancelled(self):
        tm.create_user_task("任务", ANALYSIS)

        with mock.patch("builtins.input", side_effect=["1", "n", "q"]):
            cli.data_console()

        self.assertEqual(len(tm.load_tasks()), 1)

    def test_clear_emails_confirmed(self):
        with mock.patch("builtins.input", side_effect=["2", "y", "q"]):
            cli.data_console()

        self.assertFalse(config.PROCESSED_EMAILS_FILE.exists())

    def test_clear_emails_cancelled(self):
        # 先造一条邮件记录
        from services.email_service import check_emails
        with mock.patch("services.email_service.analyze_email",
                        return_value={
                            "type": "通知", "core": "x",
                            "time": None, "deadline": None,
                            "need_action": False, "action": None,
                        }):
            check_emails([{
                "message_id": "m1", "subject": "s", "sender": "a",
                "date": "d", "body": "b",
            }])

        self.assertTrue(config.PROCESSED_EMAILS_FILE.exists())

        with mock.patch("builtins.input", side_effect=["2", "n", "q"]):
            cli.data_console()

        self.assertTrue(config.PROCESSED_EMAILS_FILE.exists())


class TestDriveTask(unittest.TestCase):

    def setUp(self):
        self._ctx = TempDataDir()
        self._ctx.__enter__()
        self._echo = tp.ECHO
        tp.ECHO = False

    def tearDown(self):
        tp.ECHO = self._echo
        self._ctx.__exit__(None, None, None)

    def _repair_task(self, status, with_data=False):
        task = tm.create_user_task("报修", ANALYSIS)
        tm.update_task_status(task["id"], status)
        if with_data:
            tm.update_task_data(task["id"], "repair_data", {
                "SJH": "13800000000",
                "XMDM": "水龙头/水龙头漏水",
                "QYDM": "仙林校区",
                "GZDD": "某宿舍楼某房间",
                "DZ_FBSMKSSJ": "2026-09-20 19:00",
                "DZ_FBSMJSSJ": "2026-09-20 21:00",
                "GZMS": "水龙头坏了",
                "BZ": "",
                "GZTP": "",
                "DZ_SSDW": "1",
            })
        return task["id"]

    def test_waiting_user_w_returns_without_continue(self):
        tid = self._repair_task("WAITING_USER")

        with mock.patch("builtins.input", side_effect=["w"]), \
             mock.patch("entrypoints.cli.continue_task") as fake:
            cli.drive_task(tid)

        fake.assert_not_called()
        self.assertEqual(tm.get_task(tid)["status"], "WAITING_USER")

    def test_waiting_user_input_then_w(self):
        tid = self._repair_task("WAITING_USER")

        outcome = tp.Outcome(ok=True, events=["用户输入已经保存"])

        with mock.patch("builtins.input", side_effect=["补充的信息", "w"]), \
             mock.patch("entrypoints.cli.continue_task",
                        return_value=outcome) as fake:
            cli.drive_task(tid)

        fake.assert_called_once_with(tid, "补充的信息")

    def test_waiting_confirmation_confirm(self):
        tid = self._repair_task("WAITING_CONFIRMATION", with_data=True)

        with mock.patch("builtins.input", side_effect=["确认"]), \
             mock.patch("entrypoints.cli.confirm_task",
                        return_value=tp.Outcome(ok=False, events=["失败"])) as fake:
            cli.drive_task(tid)

        fake.assert_called_once_with(tid)

    def test_waiting_confirmation_w_keeps_state(self):
        tid = self._repair_task("WAITING_CONFIRMATION", with_data=True)

        with mock.patch("builtins.input", side_effect=["w"]), \
             mock.patch("entrypoints.cli.confirm_task") as fake_confirm, \
             mock.patch("entrypoints.cli.cancel_task") as fake_cancel:
            cli.drive_task(tid)

        fake_confirm.assert_not_called()
        fake_cancel.assert_not_called()
        self.assertEqual(tm.get_task(tid)["status"], "WAITING_CONFIRMATION")

    def test_new_task_auto_processed(self):
        tid = self._repair_task("NEW")

        with mock.patch("builtins.input", side_effect=["w"]), \
             mock.patch("entrypoints.cli.process_task",
                        return_value=tp.Outcome(ok=True, events=["处理中"])) as fake:
            cli.drive_task(tid)

        fake.assert_called_once_with(tid)

    def test_unknown_task(self):
        with mock.patch("builtins.input", side_effect=["w"]):
            cli.drive_task(999)


class TestMainMenu(unittest.TestCase):

    def setUp(self):
        self._ctx = TempDataDir()
        self._ctx.__enter__()
        self._echo = tp.ECHO
        tp.ECHO = False

    def tearDown(self):
        tp.ECHO = self._echo
        self._ctx.__exit__(None, None, None)

    def test_menu_quit(self):
        with mock.patch("builtins.input", side_effect=["q"]):
            cli.main_menu()

    def test_menu_choice_1_email(self):
        with mock.patch("builtins.input", side_effect=["1", "q"]), \
             mock.patch("entrypoints.cli.email_console") as fake:
            cli.main_menu()

        fake.assert_called_once_with()

    def test_menu_choice_4_data(self):
        with mock.patch("builtins.input", side_effect=["4", "q", "q"]), \
             mock.patch("entrypoints.cli.data_console") as fake:
            cli.main_menu()

        fake.assert_called_once_with()

    def test_menu_choice_3_tasks(self):
        with mock.patch("builtins.input", side_effect=["3", "q"]), \
             mock.patch("entrypoints.cli.list_tasks"), \
             mock.patch("entrypoints.cli.interactive_loop") as fake:
            cli.main_menu()

        fake.assert_called_once_with()

    def test_menu_choice_2_opens_repair_console(self):
        with mock.patch("builtins.input", side_effect=["2", "q", "q"]), \
             mock.patch("entrypoints.cli.repair_console") as fake:
            cli.main_menu()

        fake.assert_called_once_with()

    def test_menu_unknown_choice(self):
        with mock.patch("builtins.input", side_effect=["x", "q"]):
            cli.main_menu()

    def test_menu_eof_exits_cleanly(self):
        """管道输入提前结束（EOF）时不抛异常。"""
        with mock.patch("builtins.input", side_effect=EOFError):
            cli.main_menu()


if __name__ == "__main__":
    unittest.main()
