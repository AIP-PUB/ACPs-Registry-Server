# Agent 注册系统 - 服务端 API

这是一个基于 FastAPI 开发的 Agent 注册系统的服务端 API，该系统允许用户注册 Agent 并提供简单的搜索功能，并提供与认证系统和发现系统的互联。

## 1. 概述

### 技术栈

- **Python 版本**: 3.13+
- **Web 框架**: FastAPI
- **数据验证与解析** Pydantic V2
- **ORM**: SQLModel/SQLAlchemy
- **数据库**: PostgreSQL
- **数据库结构同步**: Alembic
- **包管理工具**: Poetry
- **测试框架**: Pytest

### 代码风格及开发流程的规范

- **代码风格**: 遵循 PEP 8 的风格和规范
- **类型注解**: 使用 Python 3.9+ 的类型注解，无需再从 typing 模块导入 List、Dict 等类型，使代码更简洁且更符合直觉。
- **文档字符串**: 使用 Google 风格的文档字符串
- **提交信息**: 使用 [Conventional Commits](https://www.conventionalcommits.org/en/v1.0.0/) 规范
- **分支管理**: 使用 Git Flow 工作流
- **版本命名**: 使用 [Semantic Versioning](https://semver.org/) 进行版本命名
- **测试**: 使用 pytest 进行单元测试和集成测试
- **代码审查**: 使用 GitLab Merge Request 进行代码审查
- **CI/CD**: 使用 GitLab 进行持续集成和持续部署
- **代码质量**: 使用 [Flake8](http://flake8.pycqa.org/en/latest/) 检查代码质量
- **代码格式化**: 使用 [Black](https://black.readthedocs.io/en/stable/) 进行代码格式化
- **强制代码格式化**: 使用 [pre-commit](https://pre-commit.com/) 进行代码格式化和检查

### 目录结构

```
registry-server/
│
├── app/                  # 主应用目录
│   ├── account/          # 账户和认证模块
│   ├── agent/            # Agent注册和管理模块
│   ├── core/             # 核心配置和基础功能
│   ├── file/             # 文件管理模块
│   ├── sync/             # 数据同步模块
│   └── utils/            # 工具函数
│
├── alembic/              # 数据库迁移脚本
├── client/               # 客户端演示脚本
├── tests/                # 测试代码
├── .env                  # 环境变量配置
├── alembic.ini           # Alembic配置文件
├── main.py               # 应用入口点
├── run.sh                # 服务启停管理脚本
├── pyproject.toml        # 项目配置文件
└── README.md             # 项目说明文档
```

## 2. 开发步骤

1. 克隆代码库

```bash
git clone [registry-server-repo-url]
cd registry-server
```

2. 创建 Python 虚拟环境并安装依赖

本项目使用手工维护的虚拟环境 `./venv`。请先激活该环境，再执行 Poetry 安装依赖。

```bash
python3.13 -m venv venv     # 创建python虚拟环境，python的路径和名字根据实际情况调整
source venv/bin/activate    # 激活虚拟环境
pip install poetry      # 如果尚未全局安装 Poetry，可以在虚拟环境中安装
poetry install          # 安装依赖
```

3. 配置环境变量

```bash
cp .env.example .env
# 编辑 .env 文件，修改必要的配置项
```

4. 初始化数据库

使用 Alembic 进行数据库迁移和初始数据插入：

```bash
alembic upgrade head
```

这将自动完成：

- 创建所有数据库表结构
- 插入初始角色（ADMIN、STAFF、CLIENT）
- 创建默认管理员用户（用户名：`admin`，密码：`admin123`）

6. 启停服务器

后台运行：

`./run.sh` 会直接使用 `./venv/bin/python`（或 `.venv/bin/python`）启动服务，因此执行前需要先完成上面的虚拟环境创建和依赖安装。

```bash
./run.sh start      # 启动服务（若已运行则报错）
./run.sh stop       # 停止服务
./run.sh restart    # 重启服务（先停后启）
./run.sh status     # 查看服务状态
./run.sh kill-port  # 按端口杀死监听进程（PID文件丢失时的恢复手段，默认端口从配置读取）
./run.sh kill-port 8001  # 指定端口号
```

前台运行（开发调试用）：

```bash
source venv/bin/activate
python main.py
```

服务器将在 http://localhost:8001 启动，API 文档可在 http://localhost:8001/docs 查看。

## 3. 运行测试

运行测试前同样需要先激活 `./venv`。

```bash
source venv/bin/activate
pytest tests/
```

## 4. Mock 模式

本项目支持 Mock 模式，允许在开发和测试环境下无需真实外部服务即可运行。通过 `.env` 文件中的环境变量控制：

- **`CA_SERVER_MOCK`**（默认 `false`）：启用后，对 CA Server 的证书吊销通知（Agent 停用或删除时触发）将跳过真实的 HTTP 调用，直接按成功处理，业务流程不受影响。

## 5. 客户端命令

`client/` 目录下提供了演示用的客户端脚本，用于验证注册服务的功能。

### 前置条件

1. 确保注册服务已启动（`./run.sh start`）
2. 启动 CA Server（参考 [ca-server](../ca-server) 项目），或在 `.env` 中设置 `CA_SERVER_MOCK=true` 以 Mock 模式运行
3. 进入 client 目录：`cd client`

### 用户端命令 (demo_user.py)

用于模拟普通用户操作，默认使用 `demo-client / demo123` 账号。

```bash
# 确保用户账号存在（首次运行会自动注册）
python demo_user.py ensure-account

# 注册 Agent（使用 ACS 文件。beijing_urban.json 为示例文件）
python demo_user.py register --acs-path beijing_urban.json

# 注册 Agent 但不提交审核（仅创建草稿）
python demo_user.py register --acs-path beijing_urban.json --no-submit

# 注册为本体 Agent（可派生实体）
python demo_user.py register --acs-path beijing_urban.json --ontology

# 查询当前用户的 Agent
python demo_user.py query
python demo_user.py query --name "北京城区旅游智能体"
python demo_user.py query --name-like "北京"

# 删除 Agent
python demo_user.py delete --acs-path beijing_urban.json
python demo_user.py delete --aic <AIC编码>
```

### 管理员命令 (demo_admin.py)

用于模拟管理员操作，默认使用 `admin / admin123` 账号。

```bash
# 验证管理员账号
python demo_admin.py ensure-account

# 审批 Agent（多种定位方式）
python demo_admin.py approve --acs-path beijing_urban.json
python demo_admin.py approve --aic <AIC编码>
python demo_admin.py approve --name "北京城区旅游智能体" --version "1.0.0"
python demo_admin.py approve --agent-id <UUID> --comments "审批通过"

# 禁用 Agent
python demo_admin.py disable --aic <AIC编码>

# 启用 Agent
python demo_admin.py enable --aic <AIC编码>

# 查询全局 Agent 列表
python demo_admin.py query
python demo_admin.py query --is-active true --is-deleted false
```

### 完整验证流程示例

```bash
cd client

# 1. 确保账号存在
python demo_user.py ensure-account
python demo_admin.py ensure-account

# 2. 用户注册 Agent
python demo_user.py register --acs-path beijing_urban.json

# 3. 管理员审批
python demo_admin.py approve --acs-path beijing_urban.json --comments "审批通过"

# 4. 查询验证
python demo_user.py query --name "北京城区旅游智能体"
```

### 配置说明

如需修改 API 地址或账号信息，编辑对应脚本顶部的常量：

- `demo_user.py`: `BASE_URL`, `CLIENT_USERNAME`, `CLIENT_PASSWORD`
- `demo_admin.py`: `BASE_URL`, `ADMIN_USERNAME`, `ADMIN_PASSWORD`
