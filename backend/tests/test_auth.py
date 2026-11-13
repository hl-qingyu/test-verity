"""Set RUN_AUTH_DB_TESTS=1 to verify migrated PostgreSQL inside rollback-only transactions."""

import os
import secrets
import unittest
from datetime import UTC, datetime, timedelta
from unittest.mock import patch

from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import func, select, update
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session
from test_password_transport import EncryptedClient

from app.core.config import COOKIE_NAME
from app.db.models import Project, ProjectMember, UserAccount, UserSession
from app.db.session import get_db, get_engine
from app.main import app
from app.modules.accounts.schemas import UserFields
from app.security import passwords, rate_limit

ORIGIN = {"Origin": "http://127.0.0.1:5173"}


class PasswordTests(unittest.TestCase):
    def test_account_role_defaults_and_validation(self) -> None:
        fields = {"login_name": "role_check", "display_name": "角色检查"}
        self.assertEqual(UserFields(**fields).platform_role, "TEST")
        for role in ("ADMIN", "TEST", "DEV", "PRODUCT", "MANAGER", "USER"):
            with self.subTest(role=role):
                self.assertEqual(UserFields(**fields, platform_role=role).platform_role, role)
        for role in ("admin", "OWNER", "", "MANAGER "):
            with self.subTest(role=role), self.assertRaises(ValidationError):
                UserFields(**fields, platform_role=role)

    def test_password_hash_is_salted_and_verification_rejects_bad_input(self) -> None:
        password = secrets.token_urlsafe(16)
        encoded = passwords.hash_password(password)
        self.assertNotIn(password, encoded)
        self.assertNotEqual(encoded, passwords.hash_password(password))
        self.assertTrue(passwords.verify_password(password, encoded))
        self.assertFalse(passwords.verify_password(password + "x", encoded))
        self.assertFalse(passwords.verify_password(password, "invalid"))
        self.assertFalse(passwords.verify_password(password, encoded.replace("32768", "999999999")))

    def test_validation_never_returns_password_and_origin_is_required(self) -> None:
        with TestClient(app) as client:
            secret = secrets.token_urlsafe(16)
            response = client.post(
                "/api/auth/login", json={"login_name": "!", "password": secret}, headers=ORIGIN
            )
            self.assertEqual(response.status_code, 422)
            self.assertNotIn(secret, response.text)
            self.assertEqual(response.json(), {"detail": "invalid_request"})
            response = client.post(
                "/api/auth/login", json={"login_name": "abc", "password": secret}
            )
            self.assertEqual(response.status_code, 403)
            self.assertEqual(
                client.post(
                    "/api/auth/logout", headers={"Origin": "https://evil.invalid"}
                ).status_code,
                403,
            )


@unittest.skipUnless(
    os.environ.get("RUN_AUTH_DB_TESTS") == "1", "requires explicit PostgreSQL test opt-in"
)
class AuthDatabaseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.password = secrets.token_urlsafe(18)
        cls.encoded = passwords.hash_password(cls.password)

    def setUp(self) -> None:
        rate_limit._login_windows.clear()
        self.connection = get_engine().connect()
        self.transaction = self.connection.begin()

        def db_override():
            with Session(
                self.connection, join_transaction_mode="create_savepoint", expire_on_commit=False
            ) as db:
                yield db

        app.dependency_overrides[get_db] = db_override
        self.prefix = "check_" + secrets.token_hex(5)
        with Session(self.connection, join_transaction_mode="create_savepoint") as db:
            self.admin = UserAccount(
                login_name=self.prefix + "_admin",
                display_name="检查管理员",
                password_hash=self.encoded,
                platform_role="ADMIN",
            )
            self.member = UserAccount(
                login_name=self.prefix + "_member",
                display_name="检查普通用户",
                password_hash=self.encoded,
                platform_role="USER",
            )
            db.add_all([self.admin, self.member])
            db.flush()
            self.admin_id, self.member_id = self.admin.id, self.member.id
            self.admin_name, self.member_name = self.admin.login_name, self.member.login_name
            db.commit()
        self.client = EncryptedClient(app)
        self.client.__enter__()

    def tearDown(self) -> None:
        self.client.__exit__(None, None, None)
        app.dependency_overrides.clear()
        self.transaction.rollback()
        self.connection.close()
        rate_limit._login_windows.clear()

    def login(self, name: str | None = None, password: str | None = None):
        return self.client.post(
            "/api/auth/login",
            headers=ORIGIN,
            json={"login_name": name or self.admin_name, "password": password or self.password},
        )

    def session_cookie(self) -> str:
        return self.client.cookies.get(COOKIE_NAME)

    def read_me(self, token: str):
        return self.client.get("/api/auth/me", headers={"Cookie": f"{COOKIE_NAME}={token}"})

    def test_login_persistence_expiry_logout_and_no_secret_response(self) -> None:
        self.assertEqual(self.client.get("/api/auth/me").status_code, 401)
        wrong = self.login(password="wrong-password")
        self.assertEqual(wrong.status_code, 401)
        self.assertEqual(wrong.json(), self.login(name=self.prefix + "_missing").json())
        response = self.login(name=self.admin_name.upper())
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            set(response.json()), {"id", "login_name", "display_name", "platform_role"}
        )
        cookie_header = response.headers["set-cookie"]
        self.assertIn("HttpOnly", cookie_header)
        self.assertIn("Max-Age=28800", cookie_header)
        self.assertIn("SameSite=lax", cookie_header)
        self.assertIn("Path=/api", cookie_header)
        self.assertEqual(response.headers["cache-control"], "no-store")
        token = self.session_cookie()
        with Session(self.connection, join_transaction_mode="create_savepoint") as db:
            stored = db.scalar(select(UserSession).where(UserSession.user_id == self.admin_id))
            self.assertEqual(stored.token_hash, passwords.token_hash(token))
            self.assertNotEqual(stored.token_hash, token)
        with TestClient(app) as fresh:
            self.assertEqual(
                fresh.get("/api/auth/me", headers={"Cookie": f"{COOKIE_NAME}={token}"}).status_code,
                200,
            )
        self.assertEqual(self.client.post("/api/auth/logout", headers=ORIGIN).status_code, 204)
        self.assertEqual(self.read_me(token).status_code, 401)
        self.assertEqual(self.login().status_code, 200)
        with Session(self.connection, join_transaction_mode="create_savepoint") as db:
            db.execute(
                update(UserSession)
                .where(UserSession.user_id == self.admin_id)
                .values(
                    created_at=datetime.now(UTC) - timedelta(hours=9),
                    expires_at=datetime.now(UTC) - timedelta(seconds=1),
                )
            )
            db.commit()
        self.assertEqual(self.client.get("/api/auth/me").status_code, 401)

    def test_lockout_and_disabled_account(self) -> None:
        for _ in range(5):
            self.assertEqual(self.login(password="wrong-password").status_code, 401)
        self.assertEqual(self.login().status_code, 429)
        with Session(self.connection, join_transaction_mode="create_savepoint") as db:
            db.execute(
                update(UserAccount)
                .where(UserAccount.id == self.admin_id)
                .values(locked_until=datetime.now(UTC) - timedelta(seconds=1))
            )
            db.commit()
        self.assertEqual(self.login().status_code, 200)
        with Session(self.connection, join_transaction_mode="create_savepoint") as db:
            db.execute(
                update(UserAccount).where(UserAccount.id == self.admin_id).values(status="DISABLED")
            )
            db.commit()
        self.assertEqual(self.client.get("/api/auth/me").status_code, 401)
        self.assertEqual(self.login().status_code, 401)

    def test_unknown_accounts_cannot_bypass_ip_limit(self) -> None:
        with patch("app.modules.auth.service.verify_password", return_value=False):
            for index in range(20):
                self.assertEqual(self.login(name=f"missing_{index}").status_code, 401)
            self.assertEqual(self.login(name="another_missing").status_code, 429)

    def test_admin_crud_reset_revokes_sessions_and_preserves_history(self) -> None:
        self.assertEqual(self.login().status_code, 200)
        admin_token = self.session_cookie()
        payload = {
            "login_name": self.prefix + "_new",
            "display_name": "新账号",
            "password": self.password,
            "confirm_password": self.password,
            "platform_role": "USER",
            "status": "ACTIVE",
        }
        response = self.client.post("/api/users", headers=ORIGIN, json=payload)
        self.assertEqual(response.status_code, 201, response.text)
        account = response.json()
        self.assertNotIn("password_hash", account)
        self.assertEqual(
            self.client.post("/api/users", headers=ORIGIN, json=payload).status_code, 409
        )
        self.assertEqual(self.login(name=payload["login_name"]).status_code, 200)
        old_token = self.session_cookie()
        self.assertEqual(self.client.get("/api/users").status_code, 403)
        self.assertEqual(
            self.client.post("/api/users", headers=ORIGIN, json=payload).status_code, 403
        )
        self.assertEqual(
            self.client.delete(f"/api/users/{self.admin_id}", headers=ORIGIN).status_code, 403
        )
        self.assertEqual(
            self.client.post(
                f"/api/users/{self.admin_id}/reset-password",
                headers=ORIGIN,
                json={"password": self.password, "confirm_password": self.password},
            ).status_code,
            403,
        )
        # Login replacement revokes the prior cookie; acquire a fresh admin session.
        self.assertEqual(self.read_me(admin_token).status_code, 401)
        self.client.cookies.clear()
        self.assertEqual(self.login().status_code, 200)
        self.assertEqual(self.read_me(old_token).status_code, 200)
        new_password = secrets.token_urlsafe(18)
        response = self.client.post(
            f"/api/users/{account['id']}/reset-password",
            headers=ORIGIN,
            json={"password": new_password, "confirm_password": new_password},
        )
        self.assertEqual(response.status_code, 204)
        self.assertEqual(self.read_me(old_token).status_code, 401)
        with EncryptedClient(app) as reset_client:
            self.assertEqual(
                reset_client.post(
                    "/api/auth/login",
                    headers=ORIGIN,
                    json={"login_name": payload["login_name"], "password": self.password},
                ).status_code,
                401,
            )
            self.assertEqual(
                reset_client.post(
                    "/api/auth/login",
                    headers=ORIGIN,
                    json={"login_name": payload["login_name"], "password": new_password},
                ).status_code,
                200,
            )
            reset_token = reset_client.cookies.get(COOKIE_NAME)
        fields = {
            key: account[key]
            for key in ("login_name", "display_name", "platform_role", "status", "updated_at")
        }
        self.assertEqual(
            self.client.patch(
                f"/api/users/{account['id']}", headers=ORIGIN, json=fields
            ).status_code,
            409,
        )
        listing = self.client.get("/api/users", params={"search": payload["login_name"]}).json()
        fields["updated_at"] = listing["items"][0]["updated_at"]
        fields["display_name"] = "修改后的名称"
        self.assertEqual(
            self.client.patch(
                f"/api/users/{account['id']}", headers=ORIGIN, json=fields
            ).status_code,
            200,
        )
        self.assertEqual(
            self.client.delete(f"/api/users/{account['id']}", headers=ORIGIN).status_code, 204
        )
        self.assertEqual(self.read_me(reset_token).status_code, 401)
        with Session(self.connection, join_transaction_mode="create_savepoint") as db:
            self.assertEqual(db.get(UserAccount, account["id"]).status, "DELETED")
            self.assertGreater(
                db.scalar(
                    select(func.count())
                    .select_from(UserSession)
                    .where(UserSession.user_id == account["id"])
                ),
                0,
            )
        self.assertEqual(
            self.client.get("/api/users", params={"search": payload["login_name"]}).json()["total"],
            0,
        )
        self.assertEqual(
            self.client.post("/api/users", headers=ORIGIN, json=payload).status_code, 409
        )
        self.assertEqual(
            self.login(name=payload["login_name"], password=new_password).status_code, 401
        )

    def test_self_protection_and_role_change_revokes_access(self) -> None:
        self.assertEqual(self.login().status_code, 200)
        self.assertEqual(
            self.client.delete(f"/api/users/{self.admin_id}", headers=ORIGIN).status_code, 409
        )
        account = self.client.get("/api/users", params={"search": self.admin_name}).json()["items"][
            0
        ]
        fields = {
            key: account[key]
            for key in ("login_name", "display_name", "platform_role", "status", "updated_at")
        }
        fields["platform_role"] = "USER"
        self.assertEqual(
            self.client.patch(
                f"/api/users/{self.admin_id}", headers=ORIGIN, json=fields
            ).status_code,
            409,
        )
        fields["platform_role"] = "ADMIN"
        fields["status"] = "DISABLED"
        self.assertEqual(
            self.client.patch(
                f"/api/users/{self.admin_id}", headers=ORIGIN, json=fields
            ).status_code,
            409,
        )
        self.assertEqual(self.client.get("/api/users?page=0").status_code, 422)
        self.assertEqual(self.client.get("/api/users", params={"search": "%"}).json()["total"], 0)
        with EncryptedClient(app) as member_client:
            self.assertEqual(
                member_client.post(
                    "/api/auth/login",
                    headers=ORIGIN,
                    json={"login_name": self.member_name, "password": self.password},
                ).status_code,
                200,
            )
            account = self.client.get("/api/users", params={"search": self.member_name}).json()[
                "items"
            ][0]
            fields = {
                key: account[key]
                for key in ("login_name", "display_name", "platform_role", "status", "updated_at")
            }
            fields["platform_role"] = "ADMIN"
            self.assertEqual(
                self.client.patch(
                    f"/api/users/{self.member_id}", headers=ORIGIN, json=fields
                ).status_code,
                200,
            )
            self.assertEqual(member_client.get("/api/auth/me").status_code, 401)

    def test_database_failure_does_not_leak_or_claim_logout_success(self) -> None:
        self.assertEqual(self.login().status_code, 200)
        failure = OperationalError("SELECT sensitive", {}, Exception("secret-connection-string"))
        with patch("sqlalchemy.orm.Session.execute", side_effect=failure):
            response = self.client.post("/api/auth/logout", headers=ORIGIN)
            self.assertEqual(response.status_code, 503)
            self.assertNotIn("secret", response.text)
            self.assertNotIn("set-cookie", response.headers)
        self.assertEqual(self.client.get("/api/auth/me").status_code, 200)

    def test_new_roles_login_as_members_and_role_edits_revoke_sessions(self) -> None:
        self.assertEqual(self.login().status_code, 200)
        with Session(self.connection, join_transaction_mode="create_savepoint") as db:
            project = Project(
                name="角色检查项目",
                identifier=self.prefix + "_roles",
                owner_id=self.admin_id,
                created_by=self.admin_id,
            )
            db.add(project)
            db.flush()
            project_id = project.id
            db.commit()
        for index, role in enumerate(("TEST", "DEV", "PRODUCT", "MANAGER")):
            with self.subTest(role=role):
                payload = {
                    "login_name": self.prefix + f"_role_{index}",
                    "display_name": "角色检查",
                    "password": self.password,
                    "confirm_password": self.password,
                    "platform_role": role,
                    "status": "ACTIVE",
                }
                response = self.client.post("/api/users", headers=ORIGIN, json=payload)
                self.assertEqual(response.status_code, 201, response.text)
                account = response.json()
                self.assertEqual(account["platform_role"], role)
                with EncryptedClient(app) as member:
                    response = member.post(
                        "/api/auth/login",
                        headers=ORIGIN,
                        json={"login_name": payload["login_name"], "password": self.password},
                    )
                    self.assertEqual(response.status_code, 200, response.text)
                    self.assertEqual(response.json()["platform_role"], role)
                    self.assertEqual(member.get("/api/auth/me").json()["platform_role"], role)
                    self.assertEqual(member.get("/api/users").status_code, 403)
                    self.assertEqual(
                        member.post("/api/users", headers=ORIGIN, json=payload).status_code, 403
                    )
                    self.assertEqual(member.get("/api/analysis-acceptance").status_code, 403)
                    self.assertEqual(member.get("/api/projects").json(), [])
                    with Session(self.connection, join_transaction_mode="create_savepoint") as db:
                        db.add(ProjectMember(project_id=project_id, user_id=account["id"]))
                        db.commit()
                    projects = member.get("/api/projects").json()
                    self.assertEqual([p["id"] for p in projects], [project_id])
                    self.assertFalse(projects[0]["can_manage"])
                    self.assertEqual(
                        member.post(
                            "/api/projects",
                            headers=ORIGIN,
                            json={
                                "name": "不可为他人创建",
                                "identifier": self.prefix + f"_denied_{index}",
                                "owner_id": self.admin_id,
                            },
                        ).status_code,
                        403,
                    )
                    response = member.post(
                        "/api/projects",
                        headers=ORIGIN,
                        json={
                            "name": "本人创建",
                            "identifier": self.prefix + f"_own_{index}",
                            "owner_id": account["id"],
                        },
                    )
                    self.assertEqual(response.status_code, 201, response.text)
                    self.assertEqual(response.json()["owner_id"], account["id"])
                    self.assertTrue(response.json()["can_manage"])
                    fields = {
                        key: account[key]
                        for key in (
                            "login_name",
                            "display_name",
                            "platform_role",
                            "status",
                            "updated_at",
                        )
                    }
                    fields["platform_role"] = "OWNER"
                    self.assertEqual(
                        self.client.patch(
                            f"/api/users/{account['id']}", headers=ORIGIN, json=fields
                        ).status_code,
                        422,
                    )
                    fields["platform_role"] = "DEV" if role == "TEST" else "TEST"
                    response = self.client.patch(
                        f"/api/users/{account['id']}", headers=ORIGIN, json=fields
                    )
                    self.assertEqual(response.status_code, 200, response.text)
                    self.assertEqual(response.json()["platform_role"], fields["platform_role"])
                    self.assertEqual(member.get("/api/auth/me").status_code, 401)
                    self.assertEqual(
                        self.client.patch(
                            f"/api/users/{account['id']}", headers=ORIGIN, json=fields
                        ).status_code,
                        409,
                    )


if __name__ == "__main__":
    unittest.main()
