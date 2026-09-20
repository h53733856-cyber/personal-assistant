"""
测试公共工具：把 config 中的数据路径临时指向临时目录。
"""

import shutil
import tempfile
from pathlib import Path

import config

# 记录真实路径，测试结束后恢复
_ORIGINALS = {
    "TASKS_DIR": config.TASKS_DIR,
    "TASK_FILE": config.TASK_FILE,
    "DOCUMENTS_DIR": config.DOCUMENTS_DIR,
    "EMAILS_DIR": config.EMAILS_DIR,
    "PROCESSED_EMAILS_FILE": config.PROCESSED_EMAILS_FILE,
    "RULES_DIR": config.RULES_DIR,
}


class TempDataDir:
    """上下文管理器：把 config 中的数据路径临时指向一个临时目录。"""

    def __enter__(self):
        self._tmp = Path(tempfile.mkdtemp(prefix="pa-test-"))

        config.TASKS_DIR = self._tmp / "tasks"
        config.TASK_FILE = self._tmp / "tasks" / "tasks.json"
        config.DOCUMENTS_DIR = self._tmp / "documents"
        config.EMAILS_DIR = self._tmp / "emails"
        config.PROCESSED_EMAILS_FILE = self._tmp / "emails" / "processed.json"
        config.RULES_DIR = self._tmp / "rules"

        for d in (config.TASKS_DIR, config.DOCUMENTS_DIR,
                  config.EMAILS_DIR, config.RULES_DIR):
            d.mkdir(parents=True, exist_ok=True)

        return self

    def __exit__(self, *args):
        for name, value in _ORIGINALS.items():
            setattr(config, name, value)
        shutil.rmtree(self._tmp, ignore_errors=True)
