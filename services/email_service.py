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
from agent.task_manager import create_task, task_exists


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
