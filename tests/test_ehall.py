"""
tools.ehall 的单元测试（网络全部 mock，不产生真实请求）。
"""

import os
import unittest
from unittest import mock

import httpx
import tools.ehall as ehall

from tests.helpers import TempDataDir

FORM_HTML = """
<html><body>
<select id="XMDM">
  <option value="">请选择</option>
  <option value="1001">水龙头</option>
  <option value="1002">空调</option>
</select>
<select id="QYDM">
  <option value="2001">仙林校区</option>
  <option value="2002">鼓楼校区</option>
</select>
</body></html>
"""

REPAIR_DATA = {
    "SJH": "13800000000",
    "XMDM": "水龙头/水龙头漏水",
    "QYDM": "仙林校区",
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


class TestFetchCodes(unittest.TestCase):

    def setUp(self):
        self._ctx = TempDataDir()
        self._ctx.__enter__()

    def tearDown(self):
        self._ctx.__exit__(None, None, None)

    def _resp(self, html):
        resp = mock.Mock()
        resp.text = html
        resp.raise_for_status = mock.Mock()
        return resp

    def test_fetch_and_cache(self):
        with mock.patch("tools.ehall.httpx.get",
                        return_value=self._resp(FORM_HTML)):
            codes = ehall.fetch_repair_codes(force=True)

        self.assertEqual(codes["XMDM"]["水龙头"], "1001")
        self.assertEqual(codes["QYDM"]["仙林校区"], "2001")

        # 缓存生效：不再请求网络
        with mock.patch("tools.ehall.httpx.get") as fake:
            codes2 = ehall.fetch_repair_codes()

        fake.assert_not_called()
        self.assertEqual(codes2, codes)

    def test_fetch_no_selects_raises(self):
        with mock.patch("tools.ehall.httpx.get",
                        return_value=self._resp("<html>无表单</html>")):
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
        """真实模式：文本换成字典码后提交。"""

        ehall.save_codes({
            "XMDM": {"水龙头/水龙头漏水": "1001"},
            "QYDM": {"仙林校区": "2001"},
        })

        resp = mock.Mock()
        resp.json.return_value = {"code": "0", "msg": "提交成功"}

        with mock.patch.dict(os.environ, {"EHALL_DRY_RUN": "0"}), \
             mock.patch("tools.ehall.httpx.post", return_value=resp) as fake:
            result = ehall.submit_repair(REPAIR_DATA)

        fake.assert_called_once()
        payload = fake.call_args.kwargs["data"]
        self.assertEqual(payload["XMDM"], "1001")
        self.assertEqual(payload["QYDM"], "2001")
        self.assertTrue(result["success"])
        self.assertEqual(result["message"], "提交成功")

    def test_real_submit_network_error(self):
        ehall.save_codes({
            "XMDM": {"水龙头/水龙头漏水": "1001"},
            "QYDM": {"仙林校区": "2001"},
        })

        with mock.patch.dict(os.environ, {"EHALL_DRY_RUN": "0"}), \
             mock.patch("tools.ehall.httpx.post",
                        side_effect=httpx.ConnectError("连接失败")):
            result = ehall.submit_repair(REPAIR_DATA)

        self.assertFalse(result["success"])
        self.assertIn("EHALL 请求失败", result["message"])


if __name__ == "__main__":
    unittest.main()
