"""
测试 /snapshots API 端点
"""

import json
import pytest
from app.sync import api as api_module


class TestSnapshotsAPI:
    """测试snapshots相关的API端点"""

    def test_create_snapshot_success(
        self, client, monkeypatch, snapshot_factory, dummy_envelope_factory
    ):
        """测试成功创建快照"""

        def mock_create_snapshot(db, types, limit, from_seq):
            snapshot = snapshot_factory(
                snapshot_id="snap-new", seq=456, chunk_total=3, object_count=10
            )
            envelopes = [
                dummy_envelope_factory({"id": "obj-1", "type": "acs"}),
                dummy_envelope_factory({"id": "obj-2", "type": "acs"}),
            ]
            return snapshot, envelopes

        monkeypatch.setattr(api_module, "create_snapshot", mock_create_snapshot)

        response = client.get("/snapshots", params={"types": "acs", "limit": 2})

        # 验证响应状态码和headers
        assert response.status_code == 200, "创建快照应返回200状态码"
        assert response.headers.get("X-Snapshot-Id") == "snap-new", "应设置正确的快照ID"
        assert response.headers.get("X-Snapshot-Seq") == "456", "应设置正确的快照序列号"
        assert (
            response.headers.get("X-Snapshot-Chunk-Index") == "0"
        ), "应设置正确的分块索引"
        assert (
            response.headers.get("X-Snapshot-Chunk-Total") == "3"
        ), "应设置正确的总分块数"
        assert (
            response.headers.get("X-Snapshot-Object-Count") == "10"
        ), "应设置正确的对象数量"
        assert response.headers.get("content-type", "").startswith(
            "application/x-ndjson"
        ), "内容类型应为NDJSON"

        # 验证响应体
        lines = [line for line in response.text.strip().splitlines() if line.strip()]
        assert len(lines) == 2, "应返回2行数据"
        assert json.loads(lines[0]) == {
            "id": "obj-1",
            "type": "acs",
        }, "第一行数据应正确"
        assert json.loads(lines[1]) == {
            "id": "obj-2",
            "type": "acs",
        }, "第二行数据应正确"

    @pytest.mark.parametrize(
        "params,expected_status",
        [
            ({}, 400),  # 缺少types和id
            ({"types": "unknown"}, 400),  # 不支持的类型
            ({"id": "snap-1"}, 400),  # 提供id但缺少chunk
        ],
    )
    def test_create_snapshot_validation_errors(self, client, params, expected_status):
        """测试创建快照的各种验证错误"""
        response = client.get("/snapshots", params=params)
        assert (
            response.status_code == expected_status
        ), f"参数{params}应返回状态码{expected_status}"

    def test_get_snapshot_chunk_success(
        self, client, monkeypatch, snapshot_factory, dummy_envelope_factory
    ):
        """测试成功获取快照分块"""

        def mock_get_snapshot_chunk(db, snapshot_id, chunk_index, limit):
            assert snapshot_id == "snap-1", "快照ID应正确传递"
            assert chunk_index == 0, "分块索引应正确传递"

            snapshot = snapshot_factory(
                snapshot_id="snap-1", seq=789, chunk_total=5, object_count=20
            )
            envelopes = [
                dummy_envelope_factory({"id": "obj-A", "type": "acs"}),
                dummy_envelope_factory({"id": "obj-B", "type": "acs"}),
            ]
            return snapshot, envelopes

        monkeypatch.setattr(api_module, "get_snapshot_chunk", mock_get_snapshot_chunk)

        response = client.get(
            "/snapshots", params={"id": "snap-1", "chunk": 0, "limit": 2}
        )

        # 验证响应
        assert response.status_code == 200, "获取快照分块应返回200状态码"
        assert response.headers.get("X-Snapshot-Id") == "snap-1", "应返回正确的快照ID"
        assert response.headers.get("X-Snapshot-Seq") == "789", "应返回正确的快照序列号"
        assert (
            response.headers.get("X-Snapshot-Chunk-Index") == "0"
        ), "应返回正确的分块索引"
        assert (
            response.headers.get("X-Snapshot-Chunk-Total") == "5"
        ), "应返回正确的总分块数"
        assert (
            response.headers.get("X-Snapshot-Object-Count") == "20"
        ), "应返回正确的对象数量"
        assert response.headers.get("content-type", "").startswith(
            "application/x-ndjson"
        ), "内容类型应为NDJSON"

        lines = [line for line in response.text.strip().splitlines() if line.strip()]
        assert len(lines) == 2, "应返回2行数据"
        assert json.loads(lines[0]) == {
            "id": "obj-A",
            "type": "acs",
        }, "第一行数据应正确"
        assert json.loads(lines[1]) == {
            "id": "obj-B",
            "type": "acs",
        }, "第二行数据应正确"


class TestSnapshotDeletion:
    """测试快照删除功能"""

    def test_delete_snapshot_success(self, client, monkeypatch):
        """测试成功删除快照"""

        def mock_delete_snapshot(db, snapshot_id):
            assert snapshot_id == "snap-1", "快照ID应正确传递"
            return True

        monkeypatch.setattr(api_module, "delete_snapshot", mock_delete_snapshot)

        response = client.delete("/snapshots/snap-1")

        assert response.status_code == 204, "删除成功应返回204状态码"
        assert response.text == "", "删除成功的响应体应为空"

    def test_delete_snapshot_failure(self, client, monkeypatch):
        """测试删除快照失败"""

        def mock_delete_snapshot(db, snapshot_id):
            return False

        monkeypatch.setattr(api_module, "delete_snapshot", mock_delete_snapshot)

        response = client.delete("/snapshots/snap-err")

        assert response.status_code == 500, "删除失败应返回500状态码"


class TestSnapshotCleanup:
    """测试快照清理功能"""

    def test_cleanup_snapshots(self, client, monkeypatch):
        """测试清理过期快照"""

        def mock_cleanup_expired_snapshots(db):
            return 3

        monkeypatch.setattr(
            api_module, "cleanup_expired_snapshots", mock_cleanup_expired_snapshots
        )

        response = client.post("/admin/snapshots/cleanup")

        assert response.status_code == 200, "清理操作应返回200状态码"
        assert response.json() == {"cleaned_count": 3}, "应返回正确的清理数量"
