"""Real PostgreSQL rollback checks; only synthetic directory files are uploaded."""

import hashlib
import io
import json
import os
import tarfile
import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import test_auth
import test_prototypes
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.db.models import LocalCodeSource, SourceDocument, UserAccount
from app.modules.case_generation import sources as generation
from app.modules.case_generation.schemas import Prepare
from app.modules.change_analysis import contract
from app.modules.change_analysis import sources as changes
from app.modules.code_analysis import sources as code
from app.modules.prototypes import directories
from app.modules.requirements import risk_analysis_execution as risk
from app.modules.requirements.analysis_materials import model_content


def archive(entries, metadata, members=None):
    stream = io.BytesIO()
    with tarfile.open(fileobj=stream, mode="w") as tar:

        def add(name, body):
            entry = tarfile.TarInfo(name)
            entry.size = len(body)
            tar.addfile(entry, io.BytesIO(body))

        add(
            "manifest.json",
            json.dumps(
                {"metadata": metadata, "files": [{"path": p, "size": len(b)} for p, b in entries]},
                ensure_ascii=False,
            ).encode(),
        )
        for i, (_, body) in enumerate(entries):
            add(members[i] if members else f"f{i}", body)
    return stream.getvalue()


class DirectoryRequestTests(unittest.TestCase):
    def test_attachment_mapping_does_not_split_existing_source_identifiers(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "image.png"
            path.write_bytes(test_prototypes.PNG)
            source = "old#f2"
            context = {
                "materials": [
                    {"source_id": source, "segments": [{"segment_id": "s1", "image_ref": source}]}
                ]
            }
            text = model_content(context, [(path, "png", source, "image.png")])[1]["text"]
            self.assertIn("source_id=old#f2，segment_id=s1", text)

    def test_empty_new_fields_preserve_legacy_preparation_identity(self):
        payload = Prepare(
            request_id=uuid4(),
            title="兼容请求",
            mode="INITIAL",
            scope="全部",
            materials=[{"document_id": 1, "version": "1"}],
            case_ids=[],
            case_versions={},
            case_scope="不对照",
        )
        legacy = payload.model_dump(mode="json")
        legacy["materials"][0].pop("before_paths")
        self.assertEqual(generation.preparation_request(payload), legacy)
        payload.materials[0].before_paths = ["old.html"]
        self.assertEqual(
            generation.preparation_request(payload)["materials"][0]["before_paths"], ["old.html"]
        )


@unittest.skipUnless(os.environ.get("RUN_AUTH_DB_TESTS") == "1", "requires PostgreSQL test opt-in")
class DirectoryDatabaseTests(unittest.TestCase):
    setUpClass = classmethod(test_auth.AuthDatabaseTests.setUpClass.__func__)
    setUp = test_prototypes.PrototypeDatabaseTests.setUp
    tearDown = test_prototypes.PrototypeDatabaseTests.tearDown
    login = test_auth.AuthDatabaseTests.login
    rev = test_prototypes.PrototypeDatabaseTests.revision

    def upload(self, entries, source=None, request=None, name="目录原型", members=None):
        metadata = {
            "name": name,
            "description": "测试说明",
            "group_id": None,
            "source_id": source,
            "directory_name": "原型",
        }
        params = {
            "filename": "原型",
            "name": name,
            "description": "测试说明",
            "revision": self.rev(),
            "upload_id": request or str(uuid4()),
        }
        return self.client.post(
            self.base + "/directories" + (f"/{source}/versions" if source else ""),
            params=params,
            content=archive(entries, metadata, members),
            headers={**test_auth.ORIGIN, "Content-Type": "application/x-tar"},
        )

    def test_directory_versions_are_atomic_fixed_and_project_authorized(self):
        request = str(uuid4())
        entries = [
            ("页面/订单.html", b"<h1>old</h1>"),
            ("assets/notes.js", b"window.notes='fixed';"),
            ("assets/a.png", test_prototypes.PNG),
        ]
        first = self.upload(entries, request=request)
        self.assertEqual(first.status_code, 201, first.text)
        source = first.json()["sources"][0]
        sid = source["id"]
        vid = source["current"]["id"]
        self.assertEqual(source["kind"], "DIRECTORY")
        base = self.base + f"/directories/{sid}/versions/{vid}"
        listing = self.client.get(base + "/files").json()
        self.assertEqual([f["path"] for f in listing["files"]], [p for p, _ in entries])
        self.assertNotIn("storage_key", str(listing))
        package = self.client.get(base + "/archive")
        self.assertEqual(
            package.status_code, 200, package.text if package.status_code != 200 else ""
        )
        with tarfile.open(fileobj=io.BytesIO(package.content), mode="r:") as downloaded:
            self.assertEqual(downloaded.getnames(), [p for p, _ in entries])
            self.assertEqual(downloaded.extractfile("页面/订单.html").read(), b"<h1>old</h1>")
        browser = self.client.get(base + "/browser", params={"path": "页面/订单.html"})
        self.assertEqual(browser.status_code, 200)
        self.assertIn("sandbox allow-scripts", browser.headers["Content-Security-Policy"])
        self.assertIn(
            "script-src 'unsafe-inline' data:", browser.headers["Content-Security-Policy"]
        )
        self.assertNotIn("allow-same-origin", browser.headers["Content-Security-Policy"])
        self.assertEqual(self.upload(entries, request=request).status_code, 201)
        self.assertEqual(len(self.client.get(self.docs + f"/{sid}/versions").json()), 1)
        self.assertEqual(self.upload(entries, request=request, name="changed").status_code, 409)
        self.assertEqual(self.upload([("../escape.html", b"bad")], source=sid).status_code, 422)
        self.assertEqual(
            self.upload([("a.html", b"a"), ("a.html/b.html", b"b")], source=sid).status_code, 422
        )
        self.assertEqual(
            self.upload(entries, source=sid, members=["../f0", "f1", "f2"]).status_code, 422
        )
        self.assertEqual(len(self.client.get(self.docs + f"/{sid}/versions").json()), 1)
        updated = self.upload(
            [("页面/订单.html", b"<h1>new</h1>"), ("new.html", b"new")], source=sid
        )
        self.assertEqual(updated.status_code, 201, updated.text)
        self.assertEqual(
            self.client.get(base + "/file", params={"path": "页面/订单.html"}).content,
            b"<h1>old</h1>",
        )
        self.assertEqual(
            self.client.get(base + "/file", params={"path": "../escape.html"}).status_code, 422
        )
        with Session(self.connection, join_transaction_mode="create_savepoint") as db:
            actor = db.get(UserAccount, self.admin_id)
            actual, attached = directories.material(
                self.project_id, sid, vid, ["页面/订单.html", "assets/a.png"], "M1", actor, db
            )
            self.assertIn("old", actual["segments"][0]["text"])
            self.assertFalse(any("window.notes" in s["text"] for s in actual["segments"]))
            self.assertEqual(attached[0][2], "M1#f2")
            self.assertIn(
                "image_ref=M1#f2",
                model_content({}, attached, attachment_key="image_ref")[1]["text"],
            )
            self.assertIn(
                "source_id=M1，segment_id=f2",
                model_content({"materials": [actual]}, attached)[1]["text"],
            )
            self.assertEqual(
                directories.bind_material(
                    self.project_id, sid, vid, actual["segments"], "M1", actor, db
                )[1],
                ["页面/订单.html", "assets/a.png"],
            )
            broken = [{**actual["segments"][0], "text": "tampered"}, actual["segments"][1]]
            with self.assertRaises(AppError):
                directories.bind_material(self.project_id, sid, vid, broken, "M1", actor, db)
            gen, binding = generation.read_material(
                self.project_id,
                SimpleNamespace(
                    document_id=sid, version=str(vid), before="", paths=["页面/订单.html"]
                ),
                "CURRENT",
                "M1",
                actor,
                db,
            )
            self.assertEqual(gen["segments"][0]["text"], "<h1>old</h1>")
            generation.recheck(self.project_id, {"bindings": [binding]}, actor, db)
            material_selection = {
                "document_id": sid,
                "version_id": vid,
                "paths": ["assets/notes.js"],
                "snapshot": "",
                "url": "",
                "commit": "",
            }
            self.assertEqual(
                code.material_authorization(self.project_id, material_selection, actor, db).id, sid
            )
            local = LocalCodeSource(
                project_id=self.project_id,
                owner_id=actor.id,
                client_id=str(uuid4()),
                name="合成本地代码",
                directory_name="code",
                kind="BACKEND",
                version=1,
            )
            db.add(local)
            db.commit()
            code_input, _, _ = code.prepare(
                self.project_id,
                str(uuid4()),
                {
                    "targets": ["BUG"],
                    "focus": "",
                    "sources": [
                        {
                            "kind": "LOCAL",
                            "source_id": local.id,
                            "source_version": 1,
                            "commit": "",
                            "files": [
                                {
                                    "path": "main.py",
                                    "content": "print(1)",
                                    "sha256": hashlib.sha256(b"print(1)").hexdigest(),
                                }
                            ],
                        }
                    ],
                    "materials": [material_selection],
                },
                actor,
                db,
            )
            self.assertEqual(
                code_input["materials"][0]["segments"][0]["text"], "window.notes='fixed';"
            )
            task = SimpleNamespace(
                project_id=self.project_id,
                request_id=str(uuid4()),
                id=1,
                focus="",
                selections=[
                    {
                        "document_id": sid,
                        "version_id": vid,
                        "paths": ["页面/订单.html"],
                        "snapshot": "",
                        "url": None,
                    }
                ],
            )
            fixed, bindings, _ = risk.prepare(task, actor, db)
            self.assertEqual(fixed["materials"][0]["segments"][0]["text"], "<h1>old</h1>")
            self.assertEqual(bindings[0]["version"]["id"], vid)
        foreign = self.base.replace(str(self.project_id), str(self.project_id + 1000000), 1)
        self.assertEqual(
            self.client.get(base.replace(self.base, foreign) + "/files").status_code, 404
        )
        self.assertEqual(self.login(self.prefix + "_member").status_code, 200)
        self.assertEqual(self.client.get(base + "/files").status_code, 200)

    def test_invalid_or_incomplete_upload_does_not_publish_a_version(self):
        original = self.upload([("a.html", b"fixed")]).json()["sources"][0]
        revision = self.rev()
        metadata = {
            "name": "目录原型",
            "description": "测试说明",
            "group_id": None,
            "source_id": original["id"],
            "directory_name": "原型",
        }
        body = archive([("a.html", b"new" * 1000)], metadata)
        params = {
            "filename": "原型",
            "name": "目录原型",
            "description": "测试说明",
            "revision": revision,
            "upload_id": str(uuid4()),
        }
        response = self.client.post(
            self.base + f"/directories/{original['id']}/versions",
            params=params,
            content=body[:1400],
            headers=test_auth.ORIGIN,
        )
        self.assertEqual(response.status_code, 422, response.text)
        self.assertEqual(self.rev(), revision)
        response = self.upload(
            [("key.txt", b"-----BEGIN PRIVATE KEY-----\nsynthetic")], source=original["id"]
        )
        self.assertEqual(response.status_code, 422)
        self.assertEqual(self.rev(), revision)
        self.assertEqual(len(self.client.get(self.docs + f"/{original['id']}/versions").json()), 1)

    def test_browser_preview_uses_assets_from_the_requested_version_only(self):
        html = (
            b'<link rel="stylesheet" href="../assets/a.css">'
            b'<script src="../assets/a.js?v=1"></script>'
        )
        first = self.upload(
            [
                ("site/pages/a.html", html),
                ("site/assets/a.css", b"body{color:green}"),
                ("site/assets/a.js", b"window.version=1;"),
            ]
        )
        self.assertEqual(first.status_code, 201, first.text)
        source = first.json()["sources"][0]
        base = self.base + f"/directories/{source['id']}/versions/{source['current']['id']}"
        updated = self.upload(
            [
                ("site/pages/a.html", html),
                ("site/assets/a.css", b"body{color:red}"),
                ("site/assets/a.js", b"window.version=2;"),
            ],
            source=source["id"],
        )
        self.assertEqual(updated.status_code, 201, updated.text)
        response = self.client.get(base + "/browser", params={"path": "site/pages/a.html"})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertIn("Ym9keXtjb2xvcjpncmVlbn0=", response.text)
        self.assertIn("d2luZG93LnZlcnNpb249MTs=", response.text)
        self.assertEqual(
            self.client.get(base + "/file", params={"path": "site/pages/a.html"}).content, html
        )

    def test_directory_change_distinguishes_absence_and_keeps_old_input(self):
        first = self.upload([("old.html", b"old"), ("same.html", b"same")]).json()["sources"][0]
        sid, old = first["id"], first["current"]["id"]
        second = self.upload([("new.html", b"new"), ("same.html", b"changed")], source=sid).json()[
            "sources"
        ][0]
        new = second["current"]["id"]
        pair = {
            "source_id": sid,
            "before_version_id": old,
            "after_version_id": new,
            "paths": ["old.html", "same.html", "new.html"],
        }
        with Session(self.connection, join_transaction_mode="create_savepoint") as db:
            actor = db.get(UserAccount, self.admin_id)
            a, _, _ = changes.directory_snapshot(self.project_id, pair, "before", "old", actor, db)
            b, _, _ = changes.directory_snapshot(self.project_id, pair, "after", "new", actor, db)
            self.assertEqual(a["units"][2]["presence"], "VERIFIED_ABSENT")
            self.assertEqual(b["units"][0]["presence"], "VERIFIED_ABSENT")
            selection = SimpleNamespace(
                document_id=sid,
                version=str(new),
                before=str(old),
                paths=["new.html"],
                before_paths=["old.html"],
            )
            before_material, before_binding = generation.read_material(
                self.project_id, selection, "BEFORE", "before", actor, db
            )
            after_material, _ = generation.read_material(
                self.project_id, selection, "CURRENT", "after", actor, db
            )
            self.assertEqual(before_material["segments"][0]["text"], "old")
            self.assertEqual(after_material["segments"][0]["text"], "new")
            self.assertEqual(before_binding["paths"], ["old.html"])
            result = {
                "contract_version": 2,
                "analysis_type": "CHANGE_IMPACT",
                "request_id": str(uuid4()),
                "project_id": self.project_id,
                "revision": 1,
                "mode": "PROTOTYPE_CHANGE",
                "targets": ["BUSINESS_IMPACT"],
                "focus": "",
                "snapshots": [a, b],
                "comparison_pairs": [changes.comparison("pair", a, b, "FULL_REPLACEMENT")],
                "context_refs": [],
                "cases": [],
                "historical_items": [],
                "input_limitations": [],
            }
            contract.validate_input(contract.AnalysisInput.model_validate(result))
            prepared, _, _ = changes.prepare(
                self.project_id,
                str(uuid4()),
                {
                    "mode": "PROTOTYPE_CHANGE",
                    "targets": ["BUSINESS_IMPACT"],
                    "focus": "",
                    "confirmed": True,
                    "pairs": [
                        {**pair, "kind": "DIRECTORY_PROTOTYPE", "update_mode": "FULL_REPLACEMENT"}
                    ],
                    "materials": [
                        {
                            "document_id": sid,
                            "version_id": old,
                            "paths": ["old.html"],
                            "snapshot": "",
                            "url": "",
                            "commit": "",
                        }
                    ],
                    "sources": [],
                    "case_ids": [],
                    "case_versions": {},
                    "historical_items": [],
                },
                actor,
                db,
            )
            self.assertEqual(len(prepared["context_refs"]), 1)
            self.assertEqual(prepared["snapshots"][-1]["provenance"]["source_kind"], "UPLOAD")
            row = db.scalar(select(SourceDocument).where(SourceDocument.id == sid))
            row.deleted_at = datetime.now(UTC)
            db.commit()
        self.assertEqual(len(self.client.get(self.base).json()["sources"]), 0)
        self.assertEqual(
            self.client.get(
                self.base + f"/directories/{sid}/versions/{old}/file", params={"path": "old.html"}
            ).content,
            b"old",
        )
