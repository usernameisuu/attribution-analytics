"""Run on the remote host after migrations; never creates default passwords."""
import os
from sqlalchemy import select
from .db import SessionFactory, User
from .security import password_hash


def main():
    username = os.environ["BOOTSTRAP_USERNAME"]
    password = os.environ["BOOTSTRAP_PASSWORD"]
    if password.startswith("CHANGE_"):
        raise ValueError("请配置随机初始密码")
    encoded = password_hash(password)
    with SessionFactory() as db:
        if db.scalar(select(User).where(User.username == username)):
            raise ValueError("用户已经存在，不自动覆盖密码或权限")
        db.add(User(username=username, password_hash=encoded, role="analyst", domains=["ecommerce", "consumer"]))
        db.commit()
    print("分析师账号已创建；未输出密码。")


if __name__ == "__main__":
    main()
