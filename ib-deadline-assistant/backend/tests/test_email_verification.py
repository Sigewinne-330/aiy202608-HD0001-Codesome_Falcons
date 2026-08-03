import sys
import unittest
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from database import Base, get_db  # noqa: E402
from config import settings  # noqa: E402
import models  # noqa: E402,F401
from models.email_verification import EmailVerification  # noqa: E402
from models.app_user import AppUser as User  # noqa: E402
from routers.auth import router  # noqa: E402
from services.email_service import (  # noqa: E402
    EmailDeliveryError,
    SMTPConfig,
    SMTPEmailSender,
    get_email_sender,
)
from services.email_verification import (  # noqa: E402
    create_verification_request,
    mark_delivery_succeeded,
    utcnow,
)
from services.verification_policy import (  # noqa: E402
    VerificationPolicy,
    get_verification_policy,
)


class FakeEmailSender:
    def __init__(self):
        self.messages = []
        self.error = None

    def send_verification_code(self, recipient, code, expires_in_minutes):
        if self.error:
            raise self.error
        self.messages.append(
            {
                "recipient": recipient,
                "code": code,
                "expires_in_minutes": expires_in_minutes,
            }
        )


class EmailVerificationApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        cls.SessionLocal = sessionmaker(
            autocommit=False,
            autoflush=False,
            bind=cls.engine,
        )

    @classmethod
    def tearDownClass(cls):
        cls.engine.dispose()

    def setUp(self):
        Base.metadata.drop_all(self.engine)
        Base.metadata.create_all(self.engine)
        self.sender = FakeEmailSender()
        self.policy = VerificationPolicy(
            code_ttl_seconds=600,
            proof_ttl_seconds=900,
            max_attempts=3,
            resend_cooldown_seconds=60,
            email_limit_per_hour=5,
            ip_limit_per_hour=20,
        )

        app = FastAPI()
        app.include_router(router)

        def override_db():
            db = self.SessionLocal()
            try:
                yield db
            finally:
                db.close()

        def override_sender():
            return self.sender

        def override_policy():
            return self.policy

        app.dependency_overrides[get_db] = override_db
        app.dependency_overrides[get_email_sender] = override_sender
        app.dependency_overrides[get_verification_policy] = override_policy
        self.client = TestClient(app)

    def _request_code(self, email="student@example.com", expected_status=202):
        response = self.client.post(
            "/api/auth/verification-codes", json={"email": email}
        )
        self.assertEqual(expected_status, response.status_code, response.text)
        return response

    def _last_code(self):
        return self.sender.messages[-1]["code"]

    def _wrong_code(self, code):
        return "000000" if code != "000000" else "000001"

    def _verify(self, email, code, expected_status=200):
        response = self.client.post(
            "/api/auth/verification-codes/verify",
            json={"email": email, "code": code},
        )
        self.assertEqual(expected_status, response.status_code, response.text)
        return response

    def _registration_payload(self, email, token, username="newstudent"):
        return {
            "username": username,
            "email": email,
            "password": "secure123",
            "verification_token": token,
        }

    def _issue_proof(self, email="student@example.com"):
        self._request_code(email)
        response = self._verify(email, self._last_code())
        return response.json()["verification_token"]

    def _age_sent_requests(self, email, seconds=120):
        with self.SessionLocal() as db:
            records = (
                db.query(EmailVerification)
                .filter(EmailVerification.email == email.lower())
                .all()
            )
            for record in records:
                record.created_at = utcnow() - timedelta(seconds=seconds)
            db.commit()

    def test_successful_verification_and_registration(self):
        request_response = self._request_code(" Student@Example.com ")
        self.assertNotIn("code", request_response.json())
        self.assertEqual("student@example.com", self.sender.messages[0]["recipient"])

        code = self._last_code()
        proof_response = self._verify("student@example.com", code)
        token = proof_response.json()["verification_token"]
        registration = self.client.post(
            "/api/auth/register",
            json=self._registration_payload("STUDENT@example.com", token),
        )
        self.assertEqual(200, registration.status_code, registration.text)
        self.assertEqual("student@example.com", registration.json()["user"]["email"])
        self.assertTrue(registration.json()["access_token"])

        with self.SessionLocal() as db:
            record = db.query(EmailVerification).one()
            self.assertNotEqual(code, record.code_digest)
            self.assertNotEqual(token, record.registration_token_digest)
            self.assertIsNotNone(record.consumed_at)
            self.assertNotIn("code", record.__table__.columns.keys())

    def test_wrong_code_increments_attempts(self):
        self._request_code()
        code = self._last_code()
        self._verify("student@example.com", self._wrong_code(code), 400)
        with self.SessionLocal() as db:
            self.assertEqual(1, db.query(EmailVerification).one().failed_attempts)

    def test_expired_code_is_rejected(self):
        self._request_code()
        code = self._last_code()
        with self.SessionLocal() as db:
            record = db.query(EmailVerification).one()
            record.expires_at = utcnow() - timedelta(seconds=1)
            db.commit()
        self._verify("student@example.com", code, 400)

    def test_new_request_invalidates_old_code(self):
        self._request_code()
        old_code = self._last_code()
        self._age_sent_requests("student@example.com")
        self._request_code()
        new_code = self._last_code()

        self._verify("student@example.com", old_code, 400)
        self._verify("student@example.com", new_code, 200)

    def test_code_can_only_be_verified_once(self):
        self._request_code()
        code = self._last_code()
        self._verify("student@example.com", code, 200)
        self._verify("student@example.com", code, 400)

    def test_correct_code_works_on_final_allowed_attempt(self):
        self._request_code()
        code = self._last_code()
        wrong = self._wrong_code(code)
        self._verify("student@example.com", wrong, 400)
        self._verify("student@example.com", wrong, 400)
        self._verify("student@example.com", code, 200)

    def test_guess_budget_locks_challenge(self):
        self._request_code()
        code = self._last_code()
        wrong = self._wrong_code(code)
        for _ in range(self.policy.max_attempts):
            self._verify("student@example.com", wrong, 400)
        self._verify("student@example.com", code, 400)
        with self.SessionLocal() as db:
            self.assertIsNotNone(db.query(EmailVerification).one().invalidated_at)

    def test_resend_cooldown(self):
        self._request_code()
        response = self._request_code(expected_status=429)
        self.assertIn("Retry-After", response.headers)
        self.assertEqual(1, len(self.sender.messages))

    def test_email_hourly_limit(self):
        self.policy = VerificationPolicy(
            **{
                **self.policy.__dict__,
                "email_limit_per_hour": 2,
            }
        )
        self._request_code()
        self._age_sent_requests("student@example.com")
        self._request_code()
        self._age_sent_requests("student@example.com")
        self._request_code(expected_status=429)
        self.assertEqual(2, len(self.sender.messages))

    def test_ip_hourly_limit(self):
        self.policy = VerificationPolicy(
            **{
                **self.policy.__dict__,
                "ip_limit_per_hour": 2,
            }
        )
        self._request_code("one@example.com")
        self._request_code("two@example.com")
        self._request_code("three@example.com", expected_status=429)

    def test_registration_without_verification_is_rejected(self):
        response = self.client.post(
            "/api/auth/register",
            json={
                "username": "newstudent",
                "email": "student@example.com",
                "password": "secure123",
            },
        )
        self.assertEqual(422, response.status_code)
        with self.SessionLocal() as db:
            self.assertEqual(0, db.query(User).count())

    def test_mismatched_email_proof_is_rejected(self):
        token = self._issue_proof()
        response = self.client.post(
            "/api/auth/register",
            json=self._registration_payload("other@example.com", token),
        )
        self.assertEqual(400, response.status_code, response.text)

    def test_expired_proof_is_rejected(self):
        token = self._issue_proof()
        with self.SessionLocal() as db:
            record = db.query(EmailVerification).one()
            record.proof_expires_at = utcnow() - timedelta(seconds=1)
            db.commit()
        response = self.client.post(
            "/api/auth/register",
            json=self._registration_payload("student@example.com", token),
        )
        self.assertEqual(400, response.status_code, response.text)

    def test_registration_proof_can_only_be_consumed_once(self):
        token = self._issue_proof()
        first = self.client.post(
            "/api/auth/register",
            json=self._registration_payload("student@example.com", token),
        )
        self.assertEqual(200, first.status_code, first.text)
        second = self.client.post(
            "/api/auth/register",
            json=self._registration_payload(
                "student@example.com", token, username="anotherstudent"
            ),
        )
        self.assertEqual(400, second.status_code, second.text)
        with self.SessionLocal() as db:
            self.assertEqual(1, db.query(User).count())

    def test_unique_conflict_rolls_back_user_and_proof_consumption(self):
        token = self._issue_proof()
        error = IntegrityError("INSERT INTO users", {}, Exception("duplicate"))
        with patch.object(self.SessionLocal.class_, "commit", side_effect=error):
            response = self.client.post(
                "/api/auth/register",
                json=self._registration_payload("student@example.com", token),
            )
        self.assertEqual(400, response.status_code, response.text)
        with self.SessionLocal() as db:
            self.assertEqual(0, db.query(User).count())
            self.assertIsNone(db.query(EmailVerification).one().consumed_at)

    def test_existing_email_gets_generic_response_and_no_message(self):
        with self.SessionLocal() as db:
            db.add(
                User(
                    username="existing",
                    email="existing@example.com",
                    password="not-used",
                )
            )
            db.commit()
        response = self._request_code("EXISTING@example.com")
        self.assertIn("message", response.json())
        self.assertEqual([], self.sender.messages)
        with self.SessionLocal() as db:
            record = db.query(EmailVerification).one()
            self.assertEqual("suppressed", record.delivery_status)
            self.assertIsNotNone(record.invalidated_at)

    def test_email_becomes_registered_after_verification(self):
        token = self._issue_proof()
        with self.SessionLocal() as db:
            db.add(
                User(
                    username="racing-user",
                    email="student@example.com",
                    password="not-used",
                )
            )
            db.commit()
        response = self.client.post(
            "/api/auth/register",
            json=self._registration_payload("student@example.com", token),
        )
        self.assertEqual(400, response.status_code, response.text)
        with self.SessionLocal() as db:
            self.assertEqual(1, db.query(User).count())
            self.assertIsNone(db.query(EmailVerification).one().consumed_at)

    def test_existing_email_is_rate_limited_without_sending(self):
        with self.SessionLocal() as db:
            db.add(
                User(
                    username="existing",
                    email="existing@example.com",
                    password="not-used",
                )
            )
            db.commit()
        self._request_code("existing@example.com")
        self._request_code("existing@example.com", expected_status=429)
        self.assertEqual([], self.sender.messages)

    def test_newest_request_wins_when_delivery_finishes_out_of_order(self):
        with self.SessionLocal() as db:
            older, _ = create_verification_request(
                db,
                "race@example.com",
                "first-ip",
                self.policy,
                settings.SECRET_KEY,
            )
            newer, _ = create_verification_request(
                db,
                "race@example.com",
                "second-ip",
                self.policy,
                settings.SECRET_KEY,
            )
            mark_delivery_succeeded(db, newer)
            mark_delivery_succeeded(db, older)
            db.refresh(older)
            db.refresh(newer)
            self.assertIsNotNone(older.invalidated_at)
            self.assertIsNone(newer.invalidated_at)

    def test_email_delivery_failure_invalidates_challenge(self):
        self.sender.error = EmailDeliveryError("provider failed")
        self._request_code(expected_status=503)
        with self.SessionLocal() as db:
            record = db.query(EmailVerification).one()
            self.assertEqual("failed", record.delivery_status)
            self.assertIsNotNone(record.invalidated_at)

    def test_email_timeout_invalidates_challenge_and_allows_retry(self):
        self.sender.error = TimeoutError("network timeout")
        self._request_code(expected_status=503)
        self.sender.error = None
        self._request_code(expected_status=202)
        self.assertEqual(1, len(self.sender.messages))

    def test_invalid_email_header_is_a_delivery_error(self):
        sender = SMTPEmailSender(
            SMTPConfig(
                host="smtp.example.com",
                port=587,
                username="",
                password="",
                from_email="invalid@example.com\nBcc: attacker@example.com",
                from_name="IB Deadline Assistant",
                use_starttls=True,
                use_ssl=False,
                timeout_seconds=10,
            )
        )
        with self.assertRaises(EmailDeliveryError):
            sender.send_verification_code("student@example.com", "123456", 10)

    def test_invalid_request_shapes_are_rejected(self):
        self._request_code("not-an-email", expected_status=422)
        response = self.client.post(
            "/api/auth/verification-codes/verify",
            json={"email": "student@example.com", "code": "12ab"},
        )
        self.assertEqual(422, response.status_code)
        response = self.client.post(
            "/api/auth/register",
            json={
                "username": "x",
                "email": "student@example.com",
                "password": "short",
                "verification_token": "tiny",
            },
        )
        self.assertEqual(422, response.status_code)


if __name__ == "__main__":
    unittest.main()
