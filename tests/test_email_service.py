"""
services.email_service 的单元测试。

邮件拉取与 AI 分析全部 mock，不连接 IMAP、不消耗 API；
数据在临时目录中进行。
"""

import unittest
from unittest import mock

import config
import agent.task_manager as tm
import services.email_service as es

from tests.helpers import TempDataDir


def fake_mail(i=1, action=True):
    return {
        "message_id": "mail-%d@test" % i,
        "subject": "主题 %d" % i,
        "sender": "sender%d@example.com" % i,
        "date": "2026-09-20",
        "body": "正文 %d" % i,
    }


def fake_analysis(action=True):
    return {
        "type": "通知",
        "core": "核心事项",
        "time": None,
        "deadline": None,
        "need_action": action,
        "action": "需要做的事" if action else None,
    }


class TestEmailService(unittest.TestCase):

    def setUp(self):
        self._ctx = TempDataDir()
        self._ctx.__enter__()

    def tearDown(self):
        self._ctx.__exit__(None, None, None)

    def test_first_run_analyzes_all(self):
        mails = [fake_mail(1), fake_mail(2, action=False)]

        with mock.patch("services.email_service.analyze_email",
                        side_effect=[fake_analysis(True), fake_analysis(False)]) as fake:
            events = es.check_emails(mails)

        self.assertEqual(fake.call_count, 2)
        joined = "\n".join(events)
        self.assertIn("主题：主题 1", joined)
        self.assertIn("邮件类型：通知", joined)

    def test_second_run_skips_processed(self):
        """核心：同一封邮件不能重复处理。"""
        mails = [fake_mail(1, action=False)]

        with mock.patch("services.email_service.analyze_email",
                        return_value=fake_analysis(False)):
            es.check_emails(mails)

        with mock.patch("services.email_service.analyze_email",
                        return_value=fake_analysis(False)) as fake:
            events = es.check_emails(mails)

        self.assertEqual(fake.call_count, 0)
        self.assertIn("已经处理过", "\n".join(events))

    def test_action_mail_creates_task(self):
        mails = [fake_mail(1, action=True)]

        with mock.patch("services.email_service.analyze_email",
                        return_value=fake_analysis(True)):
            events = es.check_emails(mails)

        tasks = tm.load_tasks()
        self.assertEqual(len(tasks), 1)
        self.assertEqual(tasks[0]["message_id"], "mail-1@test")
        self.assertIn("已创建任务", "\n".join(events))

    def test_no_action_mail_no_task(self):
        mails = [fake_mail(1, action=False)]

        with mock.patch("services.email_service.analyze_email",
                        return_value=fake_analysis(False)):
            es.check_emails(mails)

        self.assertEqual(len(tm.load_tasks()), 0)

    def test_analysis_failure_retries_next_run(self):
        mails = [fake_mail(1, action=False)]

        with mock.patch("services.email_service.analyze_email",
                        side_effect=ValueError("LLM 失败")):
            events = es.check_emails(mails)

        self.assertIn("AI 分析失败", "\n".join(events))

        # 失败未写收据：下次运行会重试
        with mock.patch("services.email_service.analyze_email",
                        return_value=fake_analysis(False)) as fake:
            es.check_emails(mails)

        self.assertEqual(fake.call_count, 1)

    def test_existing_task_email_skipped(self):
        """收据缺失但已经建过任务的邮件（旧数据），跳过并补收据。"""
        mail = fake_mail(1)
        tm.create_task(mail, fake_analysis(True))

        with mock.patch("services.email_service.analyze_email") as fake:
            events = es.check_emails([mail])

        self.assertEqual(fake.call_count, 0)
        self.assertIn("已经处理过", "\n".join(events))

        # 再跑一次：收据兜底仍然生效
        with mock.patch("services.email_service.analyze_email") as fake2:
            es.check_emails([mail])

        self.assertEqual(fake2.call_count, 0)


class TestEmailStatus(unittest.TestCase):

    def setUp(self):
        self._ctx = TempDataDir()
        self._ctx.__enter__()

    def tearDown(self):
        self._ctx.__exit__(None, None, None)

    def _analyze(self, i, action):
        mail = fake_mail(i, action=action)
        with mock.patch("services.email_service.analyze_email",
                        return_value=fake_analysis(action)):
            es.check_emails([mail])
        return mail

    def test_statuses(self):
        action_mail = self._analyze(1, True)
        notice_mail = self._analyze(2, False)

        statuses = es.get_email_statuses([action_mail, notice_mail])

        self.assertEqual(statuses[0]["status"], "todo")
        self.assertEqual(statuses[1]["status"], "notice")

        unanalyzed = fake_mail(3, action=False)
        statuses = es.get_email_statuses([unanalyzed])
        self.assertEqual(statuses[0]["status"], "unanalyzed")

    def test_mark_done_and_undo(self):
        mail = self._analyze(1, True)

        self.assertTrue(es.mark_email_done(mail["message_id"], done=True))
        statuses = es.get_email_statuses([mail])
        self.assertEqual(statuses[0]["status"], "done")
        self.assertIsNotNone(statuses[0]["done_at"])

        self.assertTrue(es.mark_email_done(mail["message_id"], done=False))
        statuses = es.get_email_statuses([mail])
        self.assertEqual(statuses[0]["status"], "todo")

    def test_mark_unanalyzed_email_fails(self):
        self.assertFalse(es.mark_email_done("never-seen", done=True))

    def test_filter_views(self):
        action_mail = self._analyze(1, True)
        notice_mail = self._analyze(2, False)
        unanalyzed = fake_mail(3, action=False)

        es.mark_email_done(action_mail["message_id"], done=True)

        statuses = es.get_email_statuses(
            [action_mail, notice_mail, unanalyzed]
        )

        self.assertEqual(
            [s["status"] for s in es.filter_email_statuses(statuses, "done")],
            ["done"],
        )
        self.assertEqual(
            [s["status"] for s in es.filter_email_statuses(statuses, "todo")],
            [],
        )
        pending = es.filter_email_statuses(statuses, "pending")
        self.assertEqual([s["status"] for s in pending], ["unanalyzed"])
        self.assertEqual(
            len(es.filter_email_statuses(statuses, "all")),
            3,
        )

    def test_clear_processed_emails(self):
        self._analyze(1, True)
        self.assertTrue(config.PROCESSED_EMAILS_FILE.exists())

        es.clear_processed_emails()

        self.assertFalse(config.PROCESSED_EMAILS_FILE.exists())
        self.assertEqual(es._load_processed(), {})


class TestRebuildTask(unittest.TestCase):

    def setUp(self):
        self._ctx = TempDataDir()
        self._ctx.__enter__()

    def tearDown(self):
        self._ctx.__exit__(None, None, None)

    def _analyze_action_mail(self):
        mail = fake_mail(1, action=True)
        with mock.patch("services.email_service.analyze_email",
                        return_value=fake_analysis(True)):
            es.check_emails([mail])
        return mail

    def test_rebuild_creates_task_from_receipt(self):
        mail = self._analyze_action_mail()
        # 模拟任务被清空
        tm.clear_all_tasks()

        ok, message, task_id = es.rebuild_task_for_email(mail["message_id"])

        self.assertTrue(ok)
        task = tm.get_task(task_id)
        self.assertEqual(task["message_id"], mail["message_id"])
        self.assertEqual(task["status"], "NEW")

        # 再次重建：已有进行中的任务，不重复创建
        ok2, _, _ = es.rebuild_task_for_email(mail["message_id"])
        self.assertFalse(ok2)

    def test_rebuild_reopens_terminal_task(self):
        mail = self._analyze_action_mail()
        task_id = tm.get_tasks_by_message_id(mail["message_id"])[0]["id"]
        tm.update_task_status(task_id, "COMPLETED")

        ok, message, reopened_id = es.rebuild_task_for_email(
            mail["message_id"]
        )

        self.assertTrue(ok)
        self.assertEqual(reopened_id, task_id)
        self.assertEqual(tm.get_task(task_id)["status"], "NEW")

    def test_rebuild_no_receipt(self):
        ok, _, task_id = es.rebuild_task_for_email("never-seen")
        self.assertFalse(ok)
        self.assertIsNone(task_id)

    def test_rebuild_notice_email_rejected(self):
        mail = fake_mail(1, action=False)
        with mock.patch("services.email_service.analyze_email",
                        return_value=fake_analysis(False)):
            es.check_emails([mail])

        ok, _, _ = es.rebuild_task_for_email(mail["message_id"])
        self.assertFalse(ok)

    def test_mark_done_closes_pending_task(self):
        """邮件标记已做完时，对应的进行中任务同步完成。"""
        mail = self._analyze_action_mail()
        task = tm.get_tasks_by_message_id(mail["message_id"])[0]
        tm.update_task_status(task["id"], "WAITING_USER")

        es.mark_email_done(mail["message_id"], done=True)

        self.assertEqual(tm.get_task(task["id"])["status"], "COMPLETED")


if __name__ == "__main__":
    unittest.main()
