# Agent 注册系统 - WEB 功能描述及 API 设计

本文档描述注册系统的 WEB 功能及对应的 API 设计。

## 功能描述

完整的注册 Web 系统提供了用户注册、登录、搜索 Agent、查看 Agent 列表、注册 Agent、审批 Agent 等功能。用户可以根据角色的不同，访问不同的模块和功能。

本项目是 Web 服务端 API 模块，使用 FastAPI、 Pydantic、 SQLModel/SQLAlchemy、Postgresql、Qdrant 等技术栈构建。

此外，与 API 配合的还有一个前端 Web 界面模块，使用 Vue3、Vite、Element-Plus、TypeScript、Pinia 和 Tailwindcss 等技术栈构建。

### 主要数据

- 用户（User）
  - 认证相关的信息：username、password、phone、verify_code 等。
  - 权限相关的信息：role 等。一个用户可以有多个角色。
  - 用户 profile 相关的信息：name、avatar 等。
  - 用户的状态：is_active 等。
  - 用户所代表的组织机构信息：组织机构名称、组织机构代码、组织机构地址等。
- Agent
  - Agent 的基本信息：name、version、description 等。
  - Agent 的状态：is_active 等。
  - Agent 的注册审批信息：申请人、申请时间、审批状态、审批人、审批时间、审批意见等。

### 角色权限

- 角色分为 Client，Staff，Admin。
- Client 角色的用户可以提交 Agent 注册申请，并管理自己的 Agent。
- Staff 角色的用户可以审批 Agent 注册申请，并可查看所有 Agent。
- Admin 角色的用户可以管理所有的用户和角色，不做 Agent 管理。
- 系统内置了第一个 Admin 账户，用户名为 admin，没有手机号。这个账户是不能删除的。

### 我的 Agent

- 这个功能是给 Client 使用的。Client 可以管理自己的 Agent。可以提交审核，等待 Staff 审批。
- 在 我的 Agent 页面中，可以查看当前用户自己的 Agent 列表。列表下面是分页控件。列表上方左侧是新建、删除（在列表中选择条目进行删除，可以选择多个）；右侧是多个过滤条件的输入和搜索、重置。
- 在列表中最左侧是选择框，用来选择后做多条删除的，然后依次显示 Agent 的信息包括：logo（暂时用占位图片），name，version，description（如果超过 20 个字符，用...表示实际内容超过 20 个字符），审批状态，审批提交时间、审批的处理时间，处理意见（如果超过 20 个字符，用...表示实际内容超过 20 个字符）。列表的最后一栏是操作，审批状态是 DRAFT 或 REJECTED 时显示"提交审核"链接；PENDING 时显示"撤销审核"；任何状态下都显示"删除"和"详情"的链接。
- 提交审核时会弹出确认对话框，确认后提交，提交成功后会更新表格，显示最新的数据。提交后，审批状态变为 PENDING。
- 撤销审核时会弹出确认对话框，确认后撤销，撤销成功后会更新表格，显示最新的数据。撤销后，审批状态变为 DRAFT。
- 删除时会弹出确认对话框，确认后删除，删除成功后会更新表格，显示最新的数据。
- 详情链接跳转到 Agent 编辑页面。页面分两个部分，一个是 Agent 审核信息，都是只读，不可修改，第二个是 Agent 基础信息，在审批状态是 APPROVED 和 PENDING 时不可修改，其它状态可以修改。
- 详情页的第一部分，是审核相关信息。包括申请时间、审批状态、审批人、审批时间、审批意见（多行文本，显示 20 行）。这个部分是只读的，不能修改。
- 详情页的第二个部分，是 Agent 的 logo（暂时用占位图片，实际功能后续实现）、name、version、是否支持 ACP/ANP/A2A 以及每种的 URL、description（支持多行文本输入，显示 20 行。）。最后有一个保存按钮，APPROVED 和 PENDING 时按钮是灰的，不能保存，其它状态可以保存。
- 在列表上方，点击新建按钮，转到新建页面。新建页面的内容和详情页的第二部分一样。最后有保存按钮，保存后回到列表页，列表数据更新。
- 在列表上方的搜索过滤条件有 Agent 的 name、version、审批状态。输入搜索条件后点击搜索按钮，列表会更新为符合条件的数据。点击重置按钮，列表会更新为缺省搜索条件的数据。
- Agent 的审批状态包括：未申请 DRAFT、审核中 PENDING、审核通过 APPROVED、审核驳回 REJECTED。
- Agent 的名称和版本号，都是必须的。它们两个联合起来是唯一的。也就是说，可以同时存在同一个名称的多个版本的 Agent。

### Agent 审批

- 这个功能是给 Staff 使用的。
- 页面主体是等待审批的 Agent 列表，列表下面是分页控件。列表上方靠右侧，有过滤条件输入及搜索、重置按钮。
- 列表中显示 Agent 的信息包括：name、version、description （如果超过 20 个字符，用...表示实际内容超过 20 个字符），以及申请人的公司名称、申请提交的时间等。列表最右侧一栏是操作，显示“审批”链接。
- 点击审批链接，跳转到审批页面。这个页面分三个部分，第一个部分是 Agent 的基本信息，第二个部分是用户信息，第三部分是审核结果。
- 审批页第一个部分是 Agent 的基本信息，包括 logo（暂时用占位图片）、name、version、是否支持 ACP/ANP/A2A 以及每种的 URL、description（支持多行文本输入，显示 20 行。）。
- 审核页第二个部分是用户信息，包括用户姓名，组织机构名称，组织机构代码，组织机构地址。
- 审核页第三部分是审核操作，需要填写审批通过还是驳回，并填写审批意见，最后有提交按钮。提交成功后返回列表页，列表数据更新。
- 在列表上方可以输入 Agent 的 name、version 进行搜索。输入搜索条件后，点击搜索按钮，列表会更新为符合条件的数据。点击重置按钮，列表会更新为缺省搜索条件的数据。

### Agent 查询

- 这个功能是给 Staff 使用的。
- 查询页面的主体是 Agent 列表。列表下面是分页控件。列表上方靠右侧是过滤条件输入及搜索、重置等功能。
- 在列表中显示 Agent 的信息包括：name、version、description（如果超过 20 个字符，用...表示实际内容超过 20 个字符），以及申请人的公司名称、申请时间、审批状态、审批人、审批时间、审批意见（多行文本，显示 20 行）。列表最右侧一栏是操作，显示“详情”链接。
- 点击详情链接，跳转到详情页面。这个页面分三个部分，第一个部分是 Agent 的基本信息，第二个部分是用户信息，第三部分是审核结果。
- 详情页和审批页是一样的。页面第三部分的审核结果可以更改后保存。
- 在列表上方可以输入 Agent 的 name、version 进行搜索，也可以选择“我处理的”和“所有人处理的”进行搜索。输入搜索条件后，点击搜索按钮，列表会更新为符合条件的数据。点击重置按钮，列表会更新为缺省搜索条件的数据。

### 账户管理

- 这个功能是给 Admin 使用的。Admin 可以管理所有的用户和角色。
- 页面主体显示 User 列表。列表下面是分页控件。列表上方，左侧是新建按钮，右侧依次是过滤条件、搜索按钮、重置按钮。
- 在列表中显示 User 的基本信息包括：username、phone、roles、name、org_name。表格最右侧是 action(操作)，有详情的链接。
- 新建时会转到新建页面，页面分两个模块，一个是账户信息，一个是个人和组织信息。账户信息中有 username，两次 password，phone（不需要验证码），roles 的多项选择，账户 is_active 的状态。个人和组织信息中，有个人姓名，avatar（暂时先用图片的占位，功能后续再加），组织名称，组织代码，组织地址。最后有一个提交按钮。
- 在列表中“操作”一栏中的“详情”链接，可以进入账户编辑页面。这个编辑页面与新建页面整体上一样，只是账户信息、个人和组织信息这两个部分，分别是一个表单，分别有提交按钮。
- 在列表上方可以输入用户名、手机号、姓名、机构名、角色等信息进行搜索。点击搜索按钮，列表会更新为符合条件的数据。点击重置按钮，列表会更新为缺省搜索条件的数据。

### Agent 公共搜索

- 这个功能是给所有用户使用的。所有用户都可以搜索 Agent。
- 在首页的搜索框中输入搜索条件，点击搜索按钮，列表会显示最匹配的 5 条数据。没有搜索时，默认显示最近的 5 条数据。点击重置按钮，列表会更新为默认的 Recent 数据。
- 每条数据显示图片（暂时用占位图片）、名称、版本号、组织机构名称、审核通过时间。图片在左侧，右侧是上下排列的名称、版本号、组织机构名称、审核通过时间。点击图片弹出详情对话框。
- 详情对话框中，显示 Agent 所属的组织单位名称，审核通过的时间，Agent 的 logo（暂时用占位图片）、name、version、是否支持 ACP/ANP/A2A 以及每种的 URL、description（支持多行文本输入，显示 20 行。）。这个对话框是只读的，不能修改。
- 搜索框中输入的数据，先做向量化处理，然后到 Qdrant 向量数据库中进行搜索，返回最匹配的 5 条数据。根据每条数据的 AgentId 到 Postgresql 中找到 Agent 数据，显示名称、版本号等信息。

### 注册认证及用户信息相关

- 注册时需要填写用户名、密码、手机号、手机验证码等信息。注册必须验证手机，用户名密码为可选。数据库中加密存储密码。
- 登录时可以用用户名和密码这两个的组合来登录，也可以用手机和验证码这两个的组合来登录。用户名和手机各自都不是必须的，但两者必须有一个不为空。
- 登录成功后会生成一个 JWT Token，作为后续请求的身份验证凭证。Token 的有效期为 1 周。Token 可以用老 Token 进行刷新。过期的 Token 可以定时进行清理，避免数据库中存储过多的无效 Token。
- 用户都可以查看和修改自己的 Profile 信息。可以用旧密码更换新密码。可以更换手机，需要再次验证手机。可以忘记密码要求重置密码，需要验证手机。
- 用户登出时会删除 Token。
- 系统内置了第一个 Admin 账户，用户名为 admin，密码 12345678，没有手机号。

## API 设计

### 用户角色

系统定义了三种用户角色：

1. **Client**: 普通用户，可以注册、管理自己的 Agent。
2. **Staff**: 工作人员，可以审核 Agent 注册申请。
3. **Admin**: 管理员，可以进行用户管理，不做 Agent 管理。

### 认证相关

- `POST /api/auth/register`: 用户注册（用户名、密码、手机号、验证码）
- `POST /api/auth/verify-code`: 获取手机验证码
- `POST /api/auth/login`: 用户登录（用户名/密码）
- `POST /api/auth/login/phone`: 手机验证码登录
- `POST /api/auth/logout`: 用户登出
- `POST /api/auth/refresh`: 刷新访问令牌
- `POST /api/auth/reset-password`: 重置密码（需验证手机）

### 账户相关

**当前用户对自己的账户可以做的操作**

- `GET /api/account/me`: 获取当前用户信息
- `PUT /api/account/me`: 更新当前用户个人信息
- `PUT /api/account/me/password`: 修改密码（需提供旧密码）
- `PUT /api/account/me/phone`: 更换手机号（需重新验证手机）

**管理员可以做的账户管理操作**

- `POST /api/account/user`: 创建新用户
- `DELETE /api/account/user/{user_id}`: 注销用户（设置为非活跃状态）
- `DELETE /api/account/user`: 批量注销用户（设置为非活跃状态）
- `PUT /api/account/user/{user_id}/roles`: 更新用户角色
- `PUT /api/account/user/{user_id}/password`: 管理员重置用户密码
- `GET /api/account/user/{user_id}`: 获取指定用户信息
- `GET /api/account/user`: 获取用户列表，支持搜索过滤

### Agent 相关

系统将 Agent API 分为三类：

**公开的 Agent API （无需登录）**

- `POST /api/agent/public/search`: 基于向量匹配搜索 Agent，返回最匹配的结果
- `GET /api/agent/public/recent`: 获取最近审批通过的 Agent，默认 5 条
- `GET /api/agent/public/{agent_id}`: 获取已审批通过的 Agent 详情

**客户端 Agent API （仅限 CLIENT 角色）**

- `POST /api/agent/client`: 创建新 Agent，保存但不提交审核
- `DELETE /api/agent/client/{agent_id}`: 设置 Agent 为非活跃状态，相当于删除
- `DELETE /api/agent/client`: 批量设置多个 Agent 为非活跃状态，相当于删除
- `PUT /api/agent/client/{agent_id}`: 更新 Agent，仅未提交审核的可更新
- `POST /api/agent/client/{agent_id}/submit`: 提交 Agent 进行审核
- `POST /api/agent/client/{agent_id}/cancel`: 撤销处于"审核中"状态的 Agent 申请
- `GET /api/agent/client`: 获取当前用户的 Agent 列表，支持搜索过滤
- `GET /api/agent/client/{agent_id}`: 获取 Agent 详情（已审批通过的或用户自己创建的）

**工作人员 Agent API （仅限 STAFF 和 ADMIN 角色）**

- `GET /api/agent/staff`: 获取所有 Agent 列表，支持按状态、创建者、处理者等条件过滤
- `GET /api/agent/staff/{agent_id}`: 获取任意 Agent 详情，无论状态
- `POST /api/agent/staff/{agent_id}/process`: 审核 Agent，设置通过/驳回及审核意见
