"""
邮件服务：拉取邮件 → 收据查重 → AI 分析 → 需要行动则创建任务。

邮件入口与 Agent 入口互相独立：
- 本模块只依赖 tools.email（读取解析）与 agent.email_agent（分析），
  不依赖 agent.task_processor。
- 创建任务之后，由调度器 / 用户把任务交给 Agent 继续处理。

每封邮件只分析一次：
- data/emails/processed.json 记录所有分析过的邮件（含分析结果），
  包括不需要用户行动的邮件，避免重复调用 AI。
"""

import json
import os
from datetime import datetime

import config
from tools.email import get_recent_emails
from agent.email_agent import analyze_email
from agent.task_manager import (
    create_task,
    task_exists,
    get_tasks_by_message_id,
    update_task_status,
)


def _now():
    return datetime.now().isoformat(timespec="seconds")


def _load_processed():
    if not os.path.exists(config.PROCESSED_EMAILS_FILE):
        return {}

    with open(config.PROCESSED_EMAILS_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def _save_processed(processed):
    config.EMAILS_DIR.mkdir(parents=True, exist_ok=True)

    tmp = config.PROCESSED_EMAILS_FILE.with_suffix(".tmp")

    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(processed, f, ensure_ascii=False, indent=4)

    os.replace(tmp, config.PROCESSED_EMAILS_FILE)


# 邮件状态的中文标签
STATUS_LABELS = {
    "unanalyzed": "未分析",
    "todo": "待办：需要你行动",
    "done": "已完成",
    "notice": "通知类，无需行动",
}


def fetch_recent_emails():
    """拉取最近邮件（不分析），供邮件控制台展示。"""

    return get_recent_emails()


def _status_of(processed, mail):
    """判断一封邮件的处理状态。"""

    entry = processed.get(mail["message_id"])

    if entry is None:
        return "unanalyzed"

    analysis = entry.get("analysis")

    if analysis is None:
        # 收据回溯（历史上建过任务）：默认视为待办，等用户标记完成
        return "done" if entry.get("done") else "todo"

    if analysis.get("need_action"):
        return "done" if entry.get("done") else "todo"

    return "notice"


def get_email_statuses(emails):
    """返回邮件状态列表（mail / status / 中文标签 / 分析结果）。"""

    processed = _load_processed()

    statuses = []

    for mail in emails:

        entry = processed.get(mail["message_id"])
        status = _status_of(processed, mail)

        statuses.append({
            "mail": mail,
            "status": status,
            "status_label": STATUS_LABELS[status],
            "analysis": entry.get("analysis") if entry else None,
            "done_at": entry.get("done_at") if entry else None,
        })

    return statuses


def filter_email_statuses(statuses, view):
    """按视图过滤邮件状态：

    - todo:    已分析、需要行动、还没做
    - done:    用户标记已做完
    - pending: 未分析 + 待办（所有还没处理完的）
    - all:     全部
    """

    if view == "todo":
        return [s for s in statuses if s["status"] == "todo"]

    if view == "done":
        return [s for s in statuses if s["status"] == "done"]

    if view == "pending":
        return [s for s in statuses if s["status"] in ("unanalyzed", "todo")]

    return statuses


def mark_email_done(message_id, done=True):
    """把某封已分析邮件的"已完成"标记设为 done。

    只有分析过的邮件（收据存在）才能标记。
    """

    processed = _load_processed()

    entry = processed.get(message_id)

    if entry is None:
        return False

    entry["done"] = bool(done)
    entry["done_at"] = _now() if done else None

    _save_processed(processed)

    # 标记"已做完"时，把对应的进行中任务也标记完成，
    # 保证邮件状态和任务状态一致
    if done:
        _close_pending_tasks(message_id)

    return True


def _close_pending_tasks(message_id):
    """把某封邮件对应的进行中任务标记为完成。"""

    for task in get_tasks_by_message_id(message_id):

        if task["status"] in (
            "NEW", "PROCESSING", "WAITING_USER",
            "WAITING_CONFIRMATION", "EXECUTING",
        ):
            update_task_status(
                task["id"],
                "COMPLETED",
                note="用户在邮件控制台标记已完成",
            )


def rebuild_task_for_email(message_id):
    """为某封邮件重建任务：

    - 没有任务：用收据里保存的分析结果创建任务
    - 任务已结束（COMPLETED/FAILED/CANCELLED）：重新打开为 NEW
    - 有进行中的任务：不重复创建

    返回 (ok, message, task_id)。
    """

    processed = _load_processed()

    entry = processed.get(message_id)

    if entry is None:
        return False, "该邮件没有分析记录", None

    analysis = entry.get("analysis")

    if not analysis or not analysis.get("need_action"):
        return False, "该邮件不需要行动，不需要任务", None

    tasks = get_tasks_by_message_id(message_id)

    pending = [
        t for t in tasks
        if t["status"] in (
            "NEW", "PROCESSING", "WAITING_USER",
            "WAITING_CONFIRMATION", "EXECUTING",
        )
    ]

    if pending:
        return False, "该邮件已有进行中的任务（ID %d，状态 %s）" % (
            pending[0]["id"],
            pending[0]["status"],
        ), pending[0]["id"]

    if tasks:

        task = tasks[-1]
        update_task_status(
            task["id"],
            "NEW",
            note="用户从邮件控制台重新打开",
        )
        return True, "任务 %d 已重新打开" % task["id"], task["id"]

    task = create_task({
        "message_id": message_id,
        "subject": entry.get("subject", ""),
        "sender": entry.get("sender", ""),
        "date": entry.get("date", ""),
    }, analysis)

    return True, "已从邮件记录创建任务 %d" % task["id"], task["id"]


def clear_processed_emails():
    """清空邮件处理收据：所有邮件下次检查时会重新分析。"""

    if os.path.exists(config.PROCESSED_EMAILS_FILE):
        os.remove(config.PROCESSED_EMAILS_FILE)

    return True


def check_emails(emails=None):
    """处理最近邮件，返回用户可见的事件列表。

    emails 参数仅供测试注入；为 None 时从 smail 真实拉取。
    """

    events = []

    if emails is None:
        emails = get_recent_emails()

    processed = _load_processed()

    for mail in emails:

        events.append("")
        events.append("================================")
        events.append("主题：" + mail["subject"])
        events.append("发件人：" + mail["sender"])
        events.append("时间：" + mail["date"])

        message_id = mail["message_id"]

        # 收据里已经有的，直接跳过（不重复分析）
        if message_id in processed:

            events.append("")
            events.append("这封邮件已经处理过，跳过 AI 分析。")

            continue

        # 历史上已经创建过任务的邮件（收据缺失时的兜底），
        # 同样跳过，并补一张收据
        if task_exists(message_id):

            processed[message_id] = {
                "analyzed_at": _now(),
                "subject": mail["subject"],
                "analysis": None,
                "note": "收据回溯：该邮件此前已创建任务",
            }

            events.append("")
            events.append("这封邮件已经处理过，跳过 AI 分析。")

            continue

        # ==============================
        # AI 分析
        # ==============================

        events.append("")
        events.append("AI 分析：")

        try:
            result = analyze_email(mail)
        except Exception as e:
            # 分析失败不写收据，下次运行会重试
            events.append("AI 分析失败：" + str(e))
            continue

        # 分析结果缺少必要字段时同样不写收据
        if not all(k in result for k in ("type", "core", "need_action")):
            events.append("AI 分析结果缺少必要字段，下次运行会重试。")
            continue

        processed[message_id] = {
            "analyzed_at": _now(),
            "subject": mail["subject"],
            "sender": mail["sender"],
            "date": mail["date"],
            "analysis": result,
        }

        events.append("邮件类型：" + str(result["type"]))
        events.append("核心事项：" + str(result["core"]))
        events.append("时间信息：" + str(result["time"]))
        events.append("截止时间：" + str(result["deadline"]))
        events.append("需要用户行动：" + str(result["need_action"]))
        events.append("需要做什么：" + str(result["action"]))

        # ==============================
        # 需要用户行动 → 创建任务
        # ==============================

        if result["need_action"]:

            task = create_task(mail, result)

            events.append("")
            events.append("已创建任务：" + str(task["id"]))

    _save_processed(processed)

    return events
