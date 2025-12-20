# Agent 注册系统 - 服务端 API

这是一个基于 FastAPI 开发的 Agent 注册系统的服务端 API，该系统允许用户注册 Agent 并提供简单的搜索功能，并提供与认证系统和发现系统的互联。

## 技术栈

- **Web 框架**: FastAPI
- **数据验证与解析** Pydantic V2
- **ORM**: SQLModel/SQLAlchemy
- **数据库**: PostgreSQL
- **数据库结构同步**: Alembic

## 代码风格及开发流程的规范

- **Python 版本**: 3.12+
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

## 目录结构

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
├── tests/                # 测试代码
├── .env                  # 环境变量配置
├── alembic.ini           # Alembic配置文件
├── main.py               # 应用入口点
├── requirements.txt      # Python依赖列表
```

## 开发步骤

1. 克隆代码库

```bash
git clone [registry-server-repo-url]
cd registry-server
```

2. 创建 Python 虚拟环境并安装依赖

```bash
python3.13 -m venv venv # python的路径和名字根据实际情况调整
source venv/bin/activate
pip install -r requirements.txt
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

6. 启动服务器

```bash
python main.py
```

服务器将在 http://localhost:8001 启动，API 文档可在 http://localhost:8001/docs 查看。

## 运行测试

确保在虚拟环境中，`source venv/bin/activate`，然后运行：

```bash
pytest tests/
```
