"""
EHALL 工具：宿舍报修的数据准备与提交。

安全设计：
- EHALL_DRY_RUN=1（默认）：模拟提交，不产生真实报修单
- EHALL_DRY_RUN=0：真实提交（必须先人工确认，且字典码可解析）
- 登录凭据：浏览器 Cookie（环境变量 EHALL_COOKIE），
  你自己在浏览器登录 EHALL 后把 Cookie 粘贴进 .env
- 字典码：报修类型（XMDM）/ 报修区域（QYDM）的选项代码
  用 Cookie 抓取报修表单页自动解析，缓存到 data/ehall_codes.json

.env 相关配置：
    EHALL_COOKIE=xxx
    EHALL_DRY_RUN=1        # 1 模拟（默认），0 真实提交
    EHALL_BASE=https://ehall.nju.edu.cn
    EHALL_REPAIR_FORM=/modules/repairApply/repairApply.do
"""

import json
import os

import httpx
from bs4 import BeautifulSoup

import config

EHALL_BASE = os.getenv("EHALL_BASE", "https://ehall.nju.edu.cn")

# 真实提交接口（此前分析出的地址）
REPAIR_APPLY_API = "/modules/repairApply/repairApplyAdd.do"

# 报修表单页面（用于抓取字典码）
REPAIR_FORM_PAGE = os.getenv(
    "EHALL_REPAIR_FORM",
    "/modules/repairApply/repairApply.do",
)

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0 Safari/537.36"
)


def _headers():
    return {
        "Cookie": os.getenv("EHALL_COOKIE", ""),
        "User-Agent": USER_AGENT,
    }


def _is_dry_run():
    return os.getenv("EHALL_DRY_RUN", "1") != "0"


# --------------------------------------------------
# 表单数据构造
# --------------------------------------------------

def build_repair_data(
    phone,
    repair_type,
    area,
    location,
    start_time,
    end_time,
    description,
    remark="",
    image="",
):
    """构造宿舍报修表单数据。"""

    return {
        "SJH": phone,
        "XMDM": repair_type,
        "QYDM": area,
        "GZDD": location,
        "DZ_FBSMKSSJ": start_time,
        "DZ_FBSMJSSJ": end_time,
        "GZMS": description,
        "BZ": remark,
        "GZTP": image,
        "DZ_SSDW": "1",
    }


# --------------------------------------------------
# 字典码（报修类型 / 报修区域）
# --------------------------------------------------

def load_codes():
    """读取缓存的字典码 {XMDM: {label: code}, QYDM: {label: code}}。"""

    if not os.path.exists(config.EHALL_CODES_FILE):
        return {}

    with open(config.EHALL_CODES_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def save_codes(codes):
    config.EHALL_CODES_FILE.parent.mkdir(parents=True, exist_ok=True)

    with open(config.EHALL_CODES_FILE, "w", encoding="utf-8") as f:
        json.dump(codes, f, ensure_ascii=False, indent=4)


def _classify_select(select):
    """根据下拉框的 id/name 和选项文本猜测它是类型还是区域。"""

    select_id = (select.get("id") or select.get("name") or "").upper()

    if "XM" in select_id:
        return "xm"

    if "QY" in select_id:
        return "qy"

    texts = " ".join(
        o.get_text(strip=True) for o in select.find_all("option")
    )

    if ("校区" in texts) or ("宿舍" in texts) or ("楼" in texts):
        return "qy"

    return "xm"


def fetch_repair_codes(force=False):
    """抓取报修类型（XMDM）/ 报修区域（QYDM）的选项代码并缓存。

    默认优先使用本地缓存；force=True 时重新抓取。
    返回 {"XMDM": {label: code}, "QYDM": {label: code}}。
    """

    if not force:

        cached = load_codes()

        if cached:
            return cached

    resp = httpx.get(
        EHALL_BASE + REPAIR_FORM_PAGE,
        headers=_headers(),
        timeout=30,
        follow_redirects=True,
    )
    resp.raise_for_status()

    soup = BeautifulSoup(resp.text, "html.parser")

    codes = {}

    for select in soup.find_all("select"):

        kind = _classify_select(select)

        mapping = {}

        for option in select.find_all("option"):

            value = option.get("value", "")
            label = option.get_text(strip=True)

            if value and label and label != "请选择":
                mapping[label] = value

        if mapping:
            codes.setdefault(
                "QYDM" if kind == "qy" else "XMDM", {}
            ).update(mapping)

    if not codes:
        raise ValueError(
            "没有解析到报修表单的下拉选项。"
            "请确认 .env 里配置了 EHALL_COOKIE（浏览器登录 EHALL 后粘贴）。"
        )

    save_codes(codes)

    return codes


def resolve_code(kind, text, codes=None):
    """把人类文本匹配成字典码。

    匹配顺序：完全相等 → 选项标签出现在文本里 → 文本出现在选项标签里。
    找不到时返回 None。
    """

    if not text:
        return ""

    if codes is None:
        codes = load_codes()

    mapping = codes.get(kind, {})

    if text in mapping:
        return mapping[text]

    # 例如 "水龙头/水龙头漏水" 包含选项 "水龙头"
    matches = [v for k, v in mapping.items() if k and k in text]

    if len(matches) == 1:
        return matches[0]

    # 选项标签包含文本，例如 "仙林校区" 包含 "仙林"
    matches = [v for k, v in mapping.items() if k and text in k]

    if len(matches) == 1:
        return matches[0]

    return None


# --------------------------------------------------
# 提交
# --------------------------------------------------

def submit_repair(data):
    """提交宿舍报修。

    EHALL_DRY_RUN=1（默认）：模拟提交，不产生真实报修单。
    EHALL_DRY_RUN=0：真实提交。
    """

    payload = dict(data)

    if _is_dry_run():

        return {
            "success": True,
            "message": "模拟提交成功（EHALL_DRY_RUN=1，未真正提交到 EHALL）",
            "data": payload,
            "dry_run": True,
        }

    # ==============================
    # 真实提交：人类文本 → 字典码
    # ==============================

    codes = load_codes()

    xmdm = resolve_code("XMDM", payload.get("XMDM", ""), codes)
    qydm = resolve_code("QYDM", payload.get("QYDM", ""), codes)

    if not xmdm:
        return {
            "success": False,
            "message": "无法匹配报修类型代码：%s"
                       "（请到数据管理更新 EHALL 字典）"
                       % payload.get("XMDM", ""),
        }

    if not qydm:
        return {
            "success": False,
            "message": "无法匹配报修区域代码：%s"
                       "（请到数据管理更新 EHALL 字典）"
                       % payload.get("QYDM", ""),
        }

    payload["XMDM"] = xmdm
    payload["QYDM"] = qydm

    # ==============================
    # 真实 POST
    # ==============================

    try:
        resp = httpx.post(
            EHALL_BASE + REPAIR_APPLY_API,
            data=payload,
            headers=_headers(),
            timeout=60,
            follow_redirects=True,
        )
    except httpx.HTTPError as e:
        return {
            "success": False,
            "message": "EHALL 请求失败：" + str(e),
        }

    # 优先按 JSON 解析
    try:
        result = resp.json()

        if isinstance(result, dict):
            code = str(
                result.get("code", result.get("success", ""))
            )
            success = code in ("0", "1", "True", "true", "200")

            return {
                "success": success,
                "message": str(
                    result.get("msg")
                    or result.get("message")
                    or "提交完成"
                ),
                "response": result,
            }
    except ValueError:
        pass

    # 退回按 HTML 提示判断
    text = resp.text

    if "成功" in text and "失败" not in text:
        return {"success": True, "message": "提交成功"}

    return {
        "success": False,
        "message": "提交结果无法确认，请到 EHALL 查看报修记录",
        "response_text": text[:500],
    }
