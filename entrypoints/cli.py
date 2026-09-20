"""
命令行入口。

业务逻辑全部来自 service / agent 层，本文件只负责输入输出。
CLI 与 Web API 调用同一批 service 函数，互不影响。
"""

import sys
from pathlib import Path

# 保证从任何目录运行都能找到项目模块
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import argparse

import agent.task_processor as processor
import agent.task_manager as task_manager
from services.agent_service import (
    process_task,
    continue_task,
    confirm_task,
    cancel_task,
    get_missing_repair_fields,
)
from services.email_service import check_emails

# CLI 自己渲染事件，关闭处理器内部的终端打印
processor.ECHO = False


def _print_outcome(outcome):
    for line in outcome.events:
        print(line)


def _ask(prompt):
    """input() 的包装：管道输入结束（EOF）时返回 None，不会抛异常。"""

    try:
        return input(prompt)
    except EOFError:
        return None


VIEW_NAMES = {
    "all": "全部",
    "todo": "待办（已分析、需要行动、还没做）",
    "done": "已完成（你标记过做完了）",
    "pending": "未处理（未分析 + 待办）",
}


def email_console():
    """邮件控制台：拉取邮件 → 分析新邮件 → 显示每封状态 → 过滤/标记。"""

    from services.email_service import (
        fetch_recent_emails,
        get_email_statuses,
        filter_email_statuses,
        mark_email_done,
    )

    print()
    print("======== 邮件服务 ========")
    print("正在拉取最近邮件...")

    mails = fetch_recent_emails()

    # 分析未分析的新邮件（已处理过的保持跳过，不重复花钱）
    events = check_emails(mails)

    for line in events:
        print(line)

    current_view = "all"

    while True:

        statuses = get_email_statuses(mails)
        shown = filter_email_statuses(statuses, current_view)

        print()
        print("====== 邮件状态（%s）======" % VIEW_NAMES[current_view])

        if not shown:
            print("（没有符合条件的邮件）")

        for i, s in enumerate(shown, 1):
            print("[%d] %s" % (i, s["mail"]["subject"]))
            print("    发件人：%s ｜ 时间：%s ｜ %s"
                  % (s["mail"]["sender"], s["mail"]["date"],
                     s["status_label"]))

        print()
        cmd = _ask(
            "1 待办 ｜ 2 已完成 ｜ 3 未处理 ｜ a 全部 ｜ "
            "d 序号 标记已做完 ｜ u 序号 取消标记 ｜ "
            "t 序号 重建任务 ｜ q 返回："
        )

        if cmd is None or cmd.strip().lower() == "q":

            print("返回菜单。")
            return

        parts = cmd.strip().split()

        if cmd.strip() == "1":
            current_view = "todo"
            continue

        if cmd.strip() == "2":
            current_view = "done"
            continue

        if cmd.strip() == "3":
            current_view = "pending"
            continue

        if cmd.strip().lower() == "a":
            current_view = "all"
            continue

        # d 序号 / u 序号：标记或取消"已做完"
        if len(parts) == 2 \
                and parts[0] in ("d", "u") \
                and parts[1].isdigit():

            idx = int(parts[1])

            if 1 <= idx <= len(shown):

                target = shown[idx - 1]
                ok = mark_email_done(
                    target["mail"]["message_id"],
                    done=(parts[0] == "d"),
                )

                if ok:
                    print("标记成功。" if parts[0] == "d" else "已取消标记。")
                else:
                    print("该邮件还没有分析记录，无法标记。")

            else:
                print("序号超出范围。")

            continue

        # t 序号：重建 / 重新打开该邮件的任务
        if len(parts) == 2 and parts[0] == "t" and parts[1].isdigit():

            idx = int(parts[1])

            if 1 <= idx <= len(shown):

                from services.email_service import rebuild_task_for_email

                target = shown[idx - 1]
                ok, message, task_id = rebuild_task_for_email(
                    target["mail"]["message_id"]
                )

                print(message)

                if ok and task_id:
                    _print_outcome(process_task(task_id))

            else:
                print("序号超出范围。")

            continue

        print("无法识别你的输入。")


def data_console():
    """数据管理：清空任务 / 清空邮件记录（都需要明确确认）。"""

    while True:

        print()
        print("======== 数据管理 ========")
        print("1. 清空任务数据（tasks.json，任务 ID 从 1 重新开始）")
        print("2. 清空邮件记录（processed.json，邮件会重新分析并重建任务）")
        print("q. 返回")
        print()

        choice = _ask("请选择：")

        if choice is None or choice == "q":
            return

        if choice == "1":

            confirm = _ask("将删除所有任务记录，输入 y 确认：")

            if confirm and confirm.strip().lower() == "y":

                task_manager.clear_all_tasks()
                print("任务数据已清空，任务 ID 从 1 重新开始。")
                print("注意：邮件记录未动，已处理过的邮件不会重新分析。")

            else:
                print("已取消。")

        elif choice == "2":

            confirm = _ask("将清空邮件处理记录，输入 y 确认：")

            if confirm and confirm.strip().lower() == "y":

                from services.email_service import clear_processed_emails

                clear_processed_emails()
                print("邮件记录已清空，下次检查邮件会重新分析。")
                print("注意：任务数据未动。")

            else:
                print("已取消。")

        else:

            print("无法识别你的输入。")


def list_tasks():
    print()
    print("================================")
    print("当前需要用户处理的任务：")

    for task in task_manager.get_user_tasks():
        print()
        print("任务 ID：", task["id"])
        print("任务主题：", task["subject"])
        print("任务内容：", task["analysis"]["core"])
        print("任务状态：", task["status"])


def create_task_from_text(text):
    """分析用户请求并创建任务，返回最新任务（或 None）。"""

    from agent.user_agent import analyze_user_request

    print()
    print("正在分析你的请求...")

    analysis = analyze_user_request(text)

    print("请求类型：", analysis["type"])
    print("核心事项：", analysis["core"])
    print("需要用户行动：", analysis["need_action"])

    if not analysis.get("need_action"):
        print("这个请求不需要创建任务。")
        return None

    task = task_manager.create_user_task(text, analysis)

    print()
    print("已创建任务：", task["id"])
    print()

    _print_outcome(process_task(task["id"]))

    return task_manager.get_task(task["id"])


def drive_task(task_id):
    """连续引导一个任务直到结束：

    - 缺信息：直接在这里补充（按 W 返回菜单）
    - 要确认：先展示确认单再询问
    - NEW：自动开始处理
    """

    while True:

        task = task_manager.get_task(task_id)

        if task is None:

            print("任务不存在。")
            return

        status = task["status"]

        # ==============================
        # 等待用户补充信息：原地询问
        # ==============================

        if status == "WAITING_USER":

            print()
            print("这个任务正在等待你的信息。")

            missing = get_missing_repair_fields(task)

            if missing:

                print()
                print("还缺少以下信息：")

                for name in missing:
                    print("- " + name)

            print()
            user_input = _ask("请直接输入补充信息（按 W 返回菜单）：")

            if user_input is None or user_input.strip().lower() == "w":

                print("任务保持等待状态，稍后可以在任务中心继续。")
                return

            if user_input.strip():
                _print_outcome(continue_task(task_id, user_input.strip()))

            continue

        # ==============================
        # 等待用户确认：先展示确认单
        # ==============================

        if status == "WAITING_CONFIRMATION":

            print()
            print("这个任务需要你的确认。")

            confirmation = task.get("confirmation")

            if confirmation:

                print()
                print("================================")
                print(confirmation["title"])
                print("================================")

                for field in confirmation["fields"]:
                    print(field["label"] + "：" + str(field["value"]))

                print()
                print("注意：" + confirmation["warning"])
                print("================================")

            else:

                print("任务内容：", task["analysis"]["core"])

            confirm_input = _ask("请输入“确认”或“取消”（按 W 返回菜单）：")

            if confirm_input == "确认":

                _print_outcome(confirm_task(task_id))
                return

            if confirm_input == "取消":

                print("用户取消了任务。")

                _print_outcome(cancel_task(task_id))
                return

            if confirm_input is None or confirm_input.strip().lower() == "w":
                return

            print("无法识别你的输入，任务暂不执行。")
            continue

        # ==============================
        # 还没开始处理：自动开始
        # ==============================

        if status == "NEW":

            print()
            print("这个任务还没有开始处理。")

            _print_outcome(process_task(task_id))

            # 如果处理没有让状态前进（异常情况），不再无限循环
            task = task_manager.get_task(task_id)

            if task and task["status"] == "NEW":

                print("任务处理没有推进，请稍后在任务中心重试。")
                return

            continue

        # ==============================
        # 其他状态（终态）
        # ==============================

        print()
        print("当前任务状态：", status)
        return


def record_feedback_from_cli(text, commit=False):
    from agent.growth import record_feedback

    path = record_feedback(text, commit=commit)

    print("反馈已记录：", path)
    print("Agent 之后的任务会遵守这条规则。")


def interactive_loop():
    """任务交互循环（原 main.py 的交互部分）。"""

    print()
    print("================================")
    print("任务交互")

    while True:

        user_tasks = task_manager.get_user_tasks()

        if len(user_tasks) == 0:

            print()
            print("当前没有需要处理的任务。")
            return

        print()
        print("当前需要用户处理的任务：")

        for task in user_tasks:

            print()
            print("任务 ID：", task["id"])
            print("任务主题：", task["subject"])
            print("任务内容：", task["analysis"]["core"])
            print("任务状态：", task["status"])

        print()

        task_id_input = _ask(
            "输入任务 ID 处理；输入 new 创建新任务；输入 q 返回："
        )

        if task_id_input is None or task_id_input == "q":

            print("退出任务交互。")
            return

        if task_id_input == "new":

            text = _ask("请输入你的请求：")

            if text and text.strip():
                create_task_from_text(text.strip())

            continue

        try:
            task_id = int(task_id_input)
        except ValueError:

            print("无法识别你的输入。")
            continue

        task = task_manager.get_task(task_id)

        if task is None:

            print("任务不存在。")
            continue

        # 交给 drive_task 连续引导：缺信息原地补、确认单先展示，
        # 按 W 回到任务列表
        drive_task(task_id)


def main_menu():
    """主菜单：一个命令进来，选择要用的功能，选哪个自动运行哪个。"""

    while True:

        print()
        print("========================================")
        print("个人助手")
        print("========================================")
        print("1. 邮件服务：检查 smail，AI 分析并自动创建任务")
        print("2. 宿舍报修：发起 EHALL 报修任务")
        print("3. 任务中心：查看任务、补充信息、确认执行")
        print("4. 数据管理：清空任务数据 / 清空邮件记录")
        print("q. 退出")
        print()

        choice = _ask("请选择功能：")

        if choice is None or choice == "q":

            print("再见！")
            return

        if choice == "1":

            email_console()

        elif choice == "4":

            data_console()

        elif choice == "2":

            text = _ask(
                "请描述报修内容（例如：我的宿舍卫生间水龙头坏了，需要维修）："
            )

            if not text or not text.strip():

                print("没有输入内容，返回菜单。")

            else:

                task = create_task_from_text(text.strip())

                if task:
                    # 缺什么信息直接在这里补充，按 W 返回菜单
                    drive_task(task["id"])

        elif choice == "3":

            list_tasks()
            interactive_loop()

        else:

            print("无法识别你的输入，请重新选择。")


def main():
    parser = argparse.ArgumentParser(description="Personal Assistant 命令行入口")

    parser.add_argument(
        "command",
        nargs="?",
        default="menu",
        choices=["menu", "email", "tasks", "new", "feedback"],
        help="menu=功能主菜单（默认）；email=直接运行邮件服务；"
             "tasks=列出任务；new=直接创建任务；feedback=记录一条用户纠正/偏好",
    )
    parser.add_argument("text", nargs="*", help="new / feedback 命令的内容")
    parser.add_argument(
        "--commit",
        action="store_true",
        help="feedback 时自动 git 提交",
    )

    args = parser.parse_args()

    if args.command == "menu":
        main_menu()
    elif args.command == "email":
        email_console()
    elif args.command == "tasks":
        list_tasks()
    elif args.command == "new":
        text = " ".join(args.text)
        if not text:
            print("请提供任务描述，例如：python main.py new 我要报修宿舍水龙头")
            return
        create_task_from_text(text)
    elif args.command == "feedback":
        text = " ".join(args.text)
        if not text:
            print("请提供反馈内容，例如：python main.py feedback 报修时间格式要统一")
            return
        record_feedback_from_cli(text, commit=args.commit)


if __name__ == "__main__":
    main()
