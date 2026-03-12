import json
from typing import Any, Dict

import pytest
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

from app.agent import api_atr
from app.agent.api_atr import router
from app.agent.exception import AtrException, AtrErrorCode
from app.core.acps_exception import AcpsException
from app.core.db_session import get_db
from app.utils import aic


@pytest.fixture
def atr_app():
    app = FastAPI()
    app.include_router(router, prefix="/acps-atr-v2")

    @app.exception_handler(AcpsException)
    async def _handle_acps_exception(request, exc: AcpsException):
        return JSONResponse(
            status_code=exc.http_status, content=exc.to_response_payload()
        )

    # Override DB dependency used by ATR routes
    app.dependency_overrides[get_db] = lambda: None
    return app


@pytest.fixture
def atr_client(atr_app):
    return TestClient(atr_app)


def test_get_agent_invalid_aic_returns_error_payload(atr_client):
    response = atr_client.get("/acps-atr-v2/acs/invalid")
    assert response.status_code == 400
    body = response.json()
    assert body["status"] == "error"
    assert body["error"]["code"] == AtrErrorCode.INVALID_REQUEST
    assert body["error"]["message"].startswith("Invalid AIC")


def test_get_agent_not_found(monkeypatch, atr_client):
    valid_aic = aic.generate_aic()

    def _fake_get_agent(db, agent_aic, raise_exception=False):
        return None

    monkeypatch.setattr(api_atr, "get_agent_by_aic", _fake_get_agent)

    response = atr_client.get(f"/acps-atr-v2/acs/{valid_aic}")
    assert response.status_code == 404
    body = response.json()
    assert body["error"]["code"] == AtrErrorCode.AGENT_NOT_FOUND
    assert body["error"]["data"]["agentAic"] == valid_aic


def test_register_entity_propagates_service_exception(monkeypatch, atr_client):
    ontology_aic = aic.generate_ontology_aic()

    def _fake_register_entity(**kwargs: Dict[str, Any]):
        raise AtrException(
            code=AtrErrorCode.ENDPOINT_CONFLICT,
            message="conflict",
            http_status=409,
            data={"conflictingUrl": "https://dup"},
        )

    monkeypatch.setattr(api_atr, "register_entity", _fake_register_entity)

    payload = {"ontologyAic": ontology_aic, "endPoints": []}
    response = atr_client.post(
        "/acps-atr-v2/entity",
        content=json.dumps(payload),
        headers={"Content-Type": "application/json"},
    )
    assert response.status_code == 409
    body = response.json()
    assert body["error"]["code"] == AtrErrorCode.ENDPOINT_CONFLICT
    assert body["error"]["data"]["conflictingUrl"] == "https://dup"
