"""
services.email_service 的单元测试。

邮件拉取与 AI 分析全部 mock，不连接 IMAP、不消耗 API；
数据在临时目录中进行。
"""

import unittest
from unittest import mock

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


if __name__ == "__main__":
    unittest.main()
