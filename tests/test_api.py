"""
server.py REST API 的测试（Flask test client，LLM 全部 mock）。
"""

import unittest
from unittest import mock

import agent.task_manager as tm
import agent.task_processor as tp
import server as server_mod

from tests.helpers import TempDataDir

ANALYSIS = {
    "type": "宿舍报修",
    "core": "宿舍水龙头坏了，需要报修",
    "time": None,
    "deadline": None,
    "need_action": True,
    "action": "在 EHALL 提交宿舍报修申请",
}

REPAIR_COMPLETE = {
    "phone": "13800000000",
    "repair_type": "水龙头/水龙头漏水",
    "area": "仙林校区",
    "location": "某宿舍楼某房间",
    "start_time": "2026-09-20 19:00",
    "end_time": "2026-09-20 21:00",
    "description": "水龙头坏了",
    "remark": "",
    "image": "",
}

DECISION_CONFIRM = {
    "next_status": "WAITING_CONFIRMATION",
    "need_user_input": False,
    "question": None,
    "reason": "信息完整，需要确认",
}


class TestApi(unittest.TestCase):

    def setUp(self):
        self._ctx = TempDataDir()
        self._ctx.__enter__()
        self._echo = tp.ECHO
        tp.ECHO = False
        self.client = server_mod.app.test_client()

    def tearDown(self):
        tp.ECHO = self._echo
        self._ctx.__exit__(None, None, None)

    def test_index_served(self):
        r = self.client.get("/")
        self.assertEqual(r.status_code, 200)
        self.assertIn("个人助手", r.get_data(as_text=True))

    def test_list_tasks_empty(self):
        r = self.client.get("/api/tasks")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.get_json(), [])

    def test_create_task(self):
        with mock.patch("agent.user_agent.analyze_user_request",
                        return_value=ANALYSIS):
            r = self.client.post(
                "/api/tasks",
                json={"text": "我要报修宿舍水龙头"},
            )

        data = r.get_json()

        self.assertTrue(data["ok"])
        self.assertTrue(data["created"])
        self.assertEqual(data["task"]["source"], "user")
        self.assertEqual(tm.get_task(data["task"]["id"])["subject"],
                         "我要报修宿舍水龙头")

    def test_create_task_empty_text(self):
        r = self.client.post("/api/tasks", json={"text": "  "})
        self.assertEqual(r.status_code, 400)

    def test_get_task_404(self):
        r = self.client.get("/api/tasks/999")
        self.assertEqual(r.status_code, 404)

    def test_input_flow_with_confirmation(self):
        """手机端补充信息 → 生成确认单。"""
        task = tm.create_user_task("报修", ANALYSIS)
        tm.update_task_status(task["id"], "WAITING_USER")

        with mock.patch(
            "agent.task_processor.ask_llm_json",
            side_effect=[REPAIR_COMPLETE, DECISION_CONFIRM],
        ):
            r = self.client.post(
                f"/api/tasks/{task['id']}/input",
                json={"text": "补充信息"},
            )

        data = r.get_json()

        self.assertTrue(data["ok"])
        self.assertEqual(data["task"]["status"], "WAITING_CONFIRMATION")
        self.assertIsNotNone(data["task"]["confirmation"])
        self.assertEqual(
            data["task"]["confirmation"]["title"],
            "即将提交 EHALL 宿舍报修申请",
        )

    def test_confirm_and_result(self):
        task = tm.create_user_task("报修", ANALYSIS)
        tm.update_task_status(task["id"], "WAITING_CONFIRMATION")
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

        r = self.client.post(f"/api/tasks/{task['id']}/confirm")

        data = r.get_json()

        # 默认 EHALL_DRY_RUN=1：模拟提交成功 → COMPLETED
        self.assertTrue(data["ok"])
        self.assertEqual(data["task"]["status"], "COMPLETED")
        self.assertIn("模拟提交", data["task"]["result"]["message"])

    def test_cancel(self):
        task = tm.create_user_task("报修", ANALYSIS)
        tm.update_task_status(task["id"], "WAITING_CONFIRMATION")

        r = self.client.post(f"/api/tasks/{task['id']}/cancel")

        data = r.get_json()

        self.assertTrue(data["ok"])
        self.assertEqual(data["task"]["status"], "CANCELLED")

    def test_emails_check(self):
        with mock.patch("server.check_emails", return_value=[]):
            r = self.client.post("/api/emails/check")

        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.get_json()["ok"])

    def test_feedback(self):
        r = self.client.post(
            "/api/feedback",
            json={"content": "报修时间格式要统一", "category": "用户偏好"},
        )

        data = r.get_json()

        self.assertTrue(data["ok"])
        self.assertTrue(data["path"].endswith("feedback.md"))


if __name__ == "__main__":
    unittest.main()
