"""
Agent 成长机制。

用户纠正、偏好、成功经验保存为 rules/ 目录下可读可编辑的
Markdown 规则文件，每次 Agent 做决策时把规则注入 prompt，实现持续成长。
规则文件纳入 git 管理，变化可回溯。
"""

import os
import subprocess
from datetime import datetime

import config

# 这个文件是规则目录的说明文档，不参与注入
README_NAME = "README.md"


def list_rules():
    """返回规则文件列表（name / path / content）。"""

    rules = []

    config.RULES_DIR.mkdir(parents=True, exist_ok=True)

    for name in sorted(os.listdir(config.RULES_DIR)):

        if not name.endswith(".md") or name == README_NAME:
            continue

        path = config.RULES_DIR / name

        with open(path, "r", encoding="utf-8") as f:
            rules.append({
                "name": name,
                "path": str(path),
                "content": f.read(),
            })

    return rules


def inject_rules(prompt):
    """把已有规则注入 prompt；没有规则时原样返回。"""

    rules = list_rules()

    if not rules:
        return prompt

    parts = [
        "以下是过去任务中积累的规则与偏好，请严格遵守：",
        "",
    ]

    for rule in rules:
        parts.append("【规则文件：%s】" % rule["name"])
        parts.append(rule["content"])
        parts.append("")

    parts.append("=" * 40)
    parts.append("")

    return "\n".join(parts) + prompt


def record_feedback(content, category="用户纠正", commit=False):
    """把一条反馈追加到 rules/feedback.md。

    用户纠正 Agent 的行为后，用本函数记录下来，
    Agent 之后的任务会通过 inject_rules() 遵守这些规则。
    commit=True 时自动提交到 git。
    """

    config.RULES_DIR.mkdir(parents=True, exist_ok=True)

    path = config.RULES_DIR / "feedback.md"

    entry = (
        "\n## %s ｜ %s\n\n%s\n"
        % (datetime.now().isoformat(timespec="seconds"), category, content)
    )

    with open(path, "a", encoding="utf-8") as f:
        f.write(entry)

    if commit:
        _git_commit_rules()

    return str(path)


def _git_commit_rules():
    """把 rules 目录提交到 git（git 不可用时静默跳过）。"""

    try:
        subprocess.run(
            ["git", "add", str(config.RULES_DIR)],
            cwd=str(config.PROJECT_ROOT),
            check=True,
            capture_output=True,
        )
        subprocess.run(
            ["git", "commit", "-m", "记录用户反馈（Agent 成长）"],
            cwd=str(config.PROJECT_ROOT),
            check=True,
            capture_output=True,
        )
    except (subprocess.CalledProcessError, FileNotFoundError):
        # git 不可用不影响主流程
        pass
