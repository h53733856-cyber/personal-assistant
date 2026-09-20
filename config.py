"""
项目全局配置。

所有文件路径都以项目根目录为基准，
不依赖当前工作目录（CWD）。
"""

import os
from pathlib import Path

# 项目根目录（config.py 所在目录）
PROJECT_ROOT = Path(__file__).resolve().parent

# 任务存储
TASKS_DIR = PROJECT_ROOT / "tasks"
TASK_FILE = TASKS_DIR / "tasks.json"

# 个人资料库
DOCUMENTS_DIR = PROJECT_ROOT / "data" / "documents"

# 邮件处理收据（记录哪些邮件已经分析过）
EMAILS_DIR = PROJECT_ROOT / "data" / "emails"
PROCESSED_EMAILS_FILE = EMAILS_DIR / "processed.json"

# 成长规则（用户纠正 / 偏好 / 成功经验）
RULES_DIR = PROJECT_ROOT / "rules"

# EHALL 字典码缓存（报修类型 XMDM / 报修区域 QYDM 的选项代码）
EHALL_CODES_FILE = PROJECT_ROOT / "data" / "ehall_codes.json"

# 邮件拉取间隔（秒），调度器与 Web 后台线程使用
EMAIL_POLL_INTERVAL = int(os.getenv("PA_POLL_INTERVAL", "300"))


def ensure_dirs():
    """确保所有数据目录存在。"""
    for d in (TASKS_DIR, DOCUMENTS_DIR, EMAILS_DIR, RULES_DIR):
        d.mkdir(parents=True, exist_ok=True)
