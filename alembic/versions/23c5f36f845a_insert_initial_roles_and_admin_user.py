"""insert_initial_roles_and_admin_user

Revision ID: 23c5f36f845a
Revises: f8e7c95b4d12
Create Date: 2025-09-07 20:23:08.705898

"""

from typing import Sequence, Union
from datetime import datetime
import uuid

from alembic import op
import sqlalchemy as sa
from sqlalchemy.sql import table, column
from sqlalchemy import String, Boolean, DateTime, Uuid
import uuid6

# 导入密码哈希函数
import sys
import os

# 添加项目根目录到Python路径
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
from app.core.auth import get_password_hash
from app.utils.utils import get_beijing_time

# revision identifiers, used by Alembic.
revision: str = "23c5f36f845a"
down_revision: Union[str, None] = "f8e7c95b4d12"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Insert initial roles and admin user."""
    # 定义表结构（用于数据操作）
    role_table = table(
        "account_role",
        column("id", Uuid),
        column("name", String),
        column("description", String),
    )

    user_table = table(
        "account_user",
        column("id", Uuid),
        column("username", String),
        column("hashed_password", String),
        column("is_active", Boolean),
        column("name", String),
        column("created_at", DateTime),
        column("updated_at", DateTime),
    )

    user_role_link_table = table(
        "account_user_role_link", column("user_id", Uuid), column("role_id", Uuid)
    )

    # 获取数据库连接
    conn = op.get_bind()

    # 生成UUID
    admin_role_id = uuid6.uuid7()
    staff_role_id = uuid6.uuid7()
    client_role_id = uuid6.uuid7()
    admin_user_id = uuid6.uuid7()

    current_time = get_beijing_time()

    # 1. 检查并插入角色（确保幂等性）
    existing_roles = conn.execute(
        sa.text(
            "SELECT name FROM account_role WHERE name IN ('ADMIN', 'STAFF', 'CLIENT')"
        )
    ).fetchall()
    existing_role_names = {row[0] for row in existing_roles}

    roles_to_insert = []
    role_id_map = {}

    if "ADMIN" not in existing_role_names:
        roles_to_insert.append(
            {"id": admin_role_id, "name": "ADMIN", "description": "管理员角色"}
        )
        role_id_map["ADMIN"] = admin_role_id
    else:
        # 获取现有ADMIN角色的ID
        result = conn.execute(
            sa.text("SELECT id FROM account_role WHERE name = 'ADMIN'")
        ).fetchone()
        role_id_map["ADMIN"] = result[0]
        # 更新描述（如果为空）
        conn.execute(
            sa.text(
                "UPDATE account_role SET description = '管理员角色' WHERE name = 'ADMIN' AND (description IS NULL OR description = '')"
            )
        )

    if "STAFF" not in existing_role_names:
        roles_to_insert.append(
            {"id": staff_role_id, "name": "STAFF", "description": "员工角色"}
        )
        role_id_map["STAFF"] = staff_role_id
    else:
        # 获取现有STAFF角色的ID
        result = conn.execute(
            sa.text("SELECT id FROM account_role WHERE name = 'STAFF'")
        ).fetchone()
        role_id_map["STAFF"] = result[0]
        # 更新描述（如果为空）
        conn.execute(
            sa.text(
                "UPDATE account_role SET description = '员工角色' WHERE name = 'STAFF' AND (description IS NULL OR description = '')"
            )
        )

    if "CLIENT" not in existing_role_names:
        roles_to_insert.append(
            {"id": client_role_id, "name": "CLIENT", "description": "客户角色"}
        )
        role_id_map["CLIENT"] = client_role_id
    else:
        # 获取现有CLIENT角色的ID
        result = conn.execute(
            sa.text("SELECT id FROM account_role WHERE name = 'CLIENT'")
        ).fetchone()
        role_id_map["CLIENT"] = result[0]
        # 更新描述（如果为空）
        conn.execute(
            sa.text(
                "UPDATE account_role SET description = '客户角色' WHERE name = 'CLIENT' AND (description IS NULL OR description = '')"
            )
        )

    # 批量插入角色
    if roles_to_insert:
        op.bulk_insert(role_table, roles_to_insert)

    # 2. 检查并插入管理员用户（确保幂等性）
    existing_admin = conn.execute(
        sa.text("SELECT id FROM account_user WHERE username = 'admin'")
    ).fetchone()

    if not existing_admin:
        # 插入管理员用户
        op.bulk_insert(
            user_table,
            [
                {
                    "id": admin_user_id,
                    "username": "admin",
                    "hashed_password": get_password_hash("admin123"),
                    "is_active": True,
                    "name": "管理员",
                    "created_at": current_time,
                    "updated_at": current_time,
                }
            ],
        )

        # 3. 为管理员用户分配所有角色
        user_roles_to_insert = [
            {"user_id": admin_user_id, "role_id": role_id_map["ADMIN"]},
            {"user_id": admin_user_id, "role_id": role_id_map["STAFF"]},
            {"user_id": admin_user_id, "role_id": role_id_map["CLIENT"]},
        ]
        op.bulk_insert(user_role_link_table, user_roles_to_insert)


def downgrade() -> None:
    """Remove initial roles and admin user."""
    # 获取数据库连接
    conn = op.get_bind()

    # 1. 删除管理员用户的角色关联
    conn.execute(
        sa.text(
            """
        DELETE FROM account_user_role_link 
        WHERE user_id IN (SELECT id FROM account_user WHERE username = 'admin')
    """
        )
    )

    # 2. 删除管理员用户
    conn.execute(sa.text("DELETE FROM account_user WHERE username = 'admin'"))

    # 3. 删除角色（谨慎操作，只删除没有其他用户关联的角色）
    conn.execute(
        sa.text(
            """
        DELETE FROM account_role 
        WHERE name IN ('ADMIN', 'STAFF', 'CLIENT') 
        AND id NOT IN (SELECT DISTINCT role_id FROM account_user_role_link)
    """
        )
    )
