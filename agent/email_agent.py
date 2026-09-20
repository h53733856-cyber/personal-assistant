from agent.llm import ask_llm_json


def analyze_email(email):
    """分析一封邮件，返回 JSON 字典（type/core/time/deadline/need_action/action）。"""

    prompt = f"""
你是我的个人助手。

请分析下面这封邮件。

邮件主题：
{email["subject"]}

发件人：
{email["sender"]}

时间：
{email["date"]}

正文：
{email["body"]}

请判断这封邮件是否要求收件人本人完成具体操作。

注意：
1. 只有邮件明确要求收件人完成某个具体操作时，need_action 才为 true。
2. 普通通知、课程安排变化、信息提醒、宣传内容，如果没有要求收件人完成具体操作，则 need_action 为 false。
3. 如果邮件只是“建议”做某件事情，而不是明确要求，也应该谨慎判断。
4. 活动开始时间和报名截止时间必须区分。
5. 只能使用邮件中明确出现的信息，不要自行编造。
6. 不要把邮件发送时间当成事件时间或截止时间。
7. 如果不存在某项信息，使用 null。
8. 如果邮件明确要求收件人转告、通知、提醒其他人，
   这也属于收件人需要完成的行动，need_action 应为 true。
9. 例如：
   “请互相转告”
   “请转告相关同学”
   “请通知其他同学”
   “请提醒相关人员”
   都属于需要行动。
10. “请知悉”“请周知”如果只是要求收件人知道信息，
    不需要实际执行其他操作，则 need_action 可以为 false。

必须严格按照下面的 JSON 格式返回：

{{
    "type": "邮件类型",
    "core": "用一句话概括邮件的核心事项",
    "time": "重要时间，没有则为 null",
    "deadline": "截止时间，没有则为 null",
    "need_action": true,
    "action": "需要用户完成的具体操作，没有则为 null"
}}

只返回 JSON，不要添加 Markdown，不要添加解释。
"""

    return ask_llm_json(prompt)
