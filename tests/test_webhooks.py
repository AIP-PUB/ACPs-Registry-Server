"""
测试 /webhooks 相关的API端点与服务层批处理行为
"""

import json
import time
import pytest

from app.sync import api as api_module
from app.sync import service as service_module


class _DummyWebHook:
    def __init__(
        self,
        id="wh_1",
        url="https://example.com/hook",
        types="acs",
        events="data_change",
        description="demo",
        status="active",
        failure_count=0,
        last_triggered_at=None,
        last_success_at=None,
        last_failure_at=None,
        next_retry_at=None,
        created_at=None,
        updated_at=None,
    ):
        from datetime import datetime

        self.id = id
        self.url = url
        self.types = types
        self.events = events
        self.description = description
        self.status = status
        self.failure_count = failure_count
        self.last_triggered_at = last_triggered_at
        self.last_success_at = last_success_at
        self.last_failure_at = last_failure_at
        self.next_retry_at = next_retry_at
        self.created_at = created_at or datetime.now()
        self.updated_at = updated_at or datetime.now()


class TestWebhooksAPI:
    """测试webhooks相关的API端点"""

    def test_create_webhook_success(self, client, monkeypatch):
        """成功创建webhook返回201与正确数据"""

        def mock_create_webhook(db, url, secret, types, events, description):
            assert url == "https://cb.example/hook"
            assert secret == "sec"
            assert types == ["acs"]
            assert events == ["data_change", "service_healthy"]
            return _DummyWebHook(
                id="wh_new",
                url=url,
                types=",".join(types),
                events=",".join(events),
                description=description,
                status="active",
                failure_count=0,
            )

        monkeypatch.setattr(api_module, "create_webhook", mock_create_webhook)

        payload = {
            "url": "https://cb.example/hook",
            "secret": "sec",
            "types": ["acs"],
            "events": ["data_change", "service_healthy"],
            "description": "desc",
        }

        resp = client.post("/webhooks", json=payload)
        assert resp.status_code == 201
        data = resp.json()
        assert data["id"] == "wh_new"
        assert data["url"] == payload["url"]
        assert data["types"] == ["acs"]
        assert set(data["events"]) == {"data_change", "service_healthy"}
        assert data["description"] == "desc"
        assert data["status"] == "active"
        assert data["failure_count"] == 0

    @pytest.mark.parametrize(
        "payload,expected_error",
        [
            (
                {
                    "url": "https://cb.example/hook",
                    "secret": "s",
                    "types": ["unknown"],
                    "events": ["data_change"],
                },
                api_module.SyncError.WEBHOOK_INVALID_TYPES,
            ),
            (
                {
                    "url": "https://cb.example/hook",
                    "secret": "s",
                    "types": ["acs"],
                    "events": ["bad_event"],
                },
                api_module.SyncError.WEBHOOK_INVALID_EVENTS,
            ),
        ],
    )
    def test_create_webhook_validation_errors(self, client, payload, expected_error):
        """类型或事件校验失败应返回400并包含错误码"""
        resp = client.post("/webhooks", json=payload)
        assert resp.status_code == 400
        data = resp.json()
        assert data["error"] == expected_error

    def test_create_webhook_unexpected_error(self, client, monkeypatch):
        """底层抛出异常应返回500并包含错误码"""

        def boom(*args, **kwargs):
            raise Exception("boom")

        monkeypatch.setattr(api_module, "create_webhook", boom)

        payload = {
            "url": "https://cb.example/hook",
            "secret": "s",
            "types": ["acs"],
            "events": ["data_change"],
        }
        resp = client.post("/webhooks", json=payload)
        assert resp.status_code == 500
        assert resp.json()["error"] == api_module.SyncError.WEBHOOK_CREATE_FAILED

    def test_get_webhook_success(self, client, monkeypatch):
        """获取单个webhook成功"""

        def mock_get(db, webhook_id):
            assert webhook_id == "wh_1"
            return _DummyWebHook(id="wh_1")

        monkeypatch.setattr(api_module, "get_webhook", mock_get)

        resp = client.get("/webhooks/wh_1")
        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] == "wh_1"
        assert data["types"] == ["acs"]
        assert data["events"] == ["data_change"]

    def test_get_webhook_unexpected_error(self, client, monkeypatch):
        def boom(*args, **kwargs):
            raise Exception("x")

        monkeypatch.setattr(api_module, "get_webhook", boom)
        resp = client.get("/webhooks/wh_x")
        assert resp.status_code == 500
        assert resp.json()["error"] == api_module.SyncError.WEBHOOK_QUERY_FAILED

    def test_get_webhook_sync_exception(self, client, monkeypatch):
        def raise_sync(*args, **kwargs):
            raise api_module.SyncException(
                status_code=418,
                error_name="TEAPOT",
                error_msg="i am teapot",
                input_params={},
            )

        monkeypatch.setattr(api_module, "get_webhook", raise_sync)
        resp = client.get("/webhooks/wh_teapot")
        assert resp.status_code == 418
        data = resp.json()
        assert data["error"] == "TEAPOT"
        assert data["message"] == "i am teapot"

    def test_update_webhook_success(self, client, monkeypatch):
        def mock_update(db, webhook_id, url, secret, types, events, description):
            assert webhook_id == "wh_1"
            assert types == ["acs"]
            assert events == ["service_healthy"]
            return _DummyWebHook(
                id=webhook_id,
                url=url or "https://example.com/hook",
                types=",".join(types) if types else "",
                events=",".join(events) if events else "",
                description=description,
            )

        monkeypatch.setattr(api_module, "update_webhook", mock_update)

        payload = {
            "types": ["acs"],
            "events": ["service_healthy"],
            "description": "updated",
        }
        resp = client.put("/webhooks/wh_1", json=payload)
        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] == "wh_1"
        assert data["types"] == ["acs"]
        assert data["events"] == ["service_healthy"]
        assert data["description"] == "updated"

    @pytest.mark.parametrize(
        "payload,expected_error",
        [
            ({"types": ["bad"]}, api_module.SyncError.WEBHOOK_INVALID_TYPES),
            ({"events": ["bad_event"]}, api_module.SyncError.WEBHOOK_INVALID_EVENTS),
        ],
    )
    def test_update_webhook_validation_errors(self, client, payload, expected_error):
        resp = client.put("/webhooks/wh_v", json=payload)
        assert resp.status_code == 400
        assert resp.json()["error"] == expected_error

    def test_update_webhook_unexpected_error(self, client, monkeypatch):
        def boom(*args, **kwargs):
            raise Exception("xx")

        monkeypatch.setattr(api_module, "update_webhook", boom)
        resp = client.put("/webhooks/wh_e", json={"types": ["acs"]})
        assert resp.status_code == 500
        assert resp.json()["error"] == api_module.SyncError.WEBHOOK_UPDATE_FAILED

    def test_delete_webhook_success(self, client, monkeypatch):
        def ok(db, webhook_id):
            assert webhook_id == "wh_1"
            return True

        monkeypatch.setattr(api_module, "delete_webhook", ok)
        resp = client.delete("/webhooks/wh_1")
        assert resp.status_code == 204
        assert resp.text == ""

    def test_delete_webhook_failure(self, client, monkeypatch):
        def not_ok(db, webhook_id):
            return False

        monkeypatch.setattr(api_module, "delete_webhook", not_ok)
        resp = client.delete("/webhooks/wh_fail")
        assert resp.status_code == 500
        assert resp.json()["error"] == api_module.SyncError.WEBHOOK_DELETE_FAILED

    def test_delete_webhook_unexpected_error(self, client, monkeypatch):
        def boom(*args, **kwargs):
            raise Exception("oops")

        monkeypatch.setattr(api_module, "delete_webhook", boom)
        resp = client.delete("/webhooks/wh_err")
        assert resp.status_code == 500
        assert resp.json()["error"] == api_module.SyncError.WEBHOOK_DELETE_FAILED

    def test_reactivate_webhook_success(self, client, monkeypatch):
        def mock_reactivate(db, webhook_id):
            assert webhook_id == "wh_dead"
            return _DummyWebHook(id=webhook_id, status="active")

        monkeypatch.setattr(api_module, "reactivate_webhook", mock_reactivate)
        resp = client.post("/webhooks/wh_dead/reactivate")
        assert resp.status_code == 200
        assert resp.json()["id"] == "wh_dead"
        assert resp.json()["status"] == "active"

    def test_reactivate_webhook_unexpected_error(self, client, monkeypatch):
        def boom(*args, **kwargs):
            raise Exception("bad")

        monkeypatch.setattr(api_module, "reactivate_webhook", boom)
        resp = client.post("/webhooks/wh_dead/reactivate")
        assert resp.status_code == 500
        assert resp.json()["error"] == api_module.SyncError.WEBHOOK_REACTIVATE_FAILED

    def test_list_webhooks_success(self, client, monkeypatch):
        def mock_list(db, page_num, page_size, status_filter):
            items = [
                _DummyWebHook(id="wh_1", url="u1", types="acs", events="data_change"),
                _DummyWebHook(
                    id="wh_2", url="u2", types="acs", events="service_healthy"
                ),
            ]
            return items, 2

        monkeypatch.setattr(api_module, "get_webhook_list", mock_list)

        resp = client.get("/webhooks", params={"page_num": 1, "page_size": 10})
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 2
        assert len(data["items"]) == 2
        assert data["items"][0]["id"] == "wh_1"
        assert data["items"][0]["types"] == ["acs"]
        assert data["items"][0]["events"] == ["data_change"]

    def test_list_webhooks_unexpected_error(self, client, monkeypatch):
        def boom(*args, **kwargs):
            raise Exception("err")

        monkeypatch.setattr(api_module, "get_webhook_list", boom)
        resp = client.get("/webhooks")
        assert resp.status_code == 500
        assert resp.json()["error"] == api_module.SyncError.WEBHOOK_QUERY_FAILED


class TestWebhookBatching:
    """测试 data_change 批处理窗口聚合与触发行为"""

    def _reset_batch_state(self, monkeypatch):
        monkeypatch.setattr(
            service_module,
            "_data_change_batch_state",
            {"types": set(), "max_seq": None, "timer": None},
            raising=False,
        )

    def _stub_session_local(self, monkeypatch):
        class _DummySession:
            def __enter__(self):
                return object()

            def __exit__(self, exc_type, exc, tb):
                return False

        monkeypatch.setattr(
            service_module, "SessionLocal", lambda: _DummySession(), raising=False
        )

    def _set_batch_window(self, monkeypatch, seconds: float):
        monkeypatch.setattr(
            service_module.settings,
            "DSP_WEBHOOK_BATCH_WINDOW_SECONDS",
            seconds,
            raising=False,
        )

    def _stub_current_seq(self, monkeypatch):
        values = [100, 101, 102, 103]

        def _fake_get_current_max_seq(db):
            try:
                return values.pop(0)
            except IndexError:
                return 103

        monkeypatch.setattr(
            service_module, "get_current_max_seq", _fake_get_current_max_seq
        )

    def test_data_change_batch_create_then_create(self, client, monkeypatch):
        """在批处理窗口内两次触发，应仅合并触发一次webhook"""
        self._reset_batch_state(monkeypatch)
        self._stub_session_local(monkeypatch)
        self._set_batch_window(monkeypatch, 1.0)
        self._stub_current_seq(monkeypatch)

        triggered = []

        def _fake_trigger_webhooks(db, event, event_data, data_types=None):
            triggered.append(
                {
                    "event": event,
                    "event_data": event_data,
                    "data_types": list(data_types or []),
                }
            )

        monkeypatch.setattr(service_module, "trigger_webhooks", _fake_trigger_webhooks)

        dummy_db = object()
        service_module.trigger_data_change_webhook(dummy_db, ["acs"])  # 第一次
        time.sleep(0.2)
        service_module.trigger_data_change_webhook(dummy_db, ["acs"])  # 第二次

        time.sleep(1.2)  # 等待窗口结束

        assert len(triggered) == 1
        assert triggered[0]["event"] == "data_change"
        assert triggered[0]["data_types"] == ["acs"]
        assert isinstance(triggered[0]["event_data"].get("current_seq"), int)

        state = service_module._data_change_batch_state
        if state.get("timer") is not None:
            state["timer"].cancel()
            state["timer"] = None

    def test_data_change_batch_delete_then_create(self, client, monkeypatch):
        """删除后创建（等价数据变更），窗口内应仅触发一次webhook"""
        self._reset_batch_state(monkeypatch)
        self._stub_session_local(monkeypatch)
        self._set_batch_window(monkeypatch, 1.0)
        self._stub_current_seq(monkeypatch)

        triggered = []

        def _fake_trigger_webhooks(db, event, event_data, data_types=None):
            triggered.append(
                {
                    "event": event,
                    "event_data": event_data,
                    "data_types": list(data_types or []),
                }
            )

        monkeypatch.setattr(service_module, "trigger_webhooks", _fake_trigger_webhooks)

        dummy_db = object()
        service_module.trigger_data_change_webhook(dummy_db, ["acs"])  # 删除后的变更
        time.sleep(0.3)
        service_module.trigger_data_change_webhook(dummy_db, ["acs"])  # 创建后的变更

        time.sleep(1.2)

        assert len(triggered) == 1
        assert triggered[0]["event"] == "data_change"
        assert triggered[0]["data_types"] == ["acs"]
        assert isinstance(triggered[0]["event_data"].get("current_seq"), int)

        state = service_module._data_change_batch_state
        if state.get("timer") is not None:
            state["timer"].cancel()
            state["timer"] = None
