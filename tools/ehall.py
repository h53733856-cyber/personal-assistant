"""
EHALL 工具：宿舍报修的数据准备与提交。

接口来自对报修应用（ssbxapp，金智 EMAP 平台）的真实分析：
- 表单模型：POST /xsfw/sys/ssbxapp/modules/wybx.do
- 报修类型树：POST /xsfw/code/64bfd69f-....do（pId 递归取子节点）
- 报修区域树：POST /xsfw/code/281e295f-....do（pId 递归取子节点）
- 提交：POST /xsfw/sys/ssbxapp/modules/repairApply/repairApplyAdd.do
  请求体：data=<JSON字符串>（表单编码），成功判定 code=="0"

安全设计：
- EHALL_DRY_RUN=1（默认）：模拟提交，不产生真实报修单
- EHALL_DRY_RUN=0：真实提交（必须先人工确认，字典码可解析）
- 登录凭据：浏览器 Cookie（环境变量 EHALL_COOKIE），
  你自己在浏览器登录 EHALL 后把 Cookie 粘贴进 .env
- 字典码缓存到 data/ehall_codes.json，供 AI 选择和提交解析

.env 相关配置：
    EHALL_COOKIE=xxx
    EHALL_DRY_RUN=1        # 1 模拟（默认），0 真实提交
    EHALL_BASE=https://ehallapp.nju.edu.cn
"""

import json
import os

import httpx
from dotenv import load_dotenv

import config

# 读取项目目录下的 .env（EHALL_COOKIE 等）
load_dotenv()

EHALL_BASE = os.getenv("EHALL_BASE", "https://ehallapp.nju.edu.cn")

# 真实提交接口
REPAIR_APPLY_API = "/xsfw/sys/ssbxapp/modules/repairApply/repairApplyAdd.do"

# 报修类型（XMDM）/ 报修区域（QYDM）的字典树接口
CODE_XMDM_URL = "/xsfw/code/64bfd69f-dc69-413d-b2de-33b99c8861f9.do"
CODE_QYDM_URL = "/xsfw/code/281e295f-7060-44bf-b114-28c0d9e2f63e.do"

REFERER = EHALL_BASE + "/xsfw/sys/ssbxapp/*default/index.do"

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0 Safari/537.36"
)


def _headers():
    return {
        "Cookie": os.getenv("EHALL_COOKIE", ""),
        "User-Agent": USER_AGENT,
        "X-Requested-With": "XMLHttpRequest",
        "Origin": EHALL_BASE,
        "Referer": REFERER,
        "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
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
    """构造宿舍报修表单数据（字段与真实表单一致）。"""

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


def _fetch_tree(url):
    """递归抓取一棵选项树，返回 {叶子完整名称: 代码}。

    树接口：POST pId=<父节点ID>，pId 为空时返回根节点；
    isParent=1 的节点继续用它的 id 抓子节点。
    """

    leaves = {}
    queue = [""]

    while queue:

        pid = queue.pop(0)

        resp = httpx.post(
            EHALL_BASE + url,
            headers=_headers(),
            data="pId=" + pid,
            timeout=30,
            follow_redirects=True,
        )
        resp.raise_for_status()

        data = resp.json()
        rows = data.get("datas", {}).get("code", {}).get("rows", [])

        for row in rows:

            if row.get("isParent"):
                queue.append(row["id"])
            else:
                leaves[row["name"]] = row["id"]

    return leaves


def fetch_repair_codes(force=False):
    """抓取报修类型（XMDM）/ 报修区域（QYDM）的完整选项代码并缓存。

    默认优先使用本地缓存；force=True 时重新抓取。
    返回 {"XMDM": {label: code}, "QYDM": {label: code}}。
    """

    if not force:

        cached = load_codes()

        if cached:
            return cached

    codes = {
        "XMDM": _fetch_tree(CODE_XMDM_URL),
        "QYDM": _fetch_tree(CODE_QYDM_URL),
    }

    if not codes["XMDM"] or not codes["QYDM"]:
        raise ValueError(
            "没有抓取到报修选项。"
            "请确认 .env 里配置了 EHALL_COOKIE（浏览器登录 EHALL 后粘贴）。"
        )

    save_codes(codes)

    return codes


def get_code_labels(kind):
    """返回某类字典的全部选项名称（供 AI 从真实选项中选择）。"""

    return list(load_codes().get(kind, {}).keys())


def resolve_code(kind, text, codes=None):
    """把人类文本匹配成字典码。

    匹配顺序：完全相等 → 选项名称出现在文本里（唯一时）→
    文本出现在选项名称里（唯一时）。
    有歧义或找不到时返回 None（提交前会明确报错，不会提交错误数据）。
    """

    if not text:
        return ""

    if codes is None:
        codes = load_codes()

    mapping = codes.get(kind, {})

    if text in mapping:
        return mapping[text]

    contains = {k: v for k, v in mapping.items() if k and k in text}

    if len(contains) == 1:
        return next(iter(contains.values()))

    if len(contains) > 1:
        return None

    contained = {k: v for k, v in mapping.items() if k and text in k}

    if len(contained) == 1:
        return next(iter(contained.values()))

    return None


def code_candidates(kind, text, codes=None):
    """返回与文本相关的候选选项名称（用于报错提示）。"""

    if codes is None:
        codes = load_codes()

    mapping = codes.get(kind, {})

    return [k for k in mapping if k and (text in k or k in text)][:8]


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

    xmdm_text = payload.get("XMDM", "")
    qydm_text = payload.get("QYDM", "")

    xmdm = resolve_code("XMDM", xmdm_text, codes)
    qydm = resolve_code("QYDM", qydm_text, codes)

    if not xmdm:
        candidates = code_candidates("XMDM", xmdm_text, codes)
        message = "无法匹配报修类型代码：%s" % xmdm_text

        if candidates:
            message += "。接近的选项：" + "、".join(candidates)

        return {"success": False, "message": message}

    if not qydm:
        candidates = code_candidates("QYDM", qydm_text, codes)
        message = "无法匹配报修区域代码：%s" % qydm_text

        if candidates:
            message += "。接近的选项：" + "、".join(candidates)

        return {"success": False, "message": message}

    payload["XMDM"] = xmdm
    payload["QYDM"] = qydm

    # ==============================
    # 真实 POST（表单编码，data=<JSON字符串>）
    # ==============================

    try:
        resp = httpx.post(
            EHALL_BASE + REPAIR_APPLY_API,
            data={"data": json.dumps(payload, ensure_ascii=False)},
            headers=_headers(),
            timeout=60,
            follow_redirects=True,
        )
    except httpx.HTTPError as e:
        return {
            "success": False,
            "message": "EHALL 请求失败：" + str(e),
        }

    try:
        result = resp.json()
    except ValueError:
        text = resp.text

        if "成功" in text and "失败" not in text:
            return {"success": True, "message": "提交成功"}

        return {
            "success": False,
            "message": "提交结果无法确认，请到 EHALL 查看报修记录",
            "response_text": text[:500],
        }

    code = str(result.get("code", ""))

    success = code == "0"

    message = str(
        result.get("msg")
        or result.get("description")
        or result.get("message")
        or ("提交成功" if success else "提交失败")
    )

    return {"success": success, "message": message, "response": result}
