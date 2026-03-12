#!/usr/bin/env python3
"""用于演示注册服务器 Agent API 的脚本。

脚本提供多个子命令：

# 1. 确认账号（如不存在则自动注册默认演示账号）
python demo_register.py ensure-accounts

# 2. 注册并提交 Agent（如需跳过提交可加 --no-submit）
python demo_register.py register --acs-path ./samples/demo.acs.json

# 3. 管理员审批通过（默认审批意见可用 --comments 覆盖）
python demo_register.py approve --acs-path ./samples/demo.acs.json

# 4. 删除 Agent（优先使用 AIC，缺失时自动使用 name/version）
python demo_register.py delete --acs-path ./samples/demo.acs.json

# 5. 禁用 Agent（优先使用 AIC，缺失时自动使用 name/version，禁用理由可用 --reason 覆盖）
python demo_register.py disable --acs-path ./samples/demo.acs.json

所有命令都会调用已运行的 registry-server API，并依赖项目内定义的标准接口。
令牌通过用户名/密码的登录流程获取。
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

import os

import requests
from requests import Response

DEFAULT_BASE_URL = os.getenv("REGISTRY_API_BASE_URL", "http://localhost:8001/api")


def _infer_default_atr_base_url(api_base_url: str) -> str:
    base = api_base_url.rstrip("/") or "http://localhost:8001/api"
    if base.endswith("/api"):
        base = base[:-4]
    return f"{base}/acps-atr-v2"


DEFAULT_ATR_BASE_URL = os.getenv(
    "REGISTRY_ATR_BASE_URL", _infer_default_atr_base_url(DEFAULT_BASE_URL)
)

REQUEST_TIMEOUT = 15  # 请求超时时间（秒）
DEFAULT_PAGE_SIZE = 50


class DemoError(RuntimeError):
    """在 API 调用失败时抛出的异常。"""


class DemoArgumentParser(argparse.ArgumentParser):
    """自定义解析器，在参数无效时输出完整的帮助信息。"""

    def error(self, message: str) -> None:
        self.print_help(sys.stderr)
        self.exit(2)


@dataclass
class TokenBundle:
    access_token: str
    refresh_token: Optional[str] = None

    @classmethod
    def from_response(cls, data: Dict[str, Any]) -> "TokenBundle":
        return cls(
            access_token=data.get("access_token"),
            refresh_token=data.get("refresh_token"),
        )


def _compose_url(base_url: str, path: str) -> str:
    base = base_url.rstrip("/")
    if not path.startswith("/"):
        path = f"/{path}"
    return f"{base}{path}"


def _request(
    method: str,
    base_url: str,
    path: str,
    token: Optional[str] = None,
    expected: Sequence[int] | int = (200, 201),
    **kwargs: Any,
) -> Response:
    url = _compose_url(base_url, path)
    headers = kwargs.pop("headers", {}) or {}
    headers.setdefault("Accept", "application/json")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    response = requests.request(
        method,
        url,
        headers=headers,
        timeout=REQUEST_TIMEOUT,
        **kwargs,
    )
    expected_codes: Iterable[int]
    if isinstance(expected, int):
        expected_codes = (expected,)
    else:
        expected_codes = expected
    if response.status_code not in expected_codes:
        message = _extract_error_message(response)
        raise DemoError(
            f"{method} {url} 请求失败，状态码 {response.status_code}：{message}"
        )
    return response


def _extract_error_message(response: Response) -> str:
    try:
        payload = response.json()
        if isinstance(payload, dict):
            detail = payload.get("detail")
            if isinstance(detail, str):
                return detail
            if isinstance(detail, list):
                return json.dumps(detail, ensure_ascii=False)
        return response.text.strip()
    except ValueError:
        return response.text.strip()


def login_with_password(base_url: str, username: str, password: str) -> TokenBundle:
    """通过用户名与密码登录并获取访问令牌。"""
    response = _request(
        "POST",
        base_url,
        "/auth/login",
        data={"username": username, "password": password},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    data = response.json()
    if "access_token" not in data:
        raise DemoError("登录响应缺少 access_token 字段")
    return TokenBundle.from_response(data)


def register_client_user(
    base_url: str,
    username: str,
    password: str,
    name: Optional[str] = None,
    org_name: Optional[str] = None,
) -> TokenBundle:
    """注册新的客户端用户并返回访问令牌。"""
    payload: Dict[str, Any] = {
        "username": username,
        "password": password,
    }
    if name:
        payload["name"] = name
    if org_name:
        payload["org_name"] = org_name

    response = _request("POST", base_url, "/auth/register", json=payload)
    data = response.json()
    if "access_token" not in data:
        raise DemoError("注册响应缺少 access_token 字段")
    return TokenBundle.from_response(data)


def ensure_client_account(
    base_url: str,
    username: str,
    password: str,
    name: Optional[str] = None,
    org_name: Optional[str] = None,
) -> Tuple[TokenBundle, str]:
    """确保客户端账号存在并可使用。

    优先尝试登录；若失败则自动注册新账号后返回令牌。
    返回值包含令牌与状态描述文本。
    """
    try:
        tokens = login_with_password(base_url, username, password)
        return tokens, "登录成功"
    except DemoError as login_error:
        try:
            tokens = register_client_user(base_url, username, password, name, org_name)
            return tokens, "注册成功"
        except DemoError:
            # 再次抛出原始的登录错误，便于定位根因
            raise login_error


def load_json(path: Path) -> Dict[str, Any]:
    if not path.exists():
        raise DemoError(f"未找到 ACS 文件: {path}")
    with path.open("r", encoding="utf-8") as fh:
        try:
            return json.load(fh)
        except json.JSONDecodeError as exc:
            raise DemoError(f"解析 JSON 文件 {path} 失败: {exc}") from exc


def write_json(path: Path, data: Dict[str, Any]) -> None:
    with path.open("w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=2, sort_keys=True)
        fh.write("\n")


def _write_json_preserve_order(path: Path, data: Dict[str, Any]) -> None:
    """写入JSON文件，保持字段顺序不变。"""
    with path.open("w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=2, sort_keys=False)
        fh.write("\n")


def parse_acs(acs_path: Path) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """读取 ACS JSON 并推导用于创建 Agent 的字段。"""
    acs_data = load_json(acs_path)
    payload = _infer_agent_payload(acs_data)
    return acs_data, payload


def _get_nested(data: Dict[str, Any], path: Sequence[str]) -> Optional[Any]:
    current: Any = data
    for key in path:
        if isinstance(current, dict) and key in current:
            current = current[key]
        else:
            return None
    return current


def _find_first(data: Dict[str, Any], paths: Sequence[Sequence[str]]) -> Optional[Any]:
    for path in paths:
        value = _get_nested(data, path)
        if value is not None:
            return value
    return None


def _infer_agent_payload(acs: Dict[str, Any]) -> Dict[str, Any]:
    """将 ACS JSON 转换为创建 Agent 所需的字段。"""
    name = _find_first(acs, [("name",), ("agent", "name"), ("metadata", "name")])
    version = _find_first(
        acs, [("version",), ("agent", "version"), ("metadata", "version")]
    )
    description = _find_first(
        acs,
        [
            ("description",),
            ("agent", "description"),
            ("metadata", "description"),
        ],
    )
    if not name:
        raise DemoError("ACS 文件中缺少 name 字段")
    if not version:
        raise DemoError("ACS 文件中缺少 version 字段")

    logo_url = _find_first(acs, [("logo_url",), ("agent", "logo_url")])

    acs_payload = json.dumps(acs, ensure_ascii=False)

    payload: Dict[str, Any] = {
        "name": name,
        "version": version,
        "description": description or "",
        "logo_url": logo_url,
        "acs": acs_payload,
    }

    # 移除值为 None 的可选字段，保持载荷简洁
    return {k: v for k, v in payload.items() if v is not None}


def register_agent(
    base_url: str,
    token: str,
    acs_path: Path,
    submit: bool = True,
    *,
    is_ontology: bool = False,
) -> Dict[str, Any]:
    _, payload = parse_acs(acs_path)
    if is_ontology:
        payload["is_ontology"] = True

    response = _request(
        "POST",
        base_url,
        "/agent/client",
        token=token,
        json=payload,
        expected=(200, 201),
    )
    agent = response.json()
    agent_id = agent.get("id")
    if submit and agent_id:
        _request(
            "POST",
            base_url,
            f"/agent/client/{agent_id}/submit",
            token=token,
            expected=(200, 201),
        )
        # 重新读取 Agent 详情以获取最新状态
        agent = get_agent_detail(base_url, token, agent_id, client_view=True)
    return agent


def register_entity_via_atr(
    atr_base_url: str,
    ontology_aic: str,
    *,
    entity_payload: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    body: Dict[str, Any] = {"ontologyAic": ontology_aic.strip().upper()}
    if entity_payload:
        if "endPoints" in entity_payload:
            body["endPoints"] = entity_payload["endPoints"]
        if "entityUserId" in entity_payload:
            body["entityUserId"] = entity_payload["entityUserId"]
        if "entityMeta" in entity_payload:
            body["entityMeta"] = entity_payload["entityMeta"]

    response = _request(
        "POST",
        atr_base_url,
        "/entity",
        json=body,
        expected=(200, 201),
    )
    payload = response.json()
    if payload.get("status") != "ok" or "result" not in payload:
        error = payload.get("error") or {}
        raise DemoError(f"实体注册失败: {error.get('message') or payload}")
    return payload["result"]


def get_agent_detail(
    base_url: str, token: str, agent_id: str, client_view: bool = False
) -> Dict[str, Any]:
    path = "/agent/client" if client_view else "/agent/staff"
    response = _request(
        "GET",
        base_url,
        f"{path}/{agent_id}",
        token=token,
        expected=200,
    )
    return response.json()


def _paginate_agents(
    base_url: str,
    token: str,
    path: str,
    *,
    name: Optional[str] = None,
    version: Optional[str] = None,
    aic: Optional[str] = None,
    name_like: Optional[str] = None,
    version_like: Optional[str] = None,
    aic_like: Optional[str] = None,
    statuses: Optional[List[str]] = None,
    with_users: bool = False,
    is_active: Optional[str] = None,
    is_deleted: Optional[str] = None,
    is_disabled: Optional[str] = None,
) -> Iterable[Dict[str, Any]]:
    page_num = 1
    while True:
        params: Dict[str, Any] = {"page_num": page_num, "page_size": DEFAULT_PAGE_SIZE}
        if name:
            params["name"] = name
        if version:
            params["version"] = version
        if aic:
            params["aic"] = aic
        if name_like:
            params["name_like"] = name_like
        if version_like:
            params["version_like"] = version_like
        if aic_like:
            params["aic_like"] = aic_like
        if statuses:
            params["statuses"] = statuses
        if with_users:
            params["with_users"] = True
        if is_active:
            params["is_active"] = is_active
        if is_deleted:
            params["is_deleted"] = is_deleted
        if is_disabled:
            params["is_disabled"] = is_disabled

        response = _request(
            "GET",
            base_url,
            path,
            token=token,
            params=params,
            expected=200,
        )
        payload = response.json()
        items = payload.get("items", [])
        for item in items:
            yield item

        total = payload.get("total", 0)
        if page_num * DEFAULT_PAGE_SIZE >= total:
            break
        page_num += 1


def _find_agent_by_predicate(
    base_url: str,
    token: str,
    path: str,
    predicate,
    *,
    name: Optional[str] = None,
    version: Optional[str] = None,
    aic: Optional[str] = None,
    name_like: Optional[str] = None,
    version_like: Optional[str] = None,
    aic_like: Optional[str] = None,
    statuses: Optional[List[str]] = None,
    is_active: Optional[str] = None,
    is_deleted: Optional[str] = None,
    is_disabled: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    for agent in _paginate_agents(
        base_url,
        token,
        path,
        name=name,
        version=version,
        aic=aic,
        name_like=name_like,
        version_like=version_like,
        aic_like=aic_like,
        statuses=statuses,
        is_active=is_active,
        is_deleted=is_deleted,
        is_disabled=is_disabled,
    ):
        if predicate(agent):
            return agent
    return None


def _find_agent_by_name_version(
    base_url: str,
    token: str,
    path: str,
    *,
    name: str,
    version: str,
    aic_like: Optional[str] = None,
    statuses: Optional[List[str]] = None,
    is_active: Optional[str] = None,
    is_deleted: Optional[str] = None,
    is_disabled: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    return _find_agent_by_predicate(
        base_url,
        token,
        path,
        predicate=lambda item: item.get("name") == name
        and item.get("version") == version,
        name=name,
        version=version,
        aic_like=aic_like,
        statuses=statuses,
        is_active=is_active,
        is_deleted=is_deleted,
        is_disabled=is_disabled,
    )


def approve_agent(
    base_url: str,
    token: str,
    name: str,
    version: str,
    comments: str = "通过演示脚本审批",
) -> Dict[str, Any]:
    agent = _find_agent_by_predicate(
        base_url,
        token,
        "/agent/staff",
        predicate=lambda item: item.get("name") == name
        and item.get("version") == version,
        name=name,
        version=version,
        statuses=["PENDING"],
    )
    if not agent:
        raise DemoError(f"未找到等待审批的 Agent: name={name}, version={version}")

    agent_id = agent["id"]
    response = _request(
        "POST",
        base_url,
        f"/agent/staff/{agent_id}/process",
        token=token,
        json={"approve": True, "comments": comments},
        expected=200,
    )
    return response.json()


def approve_agent_from_acs(
    base_url: str,
    token: str,
    acs_path: Path,
    comments: str = "通过演示脚本审批",
) -> Dict[str, Any]:
    acs_data, payload = parse_acs(acs_path)
    agent = approve_agent(
        base_url,
        token,
        payload["name"],
        payload["version"],
        comments=comments,
    )
    if not agent.get("aic"):
        agent = get_agent_detail(base_url, token, agent["id"], client_view=False)
    _write_agent_metadata_to_acs(agent, acs_path, acs_data)
    return agent


def process_agent_by_id(
    base_url: str,
    token: str,
    agent_id: str,
    approve: bool,
    comments: str,
) -> Dict[str, Any]:
    response = _request(
        "POST",
        base_url,
        f"/agent/staff/{agent_id}/process",
        token=token,
        json={"approve": approve, "comments": comments},
        expected=200,
    )
    return response.json()


def _extract_aic(data: Dict[str, Any]) -> Optional[str]:
    if "aic" in data and data["aic"]:
        return data["aic"]
    return ""


def _write_agent_metadata_to_acs(
    agent: Dict[str, Any],
    acs_path: Path,
    acs_data: Optional[Dict[str, Any]] = None,
) -> None:
    if acs_data is None:
        acs_data = load_json(acs_path)

    # 更新 aic、active、lastModifiedTime 字段
    aic = agent.get("aic")
    acs = agent.get("acs")
    if aic and acs:
        acs_json = json.loads(acs) if isinstance(acs, str) else acs
        aic2 = acs_json.get("aic")
        if aic2 and aic2 == aic:
            acs_data["aic"] = aic2
        active = acs_json.get("active")
        if active is not None:
            acs_data["active"] = active
        last_modified = acs_json.get("lastModifiedTime")
        if last_modified:
            acs_data["lastModifiedTime"] = last_modified

    # 保持原有字段顺序写入文件
    _write_json_preserve_order(acs_path, acs_data)


def resolve_agent_from_acs(
    base_url: str,
    token: str,
    acs_path: Path,
    *,
    path: str,
    statuses: Optional[List[str]] = None,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    acs_data = load_json(acs_path)
    aic = _extract_aic(acs_data)
    if aic:
        agent = _find_agent_by_aic(
            base_url,
            token,
            path,
            aic=aic,
            statuses=statuses,
        )
        if agent:
            return agent, acs_data

    payload = _infer_agent_payload(acs_data)
    name = payload["name"]
    version = payload["version"]
    agent = _find_agent_by_name_version(
        base_url,
        token,
        path,
        name=name,
        version=version,
        statuses=statuses,
    )
    if agent:
        return agent, acs_data

    identifier = f"name={name}, version={version}"
    if aic:
        raise DemoError(f"未找到匹配的 Agent: AIC={aic}, {identifier}")
    raise DemoError(
        f"ACS 文件缺少 AIC，且无法通过 name/version 定位 Agent: {identifier}"
    )


def delete_agent_record(
    base_url: str,
    token: str,
    agent_id: str,
) -> None:
    _request(
        "DELETE",
        base_url,
        f"/agent/client/{agent_id}",
        token=token,
        json="演示删除",
        expected=200,
    )


def disable_agent_record(
    base_url: str,
    token: str,
    agent_id: str,
    reason: str = "演示禁用",
) -> Dict[str, Any]:
    response = _request(
        "POST",
        base_url,
        f"/agent/staff/{agent_id}/disable",
        token=token,
        json=reason,
        expected=200,
    )
    return response.json()


def enable_agent_record(
    base_url: str,
    token: str,
    agent_id: str,
) -> Dict[str, Any]:
    response = _request(
        "POST",
        base_url,
        f"/agent/staff/{agent_id}/enable",
        token=token,
        expected=200,
    )
    return response.json()


def _find_agent_by_aic(
    base_url: str,
    token: str,
    path: str,
    *,
    aic: str,
    aic_like: Optional[str] = None,
    statuses: Optional[List[str]] = None,
    is_active: Optional[str] = None,
    is_deleted: Optional[str] = None,
    is_disabled: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    predicate = lambda item: (item.get("aic") or "").upper() == aic.upper()
    return _find_agent_by_predicate(
        base_url,
        token,
        path,
        predicate=predicate,
        aic=aic,
        aic_like=aic_like,
        statuses=statuses,
        is_active=is_active,
        is_deleted=is_deleted,
        is_disabled=is_disabled,
    )


def query_agents(
    base_url: str,
    token: str,
    path: str,
    *,
    aic: Optional[str] = None,
    name: Optional[str] = None,
    version: Optional[str] = None,
    name_like: Optional[str] = None,
    version_like: Optional[str] = None,
    aic_like: Optional[str] = None,
    is_active: Optional[str] = None,
    is_deleted: Optional[str] = None,
    is_disabled: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """按多种过滤条件查询 Agent 列表。"""
    return list(
        _paginate_agents(
            base_url,
            token,
            path,
            name=name,
            version=version,
            aic=aic,
            name_like=name_like,
            version_like=version_like,
            aic_like=aic_like,
            is_active=is_active,
            is_deleted=is_deleted,
            is_disabled=is_disabled,
        )
    )


def summarize_agent(agent: Dict[str, Any]) -> Dict[str, Any]:
    """提取在命令行中展示所需的关键信息。"""
    return {
        "name": agent.get("name"),
        "version": agent.get("version"),
        "approval_status": agent.get("approval_status"),
        "is_active": agent.get("is_active"),
        "is_disabled": agent.get("is_disabled"),
        "is_deleted": agent.get("is_deleted"),
        "aic": agent.get("aic"),
    }


def resolve_agent(
    base_url: str,
    token: str,
    path: str,
    *,
    agent_id: Optional[str] = None,
    aic: Optional[str] = None,
    name: Optional[str] = None,
    version: Optional[str] = None,
) -> Dict[str, Any]:
    """通过多种标识方式查询单个 Agent。"""
    if agent_id:
        response = _request(
            "GET",
            base_url,
            f"{path}/{agent_id}",
            token=token,
            expected=200,
        )
        return response.json()

    if aic:
        agent = _find_agent_by_aic(
            base_url,
            token,
            path,
            aic=aic,
        )
        if agent:
            return agent
        raise DemoError(f"未找到 AIC 为 {aic} 的 Agent")

    if name and version:
        agent = _find_agent_by_name_version(
            base_url,
            token,
            path,
            name=name,
            version=version,
        )
        if agent:
            return agent
        raise DemoError(f"未找到 Agent: name={name}, version={version}")

    raise DemoError("请提供 agent-id、AIC 或 name+version 用于定位 Agent")
