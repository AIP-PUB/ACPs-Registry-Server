"""
IP访问限制模块
用于限制特定端点的IP访问权限
"""

import ipaddress
import logging
from typing import List
from fastapi import Request, HTTPException, status

logger = logging.getLogger(__name__)


def parse_allowed_ips(ip_list_str: str) -> List:
    """
    解析逗号分隔的IP地址和CIDR网络列表

    Args:
        ip_list_str: 逗号分隔的IP地址字符串，支持单个IP和CIDR网络

    Returns:
        List[ipaddress.IPv4Network | ipaddress.IPv6Network]: 解析后的网络对象列表
    """
    allowed_networks = []
    if not ip_list_str:
        return allowed_networks

    for ip_str in ip_list_str.split(","):
        ip_str = ip_str.strip()
        if not ip_str:
            continue
        try:
            # 处理单个IP和CIDR网络
            if "/" not in ip_str:
                # 如果没有指定子网，为IPv4添加/32，为IPv6添加/128
                if ":" in ip_str:
                    ip_str += "/128"  # IPv6
                else:
                    ip_str += "/32"  # IPv4
            allowed_networks.append(ipaddress.ip_network(ip_str, strict=False))
        except ValueError as e:
            logger.warning(
                f"Invalid IP address or network in allowed IP list: {ip_str}, error: {e}"
            )

    return allowed_networks


def create_ip_restriction_middleware(allowed_networks: List, path_prefix: str):
    """
    创建IP限制中间件

    Args:
        allowed_networks: 允许访问的网络列表
        path_prefix: 需要限制的路径前缀

    Returns:
        中间件函数
    """

    async def ip_restriction_middleware(request: Request, call_next):
        """中间件函数：基于客户端IP限制对特定端点的访问"""
        if request.url.path.startswith(path_prefix):
            client_ip = request.client.host
            if client_ip:
                try:
                    client_ip_obj = ipaddress.ip_address(client_ip)
                    # 检查客户端IP是否在任何允许的网络中
                    allowed = any(
                        client_ip_obj in network for network in allowed_networks
                    )

                    if not allowed:
                        logger.warning(
                            f"Access denied for IP: {client_ip} to path: {request.url.path}"
                        )
                        raise HTTPException(
                            status_code=status.HTTP_403_FORBIDDEN,
                            detail="Access denied: IP address not allowed",
                        )
                except ValueError as e:
                    logger.error(f"Invalid client IP address: {client_ip}, error: {e}")
                    raise HTTPException(
                        status_code=status.HTTP_403_FORBIDDEN,
                        detail="Access denied: Invalid client IP address",
                    )

        response = await call_next(request)
        return response

    return ip_restriction_middleware
