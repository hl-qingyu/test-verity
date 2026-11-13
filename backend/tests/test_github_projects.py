"""Rollback-only PostgreSQL checks, with explicitly mocked GitHub responses."""

import io
import os
import unittest
from unittest.mock import MagicMock, patch
from urllib.error import HTTPError, URLError

import test_auth
from pydantic import ValidationError
from sqlalchemy.orm import Session
from test_password_transport import seal

from app.core.errors import AppError as HTTPException
from app.db.models import (
    GitHubConnection,
    GitHubRepository,
    Project,
    ProjectRepository,
    SourceDocument,
    UserAccount,
)
from app.integrations.github import NoRedirect, github_get
from app.modules.github.schemas import ConnectionInput
from app.modules.github.service import token_cipher

ORIGIN = test_auth.ORIGIN
TOKEN = "github_pat_" + "test_only_not_a_real_token" * 2
CONFIG = {
    "name": "测试连接",
    "kind": "personal",
    "resource_owner": "demo-user",
    "token": TOKEN,
    "version": 0,
}


def remote(token, operation, **kwargs):
    if operation == "identity":
        return {"login": "demo-user"}
    owner = "demo-team" if token.endswith("org") else "demo-user"

    def repo(rid):
        return {
            "id": rid,
            "full_name": f"{owner}/repo-{rid}",
            "default_branch": "main",
            "private": True,
            "owner": {"login": owner, "type": "Organization" if owner == "demo-team" else "User"},
        }

    if operation == "repositories":
        return [repo(101), repo(102)]
    if operation == "repository":
        return repo(kwargs["repository_id"])
    if operation == "branch":
        return {"name": kwargs["branch"], "commit": {"sha": "a" * 40}}
    raise AssertionError("Unexpected remote operation")


class GitHubTransportTests(unittest.TestCase):
    def test_transient_read_retries_are_bounded_and_never_log_remote_values(self):
        with (
            patch("app.integrations.github.build_opener") as builder,
            patch("app.integrations.github.sleep") as wait,
            self.assertLogs("app.integrations.github", level="WARNING") as logs,
        ):
            builder.return_value.open.side_effect = [
                URLError(TOKEN),
                TimeoutError(TOKEN),
                io.BytesIO(b"{}"),
            ]
            self.assertEqual(github_get(TOKEN, "identity"), {})
            self.assertEqual(builder.return_value.open.call_count, 3)
            self.assertEqual([call.args[0] for call in wait.call_args_list], [1, 2])
        self.assertNotIn(TOKEN, "\n".join(logs.output))
        self.assertIn("operation=identity", logs.output[0])
        with (
            patch("app.integrations.github.build_opener") as builder,
            patch("app.integrations.github.sleep") as wait,
        ):
            builder.return_value.open.side_effect = URLError(TOKEN)
            with self.assertRaises(HTTPException) as caught:
                github_get(TOKEN, "identity")
            self.assertEqual(caught.exception.detail, "github_connection_failed")
            self.assertEqual(builder.return_value.open.call_count, 3)
            self.assertEqual(wait.call_count, 2)
        for status, headers in (
            (301, {}),
            (401, {}),
            (403, {}),
            (404, {}),
            (429, {}),
            (403, {"X-RateLimit-Remaining": "0"}),
            (503, {"Retry-After": "120"}),
        ):
            with (
                patch("app.integrations.github.build_opener") as builder,
                patch("app.integrations.github.sleep") as wait,
            ):
                builder.return_value.open.side_effect = HTTPError(
                    "https://api.github.com/user", status, TOKEN, headers, io.BytesIO()
                )
                with self.assertRaises(HTTPException):
                    github_get(TOKEN, "identity")
                self.assertEqual(builder.return_value.open.call_count, 1)
                wait.assert_not_called()

    def test_temporary_http_failure_retries_but_invalid_json_does_not(self):
        with (
            patch("app.integrations.github.build_opener") as builder,
            patch("app.integrations.github.sleep") as wait,
        ):
            builder.return_value.open.side_effect = [
                HTTPError("https://api.github.com/user", 503, "", {}, io.BytesIO()),
                io.BytesIO(b"{}"),
            ]
            self.assertEqual(github_get(TOKEN, "identity"), {})
            wait.assert_called_once_with(1)
            builder.return_value.open.side_effect = [io.BytesIO(b"{")]
            with self.assertRaises(HTTPException) as caught:
                github_get(TOKEN, "identity")
            self.assertEqual(caught.exception.detail, "github_invalid_response")

    def test_personal_token_formats_reject_injection_and_keep_secrets_masked(self):
        for token in [TOKEN, "ghp_" + "A" * 36, "a" * 40, ""]:
            parsed = ConnectionInput(**{**CONFIG, "token": token})
            self.assertEqual(parsed.token.get_secret_value(), token)
            if token:
                self.assertNotIn(token, repr(parsed))
        for token in [
            "ghp_short",
            "ghp_" + "A" * 36 + "\n",
            "ghp_" + "A" * 36 + " ",
            "gho_" + "A" * 36,
            "invalid",
            "g" * 40,
        ]:
            with self.assertRaises(ValidationError):
                ConnectionInput(**{**CONFIG, "token": token})

    def test_remote_get_only_fixed_host_and_no_redirect(self):
        opener = MagicMock()
        opener.open.return_value.__enter__.return_value.read.return_value = b"{}"
        with (
            patch("app.integrations.github.build_opener", return_value=opener),
            patch("app.integrations.github.sleep"),
        ):
            for operation, kwargs in [
                ("identity", {}),
                ("repositories", {"page": 2}),
                ("repository", {"repository_id": 101}),
                ("branch", {"full_name": "demo-user/repo", "branch": "feature/example"}),
            ]:
                github_get(TOKEN, operation, **kwargs)
                request = opener.open.call_args.args[0]
                self.assertEqual(request.get_method(), "GET")
                self.assertTrue(request.full_url.startswith("https://api.github.com/"))
                self.assertIsNone(request.data)
                self.assertNotIn(TOKEN, request.full_url)
            self.assertTrue(request.full_url.endswith("feature%2Fexample"))
            count = opener.open.call_count
            for operation, kwargs in [
                ("push", {}),
                ("https://evil.invalid", {}),
                ("branch", {"full_name": "../evil", "branch": "main"}),
                ("branch", {"full_name": "demo-user/..", "branch": "main"}),
                ("repositories", {"page": 0}),
                ("branch", {"full_name": "demo-user/repo", "branch": "../../users"}),
                ("branch", {"full_name": "demo-user/repo", "branch": "refs/.hidden"}),
            ]:
                with self.assertRaises(HTTPException):
                    github_get(TOKEN, operation, **kwargs)
            self.assertEqual(opener.open.call_count, count)
            for status in [301, 401, 403, 404, 409, 429, 500]:
                opener.open.side_effect = HTTPError(
                    "https://api.github.com/user", status, TOKEN, {}, io.BytesIO(TOKEN.encode())
                )
                with self.assertRaises(HTTPException) as caught:
                    github_get(TOKEN, "identity")
                self.assertNotIn(TOKEN, caught.exception.detail)
            opener.open.side_effect = TimeoutError()
            with self.assertRaises(HTTPException) as caught:
                github_get(TOKEN, "identity")
            self.assertEqual(caught.exception.status_code, 504)
        self.assertIsNone(
            NoRedirect().redirect_request(None, None, 301, "", {}, "https://evil.invalid")
        )


@unittest.skipUnless(os.environ.get("RUN_AUTH_DB_TESTS") == "1", "requires PostgreSQL opt-in")
class GitHubProjectDatabaseTests(unittest.TestCase):
    setUpClass = classmethod(test_auth.AuthDatabaseTests.setUpClass.__func__)
    setUp = test_auth.AuthDatabaseTests.setUp
    tearDown = test_auth.AuthDatabaseTests.tearDown
    login = test_auth.AuthDatabaseTests.login

    def test_member_creates_own_project_without_access_to_other_projects(self):
        payload = {
            "name": "普通用户创建",
            "identifier": self.prefix + "_member_create",
            "owner_id": self.member_id,
        }
        self.assertEqual(
            self.client.post("/api/projects", json=payload, headers=ORIGIN).status_code, 401
        )
        self.login(self.member_name)
        self.assertEqual(self.client.get("/api/projects").json(), [])
        self.assertEqual(self.client.get("/api/projects/people").status_code, 403)
        self.assertEqual(
            self.client.post(
                "/api/projects", json={**payload, "owner_id": self.admin_id}, headers=ORIGIN
            ).status_code,
            403,
        )
        response = self.client.post("/api/projects", json=payload, headers=ORIGIN)
        self.assertEqual(response.status_code, 201, response.text)
        project = response.json()
        self.assertEqual(project["owner_id"], self.member_id)
        self.assertTrue(project["can_manage"])
        self.assertEqual(
            [p["id"] for p in self.client.get("/api/projects").json()], [project["id"]]
        )
        with Session(self.connection, join_transaction_mode="create_savepoint") as db:
            self.assertEqual(db.get(Project, project["id"]).created_by, self.member_id)
        self.assertEqual(
            self.client.post("/api/projects", json=payload, headers=ORIGIN).status_code, 409
        )
        self.assertEqual(
            self.client.patch(
                f"/api/projects/{project['id']}",
                json={**payload, "name": "本人修改", "version": project["version"]},
                headers=ORIGIN,
            ).status_code,
            200,
        )
        self.assertEqual(
            self.client.patch(
                f"/api/projects/{project['id']}",
                json={**payload, "owner_id": self.admin_id, "version": 2},
                headers=ORIGIN,
            ).status_code,
            403,
        )
        self.login()
        response = self.client.post(
            "/api/projects",
            json={
                **payload,
                "identifier": self.prefix + "_admin_private",
                "owner_id": self.admin_id,
            },
            headers=ORIGIN,
        )
        self.assertEqual(response.status_code, 201, response.text)
        private = response.json()
        self.login(self.member_name)
        self.assertEqual(
            [p["id"] for p in self.client.get("/api/projects").json()], [project["id"]]
        )
        self.assertEqual(
            self.client.get(f"/api/projects/{private['id']}/repositories").status_code, 404
        )

    def encrypted(self, path, payload):
        challenge = self.client.post(
            "/api/auth/password-challenge", headers=ORIGIN, json={"path": path}
        )
        self.assertEqual(challenge.status_code, 200)
        response = self.client.post(
            path, headers=ORIGIN, json=seal(challenge.json(), path, payload)
        )
        self.assertNotIn(TOKEN, response.text)
        return response

    def save_connection(self, config=None, ids=None):
        config = config or CONFIG
        probe = self.encrypted("/api/github/connections/probe", config)
        self.assertEqual(probe.status_code, 200, probe.text)
        result = self.encrypted(
            "/api/github/connections",
            {**config, "repository_ids": ids or [101], "receipts": [probe.json()["receipt"]]},
        )
        self.assertEqual(result.status_code, 200, result.text)
        return result.json()

    def test_classic_token_personal_org_save_blank_reuse_and_isolation(self):
        classic = "ghp_" + "A" * 36

        def classic_remote(token, operation, **kwargs):
            self.assertEqual(token, classic)
            if operation == "repositories":
                return remote(TOKEN, operation, **kwargs) + [
                    {**r, "id": r["id"] + 100} for r in remote(TOKEN + "org", operation, **kwargs)
                ]
            if operation == "repository" and kwargs["repository_id"] >= 200:
                return remote(TOKEN + "org", operation, **kwargs)
            return remote(TOKEN, operation, **kwargs)

        self.login()
        with patch("app.integrations.github.github_get", side_effect=classic_remote):
            personal = self.save_connection({**CONFIG, "token": classic})
            org = self.save_connection(
                {**CONFIG, "token": classic, "kind": "organization", "resource_owner": "demo-team"},
                [201],
            )
            self.assertEqual(org["repositories"][0]["github_id"], 201)
            self.assertEqual(org["resource_owner"], "demo-team")
            updated = self.save_connection(
                {**CONFIG, "token": "", "connection_id": personal["id"], "version": 1}
            )
            self.assertEqual(updated["version"], 2)
            response = self.client.get("/api/github/connections")
            self.assertNotIn(classic, response.text)
            self.assertEqual(len(response.json()), 2)
            with Session(self.connection, join_transaction_mode="create_savepoint") as db:
                encrypted = db.get(GitHubConnection, org["id"]).encrypted_token
                self.assertNotIn(classic, encrypted)
                self.assertEqual(token_cipher().decrypt(encrypted.encode()).decode(), classic)
            automatic = self.save_connection(
                {"name": "自动发现", "token": classic, "token_type": "classic"}, [101, 201]
            )
            self.assertEqual(automatic["kind"], "automatic")
            self.assertEqual(automatic["token_type"], "classic")
            self.assertEqual(
                {r["owner_type"] for r in automatic["repositories"]}, {"User", "Organization"}
            )
            self.assertEqual(
                self.encrypted(
                    "/api/github/connections/probe",
                    {"name": "不匹配", "token": classic, "token_type": "fine_grained"},
                ).status_code,
                422,
            )
            project = self.client.post(
                "/api/projects",
                json={
                    "name": "混合来源",
                    "identifier": self.prefix + "_mixed",
                    "owner_id": self.admin_id,
                },
                headers=ORIGIN,
            ).json()
            for rid in [101, 201]:
                response = self.client.post(
                    f"/api/projects/{project['id']}/repositories",
                    json={
                        "connection_id": automatic["id"],
                        "github_id": rid,
                        "kind": "BACKEND",
                        "default_branch": "main",
                    },
                    headers=ORIGIN,
                )
                self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual(
                len(self.client.get(f"/api/projects/{project['id']}/repositories").json()), 2
            )
            self.login(self.member_name)
            self.assertEqual(self.client.get("/api/github/connections").json(), [])
            self.assertEqual(
                self.encrypted(
                    "/api/github/connections/probe",
                    {**CONFIG, "token": "", "connection_id": org["id"], "version": 1},
                ).status_code,
                404,
            )

    @patch("app.integrations.github.github_get", side_effect=remote)
    def test_connection_owner_isolation_allowlist_and_versions(self, upstream):
        self.assertEqual(self.client.get("/api/github/connections").status_code, 401)
        self.login()
        saved = self.save_connection()
        self.assertEqual(saved["repositories"][0]["github_id"], 101)
        self.assertNotIn("encrypted_token", saved)
        with Session(self.connection, join_transaction_mode="create_savepoint") as db:
            row = db.get(GitHubConnection, saved["id"])
            self.assertNotIn(TOKEN, row.encrypted_token)
            self.assertEqual(token_cipher().decrypt(row.encrypted_token.encode()).decode(), TOKEN)
        self.login(self.member_name)
        self.assertEqual(self.client.get("/api/github/connections").json(), [])
        self.assertEqual(
            self.encrypted(
                "/api/github/connections/probe",
                {**CONFIG, "connection_id": saved["id"], "version": 1, "token": ""},
            ).status_code,
            404,
        )
        self.login()
        edit = {**CONFIG, "connection_id": saved["id"], "version": 1, "token": ""}
        probe = self.encrypted("/api/github/connections/probe", edit).json()
        count = upstream.call_count
        denied = self.encrypted(
            "/api/github/connections",
            {**edit, "repository_ids": [999], "receipts": [probe["receipt"]]},
        )
        self.assertEqual(denied.status_code, 403)
        self.assertEqual(upstream.call_count, count)
        response = self.encrypted(
            "/api/github/connections",
            {**edit, "repository_ids": [102], "receipts": [probe["receipt"]]},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["version"], 2)
        self.assertEqual([r["github_id"] for r in response.json()["repositories"]], [102])
        self.assertEqual(self.encrypted("/api/github/connections/probe", edit).status_code, 409)
        self.assertEqual(
            self.encrypted(
                "/api/github/connections/probe", {**edit, "version": 2, "resource_owner": "other"}
            ).status_code,
            422,
        )
        org = self.save_connection(
            {
                **CONFIG,
                "kind": "organization",
                "resource_owner": "demo-team",
                "token": TOKEN + "org",
            }
        )
        self.assertEqual(org["resource_owner"], "demo-team")
        automatic = self.save_connection(
            {"name": "自动细粒度", "token": TOKEN + "org", "token_type": "fine_grained"}
        )
        self.assertEqual(automatic["token_type"], "fine_grained")
        self.assertEqual(automatic["repositories"][0]["owner_type"], "Organization")
        self.assertEqual(
            self.encrypted(
                "/api/github/connections/probe",
                {
                    "name": "模式不匹配",
                    "connection_id": automatic["id"],
                    "version": 1,
                    "token_type": "classic",
                },
            ).status_code,
            422,
        )

    @patch("app.integrations.github.github_get", side_effect=remote)
    def test_receipt_expiry_identity_and_failed_save(self, upstream):
        self.login()
        probe = self.encrypted("/api/github/connections/probe", CONFIG).json()
        receipt = probe["receipt"]
        old = (
            token_cipher()
            .encrypt_at_time(token_cipher().decrypt(receipt.encode()), current_time=1)
            .decode()
        )
        for proof in [old, receipt[:-4] + "xxxx"]:
            self.assertEqual(
                self.encrypted(
                    "/api/github/connections",
                    {**CONFIG, "repository_ids": [101], "receipts": [proof]},
                ).status_code,
                409,
            )
        self.assertEqual(
            self.encrypted(
                "/api/github/connections/probe", {**CONFIG, "resource_owner": "other"}
            ).status_code,
            422,
        )
        self.assertEqual(
            self.encrypted(
                "/api/github/connections/probe", {**CONFIG, "token": "ghp_not_allowed"}
            ).status_code,
            422,
        )
        with patch(
            "app.integrations.github.check_repository",
            side_effect=HTTPException(502, "github_access_denied"),
        ):
            failed = self.encrypted(
                "/api/github/connections",
                {**CONFIG, "repository_ids": [101], "receipts": [receipt]},
            )
            self.assertEqual(failed.status_code, 502)
        self.assertEqual(self.client.get("/api/github/connections").json(), [])
        self.login(self.member_name)
        self.assertEqual(
            self.encrypted(
                "/api/github/connections",
                {**CONFIG, "repository_ids": [101], "receipts": [receipt]},
            ).status_code,
            409,
        )
        self.assertEqual(
            self.client.post(
                "/api/github/connections/probe", headers=ORIGIN, json=CONFIG
            ).status_code,
            422,
        )

    @patch("app.integrations.github.github_get", side_effect=remote)
    def test_project_membership_and_repository_boundaries(self, upstream):
        self.login()
        admin_connection = self.save_connection()
        payload = {"name": "项目一", "identifier": self.prefix + "_one", "owner_id": self.member_id}
        response = self.client.post("/api/projects", json=payload, headers=ORIGIN)
        self.assertEqual(response.status_code, 201)
        first = response.json()
        second = self.client.post(
            "/api/projects",
            json={**payload, "identifier": self.prefix + "_two", "owner_id": self.admin_id},
            headers=ORIGIN,
        ).json()
        with Session(self.connection, join_transaction_mode="create_savepoint") as db:
            outsider = UserAccount(
                login_name=self.prefix + "_third",
                display_name="第三账号",
                password_hash=self.encoded,
                platform_role="USER",
            )
            db.add(outsider)
            db.flush()
            outsider_id = outsider.id
            outsider_name = outsider.login_name
            db.commit()
        self.login(self.member_name)
        self.assertEqual(
            self.client.post("/api/projects", json=payload, headers=ORIGIN).status_code, 409
        )
        self.assertEqual([p["id"] for p in self.client.get("/api/projects").json()], [first["id"]])
        self.assertEqual(
            self.client.get(f"/api/projects/{second['id']}/repositories").status_code, 404
        )
        binding = {
            "connection_id": admin_connection["id"],
            "github_id": 101,
            "kind": "PROTOTYPE",
            "default_branch": "main",
            "version": 0,
        }
        path = f"/api/projects/{first['id']}/repositories"
        self.assertEqual(self.client.post(path, json=binding, headers=ORIGIN).status_code, 404)
        own = self.save_connection()
        binding["connection_id"] = own["id"]
        result = self.client.post(path, json=binding, headers=ORIGIN)
        self.assertEqual(result.status_code, 200, result.text)
        self.assertEqual(self.client.post(path, json=binding, headers=ORIGIN).status_code, 409)
        self.assertEqual(
            self.client.post(
                f"/api/projects/{first['id']}/members",
                json={"user_id": outsider_id, "version": first["version"]},
                headers=ORIGIN,
            ).status_code,
            200,
        )
        self.login(outsider_name)
        repos = self.client.get(path).json()
        self.assertEqual(len(repos), 1)
        self.assertEqual(repos[0]["kind"], "PROTOTYPE")
        self.assertFalse(repos[0]["has_personal_authorization"])
        self.assertNotIn("connection_id", repos[0])
        self.assertEqual(self.client.post(path, json=binding, headers=ORIGIN).status_code, 403)
        self.login(self.member_name)
        version = self.client.get(f"/api/projects/{first['id']}/members").json()["version"]
        self.assertEqual(
            self.client.delete(
                f"/api/projects/{first['id']}/members/{outsider_id}?version={version}",
                headers=ORIGIN,
            ).status_code,
            200,
        )
        self.login(outsider_name)
        self.assertEqual(self.client.get(path).status_code, 404)

    @patch("app.integrations.github.github_get", side_effect=remote)
    def test_confirmed_deletion_permissions_versions_references_and_no_remote_write(self, upstream):
        self.login()
        connection = self.save_connection()
        project = self.client.post(
            "/api/projects",
            headers=ORIGIN,
            json={
                "name": "删除检查",
                "identifier": self.prefix + "_delete",
                "owner_id": self.admin_id,
            },
        ).json()
        base = f"/api/projects/{project['id']}/repositories"
        row = self.client.post(
            base,
            headers=ORIGIN,
            json={
                "connection_id": connection["id"],
                "github_id": 101,
                "kind": "BACKEND",
                "default_branch": "main",
            },
        ).json()
        target = f"{base}/{row['id']}"
        connection_target = f"/api/github/connections/{connection['id']}"

        def remove(path, version=1, confirmed=True):
            return self.client.request(
                "DELETE", path, headers=ORIGIN, json={"version": version, "confirmed": confirmed}
            )

        for path in [target, connection_target]:
            self.assertEqual(remove(path, confirmed=False).status_code, 422)
            self.assertEqual(remove(path, version=2).status_code, 409)
        self.client.post(
            f"/api/projects/{project['id']}/members",
            headers=ORIGIN,
            json={"user_id": self.member_id, "version": 1},
        )
        self.login(self.member_name)
        self.assertEqual(remove(target).status_code, 403)
        self.assertEqual(remove(connection_target).status_code, 404)
        self.login()
        with Session(self.connection, join_transaction_mode="create_savepoint") as db:
            source = SourceDocument(
                project_id=project["id"],
                repository_id=row["id"],
                purpose="PROTOTYPE",
                kind="GITHUB",
                current_version=1,
            )
            db.add(source)
            db.commit()
            source_id = source.id
        calls = upstream.call_count
        self.assertEqual(remove(target).status_code, 409)
        self.assertEqual(remove(connection_target).status_code, 200)
        self.assertEqual(upstream.call_count, calls)
        self.assertEqual(len(self.client.get(base).json()), 1)
        self.assertFalse(self.client.get(base).json()[0]["has_personal_authorization"])
        with Session(self.connection, join_transaction_mode="create_savepoint") as db:
            self.assertIsNone(db.get(GitHubConnection, connection["id"]))
            self.assertIsNone(db.get(GitHubRepository, (connection["id"], 101)))
            self.assertIsNotNone(db.get(ProjectRepository, row["id"]))
            self.assertIsNotNone(db.get(SourceDocument, source_id))
            # Test-only fixture cleanup; production deletion never removes source records.
            db.delete(db.get(SourceDocument, source_id))
            db.commit()
        self.assertEqual(remove(target).status_code, 200)
        self.assertEqual(self.client.get(base).json(), [])
        self.assertEqual(remove(target).status_code, 404)
        self.assertEqual(upstream.call_count, calls)
