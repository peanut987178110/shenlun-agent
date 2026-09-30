"""重置账号密码。数据库只存密码哈希，忘记密码时无法找回，只能重置。

用法（在项目根目录）：
    .venv\\Scripts\\python.exe scripts\\reset_password.py student teacher
    .venv\\Scripts\\python.exe scripts\\reset_password.py student --password 自己定的密码

不指定 --password 时为每个账号生成随机密码并打印。
"""
from __future__ import annotations

import argparse
import asyncio
import secrets
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from sqlalchemy import select  # noqa: E402

from app.core.security import hash_password, password_issue  # noqa: E402
from app.db.models import User  # noqa: E402
from app.db.session import SessionLocal, init_db  # noqa: E402


async def main() -> int:
    ap = argparse.ArgumentParser(description="重置账号密码")
    ap.add_argument("usernames", nargs="+")
    ap.add_argument("--password", default="", help="指定新密码（至少 8 位）；不指定则随机生成")
    args = ap.parse_args()
    if args.password and (issue := password_issue(args.password)):
        print(f"[错误] {issue}")
        return 1

    await init_db()
    code = 0
    async with SessionLocal() as db:
        for name in args.usernames:
            u = (await db.execute(select(User).where(User.username == name))).scalar_one_or_none()
            if not u:
                print(f"[跳过] 账号 {name} 不存在")
                code = 1
                continue
            pwd = args.password or secrets.token_urlsafe(9)
            u.password_hash = hash_password(pwd)
            u.active = True
            print(f"{name}（{'教师' if u.role == 'teacher' else '学员'}） 新密码：{pwd}")
        await db.commit()
    return code


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
