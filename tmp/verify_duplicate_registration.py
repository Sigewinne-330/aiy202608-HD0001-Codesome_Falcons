# -*- coding: utf-8 -*-
"""验收脚本：注册重复账号提示「邮箱或用户名已被注册」
场景：
1. 用户名重复（新邮箱 + 有效 proof）→ 400 DUPLICATE_ACCOUNT_ERROR
2. 邮箱重复（新用户名 + 有效 proof）→ 400 DUPLICATE_ACCOUNT_ERROR
3. proof 无效 → 400 GENERIC_REGISTRATION_ERROR（与重复文案可区分）
4. 并发唯一约束兜底（IntegrityError 分支）→ 400 DUPLICATE_ACCOUNT_ERROR
运行：backend/venv311/Scripts/python.exe tmp/verify_duplicate_registration.py
"""
import sys
import unittest
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

BACKEND_DIR = Path(__file__).resolve().parents[1] / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from database import Base, get_db  # noqa: E402
import models  # noqa: E402,F401
from models.app_user import AppUser as User  # noqa: E402
from routers.auth import router  # noqa: E402
from services.email_service import get_email_sender  # noqa: E402
from services.email_verification import (  # noqa: E402
    DUPLICATE_ACCOUNT_ERROR,
    GENERIC_REGISTRATION_ERROR,
)
from services.verification_policy import (  # noqa: E402
    VerificationPolicy,
    get_verification_policy,
)


class FakeEmailSender:
    def __init__(self):
        self.messages = []

    def send_verification_code(self, recipient, code, expires_in_minutes):
        self.messages.append({"recipient": recipient, "code": code})


class DuplicateRegistrationMessageTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        self.SessionLocal = sessionmaker(bind=self.engine)
        Base.metadata.drop_all(self.engine)
        Base.metadata.create_all(self.engine)

        self.sender = FakeEmailSender()
        app = FastAPI()
        app.include_router(router)

        def override_db():
            db = self.SessionLocal()
            try:
                yield db
            finally:
                db.close()

        app.dependency_overrides[get_db] = override_db
        app.dependency_overrides[get_email_sender] = lambda: self.sender
        app.dependency_overrides[get_verification_policy] = lambda: VerificationPolicy(
            code_ttl_seconds=600,
            proof_ttl_seconds=900,
            max_attempts=3,
            resend_cooldown_seconds=60,
            email_limit_per_hour=50,
            ip_limit_per_hour=100,
        )
        self.client = TestClient(app)

    def tearDown(self):
        self.engine.dispose()

    def _issue_proof(self, email):
        r = self.client.post("/api/auth/verification-codes", json={"email": email})
        self.assertEqual(202, r.status_code, r.text)
        code = self.sender.messages[-1]["code"]
        r = self.client.post(
            "/api/auth/verification-codes/verify",
            json={"email": email, "code": code},
        )
        self.assertEqual(200, r.status_code, r.text)
        return r.json()["verification_token"]

    def _register(self, username, email, token):
        return self.client.post(
            "/api/auth/register",
            json={
                "username": username,
                "email": email,
                "password": "secure123",
                "verification_token": token,
            },
        )

    def test_01_baseline_register_success(self):
        token = self._issue_proof("first@example.com")
        r = self._register("studentA", "first@example.com", token)
        self.assertEqual(200, r.status_code, r.text)

    def test_02_duplicate_username_gets_new_message(self):
        token = self._issue_proof("first@example.com")
        self.assertEqual(200, self._register("studentA", "first@example.com", token).status_code)
        # 新邮箱 + 有效 proof + 已占用用户名
        token2 = self._issue_proof("second@example.com")
        r = self._register("studentA", "second@example.com", token2)
        self.assertEqual(400, r.status_code, r.text)
        self.assertEqual(DUPLICATE_ACCOUNT_ERROR, r.json()["detail"])
        self.assertEqual("邮箱或用户名已被注册", r.json()["detail"])

    def test_03_duplicate_email_gets_new_message(self):
        # 已注册邮箱不会再发验证码（安全设计），故先取 proof，再模拟并发场景：
        # 另一会话抢先注册了该邮箱
        token = self._issue_proof("first@example.com")
        with self.SessionLocal() as db:
            db.add(User(username="studentA", password="x", email="first@example.com"))
            db.commit()
        r = self._register("studentB", "first@example.com", token)
        self.assertEqual(400, r.status_code, r.text)
        self.assertEqual(DUPLICATE_ACCOUNT_ERROR, r.json()["detail"])

    def test_04_invalid_proof_keeps_generic_message(self):
        r = self._register("studentC", "nobody@example.com", "x" * 32)
        self.assertEqual(400, r.status_code, r.text)
        self.assertEqual(GENERIC_REGISTRATION_ERROR, r.json()["detail"])
        self.assertNotEqual(DUPLICATE_ACCOUNT_ERROR, r.json()["detail"])

    def test_05_two_messages_are_distinct(self):
        self.assertNotEqual(DUPLICATE_ACCOUNT_ERROR, GENERIC_REGISTRATION_ERROR)


if __name__ == "__main__":
    unittest.main(verbosity=2)
