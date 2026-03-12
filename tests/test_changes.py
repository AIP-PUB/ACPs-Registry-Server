"""
测试 /changes API 端点
"""

import json
import pytest
from app.sync import api as api_module


class TestChangesAPI:
    """测试changes相关的API端点"""

    def test_no_data_returns_204(self, client, monkeypatch):
        """当没有数据时应返回204状态码和正确的headers"""

        def mock_get_changes(db, seq, limit, types):
            return [], 123

        monkeypatch.setattr(api_module, "get_changes", mock_get_changes)

        response = client.get("/changes")

        assert response.status_code == 204, "应返回204状态码表示无内容"
        assert response.headers.get("X-Next-Seq") == "123", "应设置正确的下一个序列号"
        assert response.text == "", "响应体应为空"

    def test_with_data_returns_ndjson(
        self, client, monkeypatch, dummy_envelope_factory
    ):
        """当有数据时应返回200状态码和NDJSON格式数据"""

        def mock_get_changes(db, seq, limit, types):
            return [
                dummy_envelope_factory({"id": 1}),
                dummy_envelope_factory({"id": 2}),
            ], 456

        monkeypatch.setattr(api_module, "get_changes", mock_get_changes)

        response = client.get("/changes")

        assert response.status_code == 200, "应返回200状态码"
        assert response.headers.get("X-Next-Seq") == "456", "应设置正确的下一个序列号"
        assert response.headers.get("content-type", "").startswith(
            "application/x-ndjson"
        ), "内容类型应为NDJSON"

        lines = [line for line in response.text.strip().splitlines() if line.strip()]
        assert len(lines) == 2, "应返回2行数据"
        assert json.loads(lines[0]) == {"id": 1}, "第一行数据应正确"
        assert json.loads(lines[1]) == {"id": 2}, "第二行数据应正确"

    @pytest.mark.parametrize(
        "requested_limit,max_limit,expected_limit",
        [
            (100, 5, 5),  # 请求超过最大限制
            (3, 5, 3),  # 请求在限制内
            (10, 10, 10),  # 请求等于限制
        ],
    )
    def test_limit_enforcement(
        self, client, monkeypatch, requested_limit, max_limit, expected_limit
    ):
        """测试limit参数的限制执行"""
        captured_params = {}

        def mock_get_changes(db, seq, limit, types):
            captured_params["limit"] = limit
            return [], 1

        monkeypatch.setattr(api_module, "get_changes", mock_get_changes)
        monkeypatch.setattr(api_module.settings, "DSP_CHANGES_MAX_LIMIT", max_limit)

        response = client.get("/changes", params={"limit": requested_limit})

        assert response.status_code == 204
        assert (
            captured_params["limit"] == expected_limit
        ), f"实际limit应为{expected_limit}，但得到{captured_params['limit']}"

    def test_zero_limit_uses_default(self, client, monkeypatch):
        """当limit为0或负数时应使用默认值"""
        captured_params = {}

        def mock_get_changes(db, seq, limit, types):
            captured_params["limit"] = limit
            return [], 1

        monkeypatch.setattr(api_module, "get_changes", mock_get_changes)
        monkeypatch.setattr(api_module.settings, "DSP_CHANGES_DEFAULT_LIMIT", 7)

        response = client.get("/changes", params={"limit": 0})

        assert response.status_code == 204
        assert captured_params["limit"] == 7, "应使用默认limit值"

    def test_types_parameter_parsing(self, client, monkeypatch):
        """测试types参数的解析"""
        captured_params = {}

        def mock_get_changes(db, seq, limit, types):
            captured_params["types"] = types
            return [], 1

        monkeypatch.setattr(api_module, "get_changes", mock_get_changes)

        response = client.get("/changes", params={"types": "a, b, c"})

        assert response.status_code == 204
        assert captured_params["types"] == ["a", "b", "c"], "types参数应正确解析为列表"

    def test_wait_parameter_timeout(self, client, monkeypatch):
        """测试wait参数触发超时"""

        def mock_get_changes(db, seq, limit, types):
            return [], 99

        monkeypatch.setattr(api_module, "get_changes", mock_get_changes)

        response = client.get("/changes", params={"wait": "2"})

        assert response.status_code == 204, "超时后应返回204"
        assert response.headers.get("X-Next-Seq") == "99", "应设置正确的序列号"

    def test_unexpected_error_handling(self, client, monkeypatch):
        """测试意外错误的处理"""

        def mock_get_changes(db, seq, limit, types):
            raise Exception("boom")

        monkeypatch.setattr(api_module, "get_changes", mock_get_changes)

        response = client.get("/changes")

        assert response.status_code == 500, "意外错误应返回500状态码"

        data = response.json()
        assert (
            data["error"] == api_module.SyncError.CHANGES_QUERY_FAILED
        ), "应返回正确的错误代码"
        assert "Failed to get changes" in data["message"], "错误消息应包含失败信息"

    def test_sync_exception_propagation(self, client, monkeypatch):
        """测试SyncException异常的传播"""

        def mock_get_changes(db, seq, limit, types):
            raise api_module.SyncException(
                status_code=418,
                error_name="MY_SYNC_ERR",
                error_msg="sync fail",
                input_params={"foo": "bar"},
            )

        monkeypatch.setattr(api_module, "get_changes", mock_get_changes)

        response = client.get("/changes")

        assert response.status_code == 418, "应返回SyncException指定的状态码"

        data = response.json()
        assert data["error"] == "MY_SYNC_ERR", "应返回正确的错误名称"
        assert data["message"] == "sync fail", "应返回正确的错误消息"
        assert data["input_params"] == {"foo": "bar"}, "应返回正确的输入参数"
