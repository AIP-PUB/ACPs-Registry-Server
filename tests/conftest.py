"""
共享的pytest fixtures和配置
"""

import json
import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from fastapi.responses import JSONResponse
from app.sync.exception import SyncException
from app.sync import api as api_module


@pytest.fixture
def app():
    """创建用于测试的FastAPI应用实例"""
    app = FastAPI()
    app.include_router(api_module.router)

    # 覆盖数据库依赖
    def _fake_get_db():
        class _DummyDB:
            pass

        return _DummyDB()

    app.dependency_overrides[api_module.get_db] = _fake_get_db

    # 注册异常处理器
    async def sync_exception_handler(request: Request, exc: SyncException):
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "error": getattr(exc, "error_name", "UNKNOWN"),
                "message": getattr(exc, "error_msg", str(exc)),
                "input_params": getattr(exc, "input_params", {}),
            },
        )

    app.add_exception_handler(SyncException, sync_exception_handler)
    return app


@pytest.fixture
def client(app):
    """创建用于测试的HTTP客户端"""
    return TestClient(app)


class DummyEnvelope:
    """模拟数据包装器，用于测试"""

    def __init__(self, payload):
        self.payload = payload

    def model_dump_json(self, exclude_none=True):
        """模拟Pydantic模型的JSON序列化方法"""
        return json.dumps(self.payload)


@pytest.fixture
def dummy_envelope_factory():
    """创建DummyEnvelope对象的工厂函数"""
    return DummyEnvelope


def make_dummy_snapshot(snapshot_id="snap-1", seq=123, chunk_total=2, object_count=3):
    """创建用于测试的快照对象"""

    class _Snapshot:
        def __init__(self):
            self.id = snapshot_id
            self.seq = seq
            self.chunk_total = chunk_total
            self.object_count = object_count

    return _Snapshot()


@pytest.fixture
def snapshot_factory():
    """创建快照对象的工厂函数"""
    return make_dummy_snapshot
