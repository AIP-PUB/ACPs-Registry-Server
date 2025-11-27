# ATR 协议实现文档

本文档说明 Registry Server 对 ATR (Agent Trusted Registration) 协议的实现情况。

## 1. 协议概述

ATR (Agent Trusted Registration) 协议是 ACPS 系统中用于智能体信任注册的协议。本 Registry Server 作为 ATR 协议的重要组成部分，主要负责：

1. **提供 AIC 验证服务**：为其他系统提供智能体身份验证接口
2. **证书吊销通知**：向 CA Server 发送智能体证书吊销通知

## 2. Registry Server 实现的 API

### 2.1 验证指定 AIC 的智能体身份并返回其 ACS 信息

**端点**: `GET {ATR_BASE_PATH}/agent/{agent_aic}`

## 3. Registry Server 调用的外部 API

### 3.1 向 CA Server 发送智能体证书吊销通知

**目标 API**: `POST {CA_SERVER_BASE_URL}/mgmt/revoke`
