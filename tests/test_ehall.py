"""
tools.ehall 的单元测试（网络全部 mock，不产生真实请求）。
"""

import json
import os
import unittest
from unittest import mock

import httpx
import tools.ehall as ehall

from tests.helpers import TempDataDir

# 模拟真实树接口的返回（pId -> rows）
TREE_XM = {
    "": [
        {"id": "01", "name": "水电类", "pId": "", "isParent": 1},
    ],
    "01": [
        {"id": "0111", "name": "水电类/水龙头跑冒滴漏",
         "pId": "01", "isParent": 0},
        {"id": "0115", "name": "水电类/水龙头松动",
         "pId": "01", "isParent": 0},
    ],
}

TREE_QY = {
    "": [
        {"id": "1", "name": "仙林校区", "pId": "", "isParent": 1},
    ],
    "1": [
        {"id": "1101", "name": "仙林校区/学生公寓一组团/仙林宿舍01幢",
         "pId": "1", "isParent": 0},
    ],
}

REPAIR_DATA = {
    "SJH": "13800000000",
    "XMDM": "水电类/水龙头跑冒滴漏",
    "QYDM": "仙林校区/学生公寓一组团/仙林宿舍01幢",
    "GZDD": "某宿舍楼某房间",
    "DZ_FBSMKSSJ": "2026-09-20 19:00",
    "DZ_FBSMJSSJ": "2026-09-20 21:00",
    "GZMS": "坏了",
    "BZ": "",
    "GZTP": "",
    "DZ_SSDW": "1",
}


class TestBuildRepairData(unittest.TestCase):

    def test_structure(self):
        data = ehall.build_repair_data(
            phone="13800000000",
            repair_type="水龙头",
            area="仙林校区",
            location="某宿舍楼",
            start_time="2026-09-20 19:00",
            end_time="2026-09-20 21:00",
            description="坏了",
        )

        self.assertEqual(data["SJH"], "13800000000")
        self.assertEqual(data["XMDM"], "水龙头")
        self.assertEqual(data["QYDM"], "仙林校区")
        self.assertEqual(data["DZ_SSDW"], "1")


class TestResolveCode(unittest.TestCase):

    CODES = {
        "XMDM": {"水龙头": "1001", "空调": "1002"},
        "QYDM": {"仙林校区": "2001"},
    }

    def test_exact(self):
        self.assertEqual(
            ehall.resolve_code("XMDM", "水龙头", self.CODES),
            "1001",
        )

    def test_label_contained_in_text(self):
        # "水龙头/水龙头漏水" 包含选项 "水龙头"
        self.assertEqual(
            ehall.resolve_code("XMDM", "水龙头/水龙头漏水", self.CODES),
            "1001",
        )

    def test_text_contained_in_label(self):
        self.assertEqual(
            ehall.resolve_code("QYDM", "仙林", self.CODES),
            "2001",
        )

    def test_not_found(self):
        self.assertIsNone(ehall.resolve_code("XMDM", "灯泡", self.CODES))

    def test_empty_text(self):
        self.assertEqual(ehall.resolve_code("XMDM", "", self.CODES), "")


def _fake_tree_post(url, **kwargs):
    """模拟真实树接口：按 pId 参数返回对应层级的行。"""
    pid = ""

    if "=" in kwargs.get("data", ""):
        pid = kwargs["data"].split("=", 1)[1]

    uuid = url.rsplit("/", 1)[-1].split(".")[0]
    tree = TREE_XM if uuid.startswith("64bfd69f") else TREE_QY

    resp = mock.Mock()
    resp.json.return_value = {
        "datas": {"code": {"rows": tree.get(pid, [])}},
        "code": "0",
    }
    resp.raise_for_status = mock.Mock()
    return resp


class TestFetchCodes(unittest.TestCase):

    def setUp(self):
        self._ctx = TempDataDir()
        self._ctx.__enter__()

    def tearDown(self):
        self._ctx.__exit__(None, None, None)

    def test_fetch_and_cache(self):
        with mock.patch("tools.ehall.httpx.post",
                        side_effect=_fake_tree_post):
            codes = ehall.fetch_repair_codes(force=True)

        # 只有叶子（isParent=0）进入字典，且名称是完整路径
        self.assertEqual(codes["XMDM"]["水电类/水龙头跑冒滴漏"], "0111")
        self.assertEqual(codes["QYDM"]["仙林校区/学生公寓一组团/仙林宿舍01幢"],
                         "1101")
        self.assertNotIn("水电类", codes["XMDM"])

        # 缓存生效：不再请求网络
        with mock.patch("tools.ehall.httpx.post") as fake:
            codes2 = ehall.fetch_repair_codes()

        fake.assert_not_called()
        self.assertEqual(codes2, codes)

    def test_fetch_empty_raises(self):
        def empty_post(url, **kwargs):
            resp = mock.Mock()
            resp.json.return_value = {"datas": {"code": {"rows": []}}}
            resp.raise_for_status = mock.Mock()
            return resp

        with mock.patch("tools.ehall.httpx.post", side_effect=empty_post):
            with self.assertRaises(ValueError):
                ehall.fetch_repair_codes(force=True)


class TestSubmitRepair(unittest.TestCase):

    def setUp(self):
        self._ctx = TempDataDir()
        self._ctx.__enter__()

    def tearDown(self):
        self._ctx.__exit__(None, None, None)

    def test_dry_run_default_no_network(self):
        """默认 EHALL_DRY_RUN=1：模拟成功，不发起网络请求。"""

        with mock.patch("tools.ehall.httpx.post") as fake:
            result = ehall.submit_repair(REPAIR_DATA)

        fake.assert_not_called()
        self.assertTrue(result["success"])
        self.assertTrue(result["dry_run"])
        self.assertIn("模拟提交", result["message"])

    def test_real_submit_missing_codes_fails(self):
        """真实模式但字典码匹配不上：明确失败，不提交。"""

        with mock.patch.dict(os.environ, {"EHALL_DRY_RUN": "0"}), \
             mock.patch("tools.ehall.httpx.post") as fake:
            result = ehall.submit_repair(REPAIR_DATA)

        fake.assert_not_called()
        self.assertFalse(result["success"])
        self.assertIn("无法匹配报修类型代码", result["message"])

    def test_real_submit_success(self):
        """真实模式：文本换成字典码后按 data=<JSON> 格式提交。"""

        ehall.save_codes({
            "XMDM": {"水电类/水龙头跑冒滴漏": "0111"},
            "QYDM": {"仙林校区/学生公寓一组团/仙林宿舍01幢": "1101"},
        })

        resp = mock.Mock()
        resp.json.return_value = {"code": "0", "msg": "提交成功"}

        with mock.patch.dict(os.environ, {"EHALL_DRY_RUN": "0"}), \
             mock.patch("tools.ehall.httpx.post", return_value=resp) as fake:
            result = ehall.submit_repair(REPAIR_DATA)

        fake.assert_called_once()

        # 请求体是表单编码的 data=<JSON字符串>
        sent = fake.call_args.kwargs["data"]
        self.assertIn("data", sent)
        payload = json.loads(sent["data"])
        self.assertEqual(payload["XMDM"], "0111")
        self.assertEqual(payload["QYDM"], "1101")
        self.assertTrue(result["success"])
        self.assertEqual(result["message"], "提交成功")

    def test_real_submit_ambiguous_codes_fails(self):
        """报修类型匹配到多个候选：明确失败并提示候选，不提交。"""

        ehall.save_codes({
            "XMDM": {
                "水电类/水龙头跑冒滴漏": "0111",
                "水电类/水龙头松动": "0115",
            },
            "QYDM": {"仙林校区/学生公寓一组团/仙林宿舍01幢": "1101"},
        })

        # "水龙头" 同时出现在两个选项里 → 有歧义
        data = dict(REPAIR_DATA, XMDM="水龙头")

        with mock.patch.dict(os.environ, {"EHALL_DRY_RUN": "0"}), \
             mock.patch("tools.ehall.httpx.post") as fake:
            result = ehall.submit_repair(data)

        fake.assert_not_called()
        self.assertFalse(result["success"])
        self.assertIn("无法匹配报修类型代码", result["message"])
        self.assertIn("水龙头跑冒滴漏", result["message"])

    def test_real_submit_network_error(self):
        ehall.save_codes({
            "XMDM": {"水电类/水龙头跑冒滴漏": "0111"},
            "QYDM": {"仙林校区/学生公寓一组团/仙林宿舍01幢": "1101"},
        })

        with mock.patch.dict(os.environ, {"EHALL_DRY_RUN": "0"}), \
             mock.patch("tools.ehall.httpx.post",
                        side_effect=httpx.ConnectError("连接失败")):
            result = ehall.submit_repair(REPAIR_DATA)

        self.assertFalse(result["success"])
        self.assertIn("EHALL 请求失败", result["message"])


if __name__ == "__main__":
    unittest.main()
