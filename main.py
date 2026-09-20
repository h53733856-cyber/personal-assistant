"""
Personal Assistant 入口。

默认进入命令行交互模式（检查邮件 + 任务交互）。
CLI 的完整实现见 entrypoints/cli.py。
"""

from entrypoints.cli import main

if __name__ == "__main__":
    main()
