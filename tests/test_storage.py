"""
agent.task_manager 存储层的单元测试。

全部在临时目录中进行，不碰真实的 tasks/tasks.json。
"""

import threading
import unittest

import config
import agent.task_manager as tm

from tests.helpers import TempDataDir


def fake_email(i=1):
    return {
        "message_id": "mail-%d@test" % i,
        "subject": "主题 %d" % i,
        "sender": "sender%d@example.com" % i,
        "date": "2026-09-20",
    }


class TestTaskStorage(unittest.TestCase):

    def setUp(self):
        self._ctx = TempDataDir()
        self._ctx.__enter__()

    def tearDown(self):
        self._ctx.__exit__(None, None, None)

    def test_empty_load(self):
        self.assertEqual(tm.load_tasks(), [])

    def test_create_and_get(self):
        task = tm.create_task(fake_email(), {"type": "通知", "core": "x"})
        self.assertEqual(tm.get_task(task["id"])["subject"], "主题 1")

    def test_task_exists(self):
        tm.create_task(fake_email(1), {"core": "x"})
        self.assertTrue(tm.task_exists("mail-1@test"))
        self.assertFalse(tm.task_exists("mail-2@test"))

    def test_update_status(self):
        task = tm.create_task(fake_email(), {"core": "x"})
        tm.update_task_status(task["id"], "PROCESSING")
        self.assertEqual(tm.get_task(task["id"])["status"], "PROCESSING")

    def test_update_data(self):
        task = tm.create_task(fake_email(), {"core": "x"})
        tm.update_task_data(task["id"], "repair_data", {"SJH": "1"})
        self.assertEqual(tm.get_task(task["id"])["repair_data"], {"SJH": "1"})

    def test_add_user_input(self):
        task = tm.create_task(fake_email(), {"core": "x"})
        tm.add_user_input(task["id"], "补充1")
        tm.add_user_input(task["id"], "补充2")
        self.assertEqual(
            tm.get_task(task["id"])["user_inputs"],
            ["补充1", "补充2"]
        )

    def test_get_new_and_user_tasks(self):
        t1 = tm.create_task(fake_email(1), {"core": "x"})
        t2 = tm.create_task(fake_email(2), {"core": "y"})
        tm.update_task_status(t2["id"], "WAITING_USER")

        self.assertEqual([t["id"] for t in tm.get_new_tasks()], [t1["id"]])
        self.assertEqual(len(tm.get_user_tasks()), 2)

    def test_concurrent_creates_unique_ids(self):
        """多线程并发创建任务，ID 不能重复。"""
        errors = []

        def create(i):
            try:
                tm.create_task(fake_email(i), {"core": "x"})
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=create, args=(i,)) for i in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(errors, [])
        ids = [t["id"] for t in tm.load_tasks()]
        self.assertEqual(len(ids), len(set(ids)))

    def test_atomic_write_no_tmp_left(self):
        tm.create_task(fake_email(), {"core": "x"})
        self.assertFalse(config.TASK_FILE.with_suffix(".tmp").exists())


if __name__ == "__main__":
    unittest.main()
