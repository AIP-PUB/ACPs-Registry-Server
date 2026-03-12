#!/usr/bin/env python3
"""演示普通用户使用 Registry Server API 的脚本。"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any, Dict, Optional, Sequence

import requests

from demo_common import (
    DEFAULT_BASE_URL,
    DEFAULT_ATR_BASE_URL,
    DemoArgumentParser,
    DemoError,
    delete_agent_record,
    ensure_client_account,
    load_json,
    login_with_password,
    query_agents,
    register_agent,
    register_entity_via_atr,
    resolve_agent,
    resolve_agent_from_acs,
    summarize_agent,
)

BASE_URL = DEFAULT_BASE_URL
CLIENT_USERNAME = os.getenv("DEMO_CLIENT_USERNAME", "demo-client")
CLIENT_PASSWORD = os.getenv("DEMO_CLIENT_PASSWORD", "demo123")
CLIENT_NAME = os.getenv("DEMO_CLIENT_NAME", "Demo Client")
CLIENT_ORG_NAME = os.getenv("DEMO_CLIENT_ORG", "Demo Organization")


def build_parser() -> DemoArgumentParser:
    config_hint = (
        f"当前 Registry API 地址: {BASE_URL}\n"
        f"当前客户端用户名: {CLIENT_USERNAME}\n"
        f"当前客户端密码: {CLIENT_PASSWORD}\n"
        "如需修改，请编辑 demo_user.py 顶部的 BASE_URL/CLIENT_USERNAME/CLIENT_PASSWORD 常量。"
    )
    parser = DemoArgumentParser(
        description=f"Registry Server 普通用户演示脚本\n\n{config_hint}",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--atr-base-url",
        default=DEFAULT_ATR_BASE_URL,
        help="ATR API 基础地址（默认: %(default)s）",
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    ensure_parser = subparsers.add_parser(
        "ensure-account",
        help="确保客户端账号存在（不存在则自动注册）",
    )
    ensure_parser.add_argument(
        "--name",
        default=CLIENT_NAME,
        help="注册账号时使用的展示名称（默认: %(default)s）",
    )
    ensure_parser.add_argument(
        "--org",
        default=CLIENT_ORG_NAME,
        help="注册账号时使用的组织名称（默认: %(default)s）",
    )
    ensure_parser.set_defaults(func=cmd_ensure_account)

    register_parser = subparsers.add_parser(
        "register",
        help="根据 ACS 文件注册 Agent，可选择是否立即提交审核",
    )
    register_parser.add_argument("--acs-path", required=True, help="ACS JSON 文件路径")
    register_parser.add_argument(
        "--no-submit",
        action="store_true",
        help="只创建草稿，不提交审核",
    )
    register_parser.add_argument(
        "--ontology",
        action="store_true",
        help="将当前注册的 Agent 标记为本体 (is_ontology)",
    )
    register_parser.set_defaults(func=cmd_register)

    delete_parser = subparsers.add_parser(
        "delete",
        help="删除当前账号名下的 Agent",
    )
    delete_parser.add_argument("--agent-id", help="Agent 的 UUID")
    delete_parser.add_argument("--aic", help="Agent 的 AIC")
    delete_parser.add_argument("--name", help="Agent 名称（需与 --version 配合使用）")
    delete_parser.add_argument("--version", help="Agent 版本")
    delete_parser.add_argument("--acs-path", help="包含 Agent 信息的 ACS 文件")
    delete_parser.add_argument(
        "--confirm-ontology-cascade",
        action="store_true",
        help="如果删除的是本体，删除后验证派生实体也被删除",
    )
    delete_parser.set_defaults(func=cmd_delete)

    register_entity_parser = subparsers.add_parser(
        "register-entity",
        help="通过 ATR 协议基于本体 AIC 注册实体",
    )
    register_entity_parser.add_argument(
        "--ontology-aic",
        required=True,
        help="用于派生实体的本体 AIC",
    )
    register_entity_parser.add_argument(
        "--payload-path",
        help="包含 endPoints/entityMeta 字段的 JSON 文件（可选）",
    )
    register_entity_parser.set_defaults(func=cmd_register_entity)

    query_parser = subparsers.add_parser(
        "query",
        help="查询当前账号的 Agent，支持精确匹配与模糊匹配",
    )
    query_parser.add_argument("--aic", help="精确匹配的 AIC")
    query_parser.add_argument("--name", help="精确匹配的名称")
    query_parser.add_argument("--version", help="精确匹配的版本")
    query_parser.add_argument(
        "--name-like",
        dest="name_like",
        help="名称模糊匹配（大小写不敏感）",
    )
    query_parser.add_argument(
        "--version-like",
        dest="version_like",
        help="版本模糊匹配（大小写不敏感）",
    )
    query_parser.add_argument(
        "--aic-like",
        help="按 AIC 关键词模糊匹配（大小写不敏感）",
    )
    query_parser.add_argument(
        "--is-active",
        help="按 is_active 字段过滤（true/t/1 或 false/f/0）",
    )
    query_parser.add_argument(
        "--is-deleted",
        help="按 is_deleted 字段过滤（true/t/1 或 false/f/0）",
    )
    query_parser.add_argument(
        "--is-disabled",
        help="按 is_disabled 字段过滤（true/t/1 或 false/f/0）",
    )
    query_parser.set_defaults(func=cmd_query)

    return parser


def cmd_ensure_account(args: argparse.Namespace) -> None:
    tokens, status = ensure_client_account(
        BASE_URL,
        CLIENT_USERNAME,
        CLIENT_PASSWORD,
        name=args.name,
        org_name=args.org,
    )
    print(
        json.dumps(
            {
                "message": f"客户端账号 {CLIENT_USERNAME} {status}",
                "access_token_length": len(tokens.access_token),
            },
            ensure_ascii=False,
            indent=2,
        )
    )


def _login() -> str:
    tokens = login_with_password(BASE_URL, CLIENT_USERNAME, CLIENT_PASSWORD)
    return tokens.access_token


def cmd_register(args: argparse.Namespace) -> None:
    token = _login()
    agent = register_agent(
        BASE_URL,
        token,
        Path(args.acs_path),
        submit=not args.no_submit,
        is_ontology=args.ontology,
    )
    print(
        json.dumps(
            {
                "message": "Agent 注册完成",
                "id": agent.get("id"),
                "approval_status": agent.get("approval_status"),
                "is_ontology": agent.get("is_ontology"),
            },
            ensure_ascii=False,
            indent=2,
        )
    )


def _locate_user_agent(
    args: argparse.Namespace,
    token: str,
) -> Dict[str, Any]:
    if args.acs_path:
        agent, _ = resolve_agent_from_acs(
            BASE_URL,
            token,
            Path(args.acs_path),
            path="/agent/client",
        )
        return agent

    if not any([args.agent_id, args.aic, args.name and args.version]):
        raise DemoError("删除操作需要提供 agent-id、AIC、name+version 或 ACS 文件")

    return resolve_agent(
        BASE_URL,
        token,
        "/agent/client",
        agent_id=args.agent_id,
        aic=args.aic,
        name=args.name,
        version=args.version,
    )


def _load_entity_payload(path_value: Optional[str]) -> Optional[Dict[str, Any]]:
    if not path_value:
        return None
    data = load_json(Path(path_value))
    if not isinstance(data, dict):
        raise DemoError("实体 payload 文件必须是 JSON 对象")
    return data


def cmd_register_entity(args: argparse.Namespace) -> None:
    payload = _load_entity_payload(args.payload_path)
    result = register_entity_via_atr(
        args.atr_base_url,
        args.ontology_aic,
        entity_payload=payload,
    )
    print(
        json.dumps(
            {
                "message": "实体注册完成",
                "ontology_aic": result.get("ontologyAic"),
                "entity_aic": result.get("entityAic"),
                "endpoints": result.get("endPoints"),
                "entity_user_id": result.get("entityUserId"),
                "entity_meta": result.get("entityMeta"),
            },
            ensure_ascii=False,
            indent=2,
        )
    )


def _collect_derived_entities(
    token: str,
    ontology_aic: str,
) -> list[Dict[str, Any]]:
    prefix = ontology_aic[:22].upper()
    derived: list[Dict[str, Any]] = []
    for candidate in query_agents(
        BASE_URL,
        token,
        "/agent/client",
    ):
        candidate_aic = (candidate.get("aic") or "").upper()
        if candidate_aic.startswith(prefix) and candidate_aic != ontology_aic:
            derived.append(candidate)
    return derived


def _confirm_ontology_cascade(
    token: str,
    deleted_agent: Dict[str, Any],
) -> Dict[str, Any]:
    if not deleted_agent.get("is_ontology"):
        return {"status": "skipped", "reason": "目标 Agent 不是本体"}
    ontology_aic = (deleted_agent.get("aic") or "").upper()
    if not ontology_aic:
        return {"status": "skipped", "reason": "本体尚未分配 AIC"}

    derived_agents = _collect_derived_entities(token, ontology_aic)
    if not derived_agents:
        return {"status": "verified", "derived_total": 0}

    still_active = [agent for agent in derived_agents if not agent.get("is_deleted")]
    report: Dict[str, Any] = {
        "status": "verified" if not still_active else "failed",
        "derived_total": len(derived_agents),
        "deleted_count": len(derived_agents) - len(still_active),
    }
    if still_active:
        report["active_entities"] = [agent.get("aic") for agent in still_active]
    return report


def cmd_delete(args: argparse.Namespace) -> None:
    token = _login()
    agent = _locate_user_agent(args, token)
    if agent.get("is_ontology") and not args.confirm_ontology_cascade:
        raise DemoError(
            "目标 Agent 是本体，删除前必须显式添加 --confirm-ontology-cascade 开关以确认级联检查"
        )
    delete_agent_record(BASE_URL, token, agent["id"])
    cascade_report = None
    if args.confirm_ontology_cascade:
        cascade_report = _confirm_ontology_cascade(token, agent)

    payload = {
        "message": "Agent 删除完成",
        "id": agent.get("id"),
        "aic": agent.get("aic"),
    }
    if cascade_report:
        payload["cascade_check"] = cascade_report
    print(
        json.dumps(
            payload,
            ensure_ascii=False,
            indent=2,
        )
    )


def cmd_query(args: argparse.Namespace) -> None:
    token = _login()
    agents = query_agents(
        BASE_URL,
        token,
        "/agent/client",
        aic=args.aic,
        name=args.name,
        version=args.version,
        name_like=args.name_like,
        version_like=args.version_like,
        aic_like=args.aic_like,
        is_active=args.is_active,
        is_deleted=args.is_deleted,
        is_disabled=args.is_disabled,
    )
    summaries = [summarize_agent(agent) for agent in agents]
    print(
        json.dumps(
            {"total": len(summaries), "items": summaries}, ensure_ascii=False, indent=2
        )
    )


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        args.func(args)
        return 0
    except DemoError as exc:
        print(f"错误: {exc}")
        return 1
    except requests.RequestException as exc:
        print(f"HTTP 请求失败: {exc}")
        return 1


if __name__ == "__main__":
    import sys

    sys.exit(main())
