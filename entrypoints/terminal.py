"""
终端样式：ANSI 颜色与 emoji（仅 CLI 使用）。

- 调色板固定在柔和、显眼但不刺眼的 256 色系
- 非终端环境（管道 / 重定向 / 测试）自动输出纯文本
- 设置环境变量 NO_COLOR=1 可以强制关闭颜色
"""

import os
import sys

# --------------------------------------------------
# 调色板（256 色）
# --------------------------------------------------

LIGHT_BLUE = "38;5;117"     # 淡蓝
YELLOW = "38;5;220"         # 黄
LIGHT_PINK = "38;5;211"     # 淡粉
RED = "38;5;203"            # 红
LIGHT_GREEN = "38;5;114"    # 淡绿
GRAY = "38;5;245"           # 灰

# 任务状态 -> 颜色
STATUS_COLORS = {
    "NEW": LIGHT_BLUE,
    "PROCESSING": YELLOW,
    "WAITING_USER": YELLOW,
    "WAITING_CONFIRMATION": LIGHT_PINK,
    "EXECUTING": LIGHT_BLUE,
    "COMPLETED": LIGHT_GREEN,
    "CANCELLED": GRAY,
    "FAILED": RED,
}

# 任务状态 -> emoji
STATUS_EMOJI = {
    "NEW": "🆕",
    "PROCESSING": "⏳",
    "WAITING_USER": "💬",
    "WAITING_CONFIRMATION": "⚠️",
    "EXECUTING": "🚀",
    "COMPLETED": "✅",
    "CANCELLED": "🚫",
    "FAILED": "❌",
}


def enabled():
    """颜色开关：终端且未设置 NO_COLOR 时启用。"""

    if os.environ.get("NO_COLOR"):
        return False

    try:
        return sys.stdout.isatty()
    except Exception:
        return False


def paint(text, code, bold=False):
    """给文本着色；颜色未启用时原样返回。"""

    if not enabled():
        return text

    prefix = "\033[1;" if bold else "\033["
    return prefix + code + "m" + text + "\033[0m"


def sep(text="=" * 40):
    """分隔线（淡蓝）。"""

    return paint(text, LIGHT_BLUE)


def task_id(task_id):
    """任务 ID（淡蓝加粗）。"""

    return paint("#" + str(task_id), LIGHT_BLUE, bold=True)


def status(text, label=None):
    """任务状态（emoji + 对应颜色）。

    text：状态码（NEW / WAITING_USER / ...），用于选颜色和 emoji；
    label：显示文字，缺省时用状态码本身（可传中文名）。
    """

    label = label if label is not None else text

    return paint(
        STATUS_EMOJI.get(text, "▪️") + " " + label,
        STATUS_COLORS.get(text, GRAY),
    )


def line_style(text):
    """对 Agent 事件行做轻量着色（按关键词识别）。"""

    if not enabled():
        return text

    if text.startswith("任务状态："):
        value = text[len("任务状态："):]
        return "任务状态：" + paint(
            value, STATUS_COLORS.get(value, GRAY)
        )

    if text.startswith("=") and len(text.strip()) > 2:
        return paint(text, LIGHT_BLUE)

    if text.startswith("注意：") or "缺少" in text or text.startswith("- "):
        return paint(text, YELLOW)

    if "成功" in text and "失败" not in text:
        return paint(text, LIGHT_GREEN)

    if "失败" in text:
        return paint(text, RED)

    return text
