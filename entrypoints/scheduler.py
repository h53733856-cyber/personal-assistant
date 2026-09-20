"""
后台调度器。

职责：
- 定时拉取邮件（间隔可配置）
- 自动处理 NEW 任务（不再需要人工在命令行点选）
- 启动时恢复：EXECUTING 中中断的任务标记为 FAILED

用法：
    python entrypoints/scheduler.py --once       # 只执行一轮
    python entrypoints/scheduler.py              # 持续运行
    python entrypoints/scheduler.py --interval 60  # 自定义间隔（秒）
"""

import sys
from pathlib import Path

# 保证从任何目录运行都能找到项目模块
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import argparse
import logging
import time

import config
import agent.task_processor as processor
import agent.task_manager as task_manager
from services.agent_service import process_task
from services.email_service import check_emails

# 调度器不直接打印到终端，统一走日志
processor.ECHO = False

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
log = logging.getLogger("scheduler")


def recover_interrupted_tasks():
    """启动恢复：EXECUTING 中中断的任务标记为 FAILED。"""

    for task in task_manager.load_tasks():

        if task["status"] != "EXECUTING":
            continue

        result = task.get("result") or {}

        if result.get("success"):
            # 执行成功但状态没更新成功（进程恰好中断），补记完成
            task_manager.update_task_status(
                task["id"],
                "COMPLETED",
                note="启动恢复：执行已成功，补记完成",
            )
            log.warning("任务 %s 执行已成功，补记 COMPLETED", task["id"])
        else:
            task_manager.update_task_status(
                task["id"],
                "FAILED",
                note="启动恢复：上次执行未完成",
            )
            log.warning("任务 %s 在 EXECUTING 中中断，已标记 FAILED", task["id"])


def process_new_tasks():
    """自动处理所有 NEW 任务。"""

    for task in task_manager.get_new_tasks():

        log.info("自动处理 NEW 任务 %s：%s", task["id"], task["subject"])

        outcome = process_task(task["id"])

        for line in outcome.events:
            log.info("[任务 %s] %s", task["id"], line)


def run_once():
    """执行一轮：恢复中断任务 → 检查邮件 → 自动处理 NEW 任务。"""

    log.info("调度一轮开始")

    recover_interrupted_tasks()

    log.info("检查邮件...")
    events = check_emails()
    for line in events:
        log.info("%s", line)

    process_new_tasks()

    log.info("调度一轮结束")


def run_forever(interval):
    while True:

        try:
            run_once()
        except Exception:
            log.exception("调度循环出现异常，等待下一轮")

        time.sleep(interval)


def main():
    parser = argparse.ArgumentParser(description="Personal Assistant 后台调度器")

    parser.add_argument(
        "--once",
        action="store_true",
        help="只执行一轮后退出",
    )
    parser.add_argument(
        "--interval",
        type=int,
        default=config.EMAIL_POLL_INTERVAL,
        help="邮件拉取间隔（秒），默认 %d" % config.EMAIL_POLL_INTERVAL,
    )

    args = parser.parse_args()

    if args.once:
        run_once()
    else:
        log.info("调度器启动，间隔 %d 秒", args.interval)
        run_forever(args.interval)


if __name__ == "__main__":
    main()
