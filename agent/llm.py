import json
import os

from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

client = OpenAI(
    api_key=os.getenv("DEEPSEEK_API_KEY"),
    base_url="https://api.deepseek.com",
    timeout=60,
)

MODEL = "deepseek-chat"


def ask_llm(message):
    """单轮调用 DeepSeek，返回模型回复文本。"""

    response = client.chat.completions.create(
        model=MODEL,
        messages=[
            {
                "role": "user",
                "content": message
            }
        ]
    )

    return response.choices[0].message.content


def _extract_json_block(text):
    """从文本中截取第一个 { 到最后一个 }。"""

    start = text.find("{")
    end = text.rfind("}")

    if start == -1 or end == -1 or end <= start:
        return None

    return text[start:end + 1]


def ask_llm_json(message, max_retries=2):
    """调用 LLM 并解析为 JSON 字典。

    容错处理：
    1. 去掉模型可能添加的 Markdown 代码围栏（```json ... ```）。
    2. 从回复中截取第一个 { 到最后一个 }。
    3. 解析失败时，把错误反馈给模型并重试（最多 max_retries 次）。

    全部失败时抛出 ValueError。
    """

    last_error = None

    for attempt in range(max_retries + 1):

        raw = ask_llm(message)
        raw = raw.strip()

        # 先尝试直接解析
        try:
            return json.loads(raw)
        except json.JSONDecodeError as e:
            last_error = e

        # 再尝试去掉围栏 / 截取 JSON 块
        extracted = _extract_json_block(raw)

        if extracted is not None:
            try:
                return json.loads(extracted)
            except json.JSONDecodeError as e:
                last_error = e

        # 还有重试机会，把错误反馈给模型
        if attempt < max_retries:
            message += (
                "\n\n注意：你上一次的回复无法解析为 JSON"
                f"（错误：{last_error}）。"
                "请重新只输出合法 JSON，不要添加 Markdown，不要添加解释。"
            )

    raise ValueError(
        "LLM 多次返回无法解析的 JSON：" + str(last_error)
    )
