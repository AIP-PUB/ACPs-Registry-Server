#!/usr/bin/env python3
"""演示管理员使用 Registry Server API 的脚本。"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any, Dict, Optional, Sequence

import requests

from demo_common import (
    DEFAULT_BASE_URL,
    DemoArgumentParser,
    DemoError,
    approve_agent,
    approve_agent_from_acs,
    disable_agent_record,
    enable_agent_record,
    login_with_password,
    process_agent_by_id,
    query_agents,
    resolve_agent,
    resolve_agent_from_acs,
    summarize_agent,
)

BASE_URL = DEFAULT_BASE_URL
ADMIN_USERNAME = os.getenv("DEMO_ADMIN_USERNAME", "admin")
ADMIN_PASSWORD = os.getenv("DEMO_ADMIN_PASSWORD", "admin123")


def build_parser() -> DemoArgumentParser:
    config_hint = (
        f"当前 Registry API 地址: {BASE_URL}\n"
        f"当前管理员用户名: {ADMIN_USERNAME}\n"
        f"当前管理员密码: {ADMIN_PASSWORD}\n"
        "如需修改，请编辑 demo_admin.py 顶部的 BASE_URL/ADMIN_USERNAME/ADMIN_PASSWORD 常量。"
    )
    parser = DemoArgumentParser(
        description=f"Registry Server 管理员演示脚本\n\n{config_hint}",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    ensure_parser = subparsers.add_parser(
        "ensure-account",
        help="验证管理员账号是否可登录",
    )
    ensure_parser.set_defaults(func=cmd_ensure_account)

    approve_parser = subparsers.add_parser(
        "approve",
        help="审批待审核的 Agent，可通过多种方式定位目标",
    )
    approve_parser.add_argument("--agent-id", help="Agent 的 UUID")
    approve_parser.add_argument("--aic", help="Agent 的 AIC")
    approve_parser.add_argument("--name", help="Agent 名称（与 --version 组合使用）")
    approve_parser.add_argument("--version", help="Agent 版本")
    approve_parser.add_argument("--acs-path", help="包含 Agent 信息的 ACS 文件")
    approve_parser.add_argument(
        "--comments",
        default="通过演示脚本审批",
        help="审批意见",
    )
    approve_parser.set_defaults(func=cmd_approve)

    disable_parser = subparsers.add_parser(
        "disable",
        help="禁用指定 Agent",
    )
    _add_agent_lookup_arguments(disable_parser)
    disable_parser.add_argument("--reason", default="演示禁用", help="禁用原因")
    disable_parser.set_defaults(func=cmd_disable)

    enable_parser = subparsers.add_parser(
        "enable",
        help="启用指定 Agent 及其派生实体",
    )
    _add_agent_lookup_arguments(enable_parser)
    enable_parser.set_defaults(func=cmd_enable)

    query_parser = subparsers.add_parser(
        "query",
        help="查询全局 Agent 列表，支持精确匹配与模糊匹配",
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
        help="按 is_active 字段过滤（接受 true/t/1 或 false/f/0，大小写不敏感）",
    )
    query_parser.add_argument(
        "--is-deleted",
        help="按 is_deleted 字段过滤（接受 true/t/1 或 false/f/0，大小写不敏感）",
    )
    query_parser.add_argument(
        "--is-disabled",
        help="按 is_disabled 字段过滤（接受 true/t/1 或 false/f/0，大小写不敏感）",
    )
    query_parser.set_defaults(func=cmd_query)

    return parser


def _add_agent_lookup_arguments(subparser: argparse.ArgumentParser) -> None:
    subparser.add_argument("--agent-id", help="Agent 的 UUID")
    subparser.add_argument("--aic", help="Agent 的 AIC")
    subparser.add_argument("--name", help="Agent 名称（需与 --version 配合使用）")
    subparser.add_argument("--version", help="Agent 版本")
    subparser.add_argument("--acs-path", help="包含 Agent 信息的 ACS 文件")


def _login() -> str:
    tokens = login_with_password(BASE_URL, ADMIN_USERNAME, ADMIN_PASSWORD)
    return tokens.access_token


def cmd_ensure_account(args: argparse.Namespace) -> None:
    token = _login()
    print(
        json.dumps(
            {
                "message": f"管理员账号 {ADMIN_USERNAME} 登录成功",
                "access_token_length": len(token),
            },
            ensure_ascii=False,
            indent=2,
        )
    )


def _resolve_admin_agent(
    args: argparse.Namespace,
    token: str,
) -> Dict[str, Any]:
    if args.acs_path:
        agent, _ = resolve_agent_from_acs(
            BASE_URL,
            token,
            Path(args.acs_path),
            path="/agent/staff",
        )
        return agent

    if not any([args.agent_id, args.aic, args.name and args.version]):
        raise DemoError("需要提供 agent-id、AIC、name+version 或 ACS 文件来定位 Agent")

    return resolve_agent(
        BASE_URL,
        token,
        "/agent/staff",
        agent_id=args.agent_id,
        aic=args.aic,
        name=args.name,
        version=args.version,
    )


def cmd_approve(args: argparse.Namespace) -> None:
    token = _login()

    if args.acs_path:
        agent = approve_agent_from_acs(
            BASE_URL,
            token,
            Path(args.acs_path),
            comments=args.comments,
        )
    elif args.name and args.version and not args.agent_id and not args.aic:
        agent = approve_agent(
            BASE_URL,
            token,
            args.name,
            args.version,
            comments=args.comments,
        )
    else:
        target = _resolve_admin_agent(args, token)
        agent = process_agent_by_id(
            BASE_URL,
            token,
            target["id"],
            approve=True,
            comments=args.comments,
        )

    print(
        json.dumps(
            {
                "message": "Agent 审批已完成",
                "id": agent.get("id"),
                "aic": agent.get("aic"),
                "approval_status": agent.get("approval_status"),
            },
            ensure_ascii=False,
            indent=2,
        )
    )


def cmd_disable(args: argparse.Namespace) -> None:
    token = _login()
    agent = _resolve_admin_agent(args, token)
    result = disable_agent_record(
        BASE_URL,
        token,
        agent["id"],
        reason=args.reason,
    )
    print(
        json.dumps(
            {
                "message": "Agent 已禁用",
                "id": result.get("id") or agent.get("id"),
                "aic": result.get("aic") or agent.get("aic"),
                "disabled_reason": result.get("disabled_reason") or args.reason,
            },
            ensure_ascii=False,
            indent=2,
        )
    )


def cmd_enable(args: argparse.Namespace) -> None:
    token = _login()
    agent = _resolve_admin_agent(args, token)
    result = enable_agent_record(BASE_URL, token, agent["id"])
    print(
        json.dumps(
            {
                "message": "Agent 已启用",
                "id": result.get("id") or agent.get("id"),
                "aic": result.get("aic") or agent.get("aic"),
            },
            ensure_ascii=False,
            indent=2,
        )
    )


def cmd_query(args: argparse.Namespace) -> None:
    token = _login()
    agents = query_agents(
        BASE_URL,
        token,
        "/agent/staff",
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
