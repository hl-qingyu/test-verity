"""Initialize the first administrator locally; no public registration endpoint."""

import getpass
import sys

from sqlalchemy import select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.db.models import UserAccount
from app.db.session import get_engine
from app.security.passwords import hash_password


def create_initial_admin(password: str) -> None:
    if not 8 <= len(password) <= 128 or password.isspace():
        raise ValueError("密码须为8–128个字符，不能全为空格。")
    encoded = hash_password(password)
    with Session(get_engine()) as db, db.begin():
        db.execute(text("SELECT pg_advisory_xact_lock(2026091101)"))
        if db.scalar(select(UserAccount.id).where(UserAccount.platform_role == "ADMIN")):
            raise ValueError("管理员已存在，不会覆盖账号或重置密码。")
        if db.scalar(select(UserAccount.id).where(UserAccount.login_name == "admin")):
            raise ValueError("admin账号已存在，不会覆盖。")
        db.add(
            UserAccount(
                login_name="admin",
                display_name="管理员",
                password_hash=encoded,
                platform_role="ADMIN",
            )
        )


def main() -> int:
    if not sys.stdin.isatty():
        print("请在本机交互终端运行，密码使用隐藏输入，不接受命令行明文密码。")
        return 1
    try:
        password = getpass.getpass("设置admin密码（8–128个字符）：")
        if password != getpass.getpass("再次输入密码："):
            print("两次密码不一致，未创建账号。")
            return 1
        create_initial_admin(password)
    except ValueError as exc:
        print(str(exc))
        return 1
    except SQLAlchemyError:
        print("数据库操作失败，请检查连接和迁移状态。未输出连接信息。")
        return 1
    except (EOFError, KeyboardInterrupt):
        print("\n已取消。")
        return 1
    print("初始管理员admin已创建，可以登录。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
