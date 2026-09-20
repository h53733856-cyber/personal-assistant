"""
EHALL 工具
目前先实现宿舍报修的数据准备与接口定义。
真实提交功能后续接入。
"""

REPAIR_APPLY_API = "/modules/repairApply/repairApplyAdd.do"


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
    """构造宿舍报修表单数据"""

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


def submit_repair(data):
    """
    提交宿舍报修。

    当前暂不执行真实提交，避免在开发阶段产生实际事务。
    """
    return {
        "success": False,
        "message": "EHALL真实提交功能尚未接入",
        "data": data,
    }