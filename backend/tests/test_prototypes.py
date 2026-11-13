import base64
import io
import json
import os
import tempfile
import unittest
from unittest.mock import patch
from uuid import uuid4

import test_auth
from pydantic import ValidationError
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.db.models import (
    GitHubConnection,
    GitHubRepository,
    Project,
    ProjectMember,
    ProjectRepository,
    SourceDocument,
)
from app.integrations import github, prototype_link
from app.modules.github.service import token_cipher
from app.modules.prototypes.schemas import GitScope, LiveInput
from app.modules.requirements.risk_schemas import AnalysisSelection

SHA = "a" * 40
TREE = "b" * 40
FILE = {
    "path": "prototype/index.html",
    "sha": "c" * 40,
    "size": 100,
    "type": "blob",
    "mode": "100644",
}
PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/l9sAAAAASUVORK5CYII="
)


class PrototypeValidationTests(unittest.TestCase):
    def test_git_version_lists_keep_fixed_shas_and_validate_metadata(self):
        repo = {
            "id": 5,
            "full_name": "team/web",
            "private": True,
            "default_branch": "main",
            "owner": {"login": "team", "type": "Organization"},
        }
        for kind in ("branches", "tags", "commits"):
            row = (
                {
                    "sha": SHA,
                    "commit": {
                        "message": "修正核销\n完整内容不回传",
                        "author": {"date": "2026-10-08T00:00:00Z"},
                    },
                }
                if kind == "commits"
                else {"name": "main" if kind == "branches" else "v1.2", "commit": {"sha": SHA}}
            )
            with patch.object(github, "github_get", side_effect=[repo, [row] * 50]) as get:
                result = github.repository_versions(
                    "synthetic", 5, kind, "main" if kind == "commits" else "", 2
                )
            self.assertTrue(result["has_more"])
            self.assertEqual(result["items"][0]["sha"], SHA)
            self.assertEqual(get.call_args_list[-1].kwargs["page"], 2)
            if kind == "commits":
                self.assertEqual(result["items"][0]["message"], "修正核销")
        for kind, ref, page in [
            ("push", "", 1),
            ("tags", "main", 1),
            ("commits", "main?token=x", 1),
            ("branches", "", 0),
        ]:
            with self.assertRaises(AppError), patch.object(github, "github_get") as get:
                github.repository_versions("synthetic", 5, kind, ref, page)
            get.assert_not_called()
        with patch.object(
            github, "github_get", side_effect=[repo, [{"name": "main", "commit": {"sha": "fake"}}]]
        ):
            with self.assertRaises(AppError) as error:
                github.repository_versions("synthetic", 5, "branches", "", 1)
            self.assertEqual(error.exception.detail, "github_invalid_response")

    def test_static_link_page_selection_is_fixed_and_restricted(self):
        url = "https://prototype.geekuat.com/p/Test123/"
        tree = [
            {"id": 1, "parentId": None, "type": "folder", "name": "门店"},
            {"id": 2, "parentId": 1, "type": "page", "name": "订单", "file": "page-2.html"},
            {"id": 3, "parentId": 1, "type": "page", "name": "钱包", "file": "page-3.html"},
        ]
        js = (
            "window.XETA_PAGE_TREE = "
            + json.dumps(tree, ensure_ascii=False)
            + "; window.XETA_ANNOTATIONS = "
            + json.dumps({"page-2.html": {"原型说明": ["订单规则"]}}, ensure_ascii=False)
            + ";"
        ).encode()
        content = {
            url: b'<script src="assets/annotations.js?v=1"></script>',
            url + "assets/annotations.js?v=1": js,
            url + "pages/page-2.html": b"<h1>Order</h1>",
        }
        with patch.object(prototype_link, "fetch", side_effect=content.__getitem__) as get:
            catalog = prototype_link.catalog(url)
            self.assertEqual([p["path"] for p in catalog["pages"]], ["门店 / 订单", "门店 / 钱包"])
            result = prototype_link.read_pages(url, ["page-2.html"], catalog["snapshot"])
            self.assertEqual(
                [s["text"] for s in result["segments"]], ["<h1>Order</h1>", "订单规则"]
            )
            self.assertFalse(any("page-3.html" in call.args[0] for call in get.call_args_list))
            with self.assertRaises(AppError):
                prototype_link.read_pages(url, ["page-3.html"], "0" * 64)
        for bad in (
            "http://prototype.geekuat.com/p/Test123/",
            "https://127.0.0.1/p/Test123/",
            "https://prototype.geekuat.com/p/Test123/../../admin",
            url + "?next=localhost",
        ):
            with self.assertRaises(AppError):
                prototype_link.catalog(bad)

    def test_generic_link_catalog_preserves_groups_and_all_note_formats(self):
        url = "https://prototype.geekuat.com/p/Test123/"
        pages = [
            {"id": "order", "title": "订单详情", "module": "订单", "file": "order-detail.html"},
            {"id": "wallet", "title": "钱包首页", "module": "钱包", "file": "wallet.html"},
        ]
        notes = {
            "*": [{"title": "公共说明", "items": ["全局规则"]}],
            "order-detail.html": [
                {"title": "说明", "items": ["订单规则"]},
                {"title": "说明", "markdown": "## 状态\n保留完整正文"},
            ],
        }
        js = (
            "window.PROTOTYPE_PAGES="
            + json.dumps(pages, ensure_ascii=False)
            + "; window.PROTOTYPE_ANNOTATIONS =\n"
            + json.dumps(notes, ensure_ascii=False)
            + ";"
        ).encode()
        content = {
            url: b'<script src="assets/annotations.js?v=1"></script>',
            url + "assets/annotations.js?v=1": js,
            url + "pages/order-detail.html": b"<h1>Order</h1>",
        }
        with patch.object(prototype_link, "fetch", side_effect=content.__getitem__) as get:
            catalog = prototype_link.catalog(url)
            self.assertEqual(
                [p["path"] for p in catalog["pages"]], ["订单 / 订单详情", "钱包 / 钱包首页"]
            )
            selection = AnalysisSelection(
                document_id=1,
                version_id=None,
                paths=["order-detail.html"],
                snapshot=catalog["snapshot"],
                url=url,
            )
            result = prototype_link.read_pages(url, selection.paths, selection.snapshot)
            self.assertEqual(
                [s["text"] for s in result["segments"]],
                ["<h1>Order</h1>", "全局规则", "订单规则\n## 状态\n保留完整正文"],
            )
            self.assertFalse(any("wallet.html" in call.args[0] for call in get.call_args_list))
            for files, snapshot in [
                (["order-detail.html"], "0" * 64),
                (["unlisted.html"], catalog["snapshot"]),
                (["order-detail.html"] * 2, catalog["snapshot"]),
            ]:
                with self.assertRaises(AppError):
                    prototype_link.read_pages(url, files, snapshot)

    def test_annotation_markdown_files_are_complete_fixed_deduplicated_and_transitive(self):
        url = "https://prototype.geekuat.com/p/Test123/"
        pages = [
            {"title": "订单", "file": "order.html"},
            {"title": "钱包", "file": "wallet.html"},
        ]
        notes = {
            "*": [{"title": "公共规则", "markdown": "[规则](docs/规则.md#流程)"}],
            "order.html": [
                {"title": "说明", "items": ['<a href="docs/%E8%A7%84%E5%88%99.md">完整规则</a>']}
            ],
            "wallet.html": [{"title": "未选", "markdown": "[不读取](private.md)"}],
        }
        raw = "# 完整规则\r\n\r\n[条件](../shared/conditions.md?v=1#条件)\r\n".encode()
        content = {
            url: b'<script src="assets/annotations.js"></script>',
            url + "assets/annotations.js": (
                "window.PROTOTYPE_PAGES="
                + json.dumps(pages)
                + ";window.PROTOTYPE_ANNOTATIONS="
                + json.dumps(notes)
                + ";"
            ).encode(),
            url + "pages/order.html": b"<h1>Order</h1>",
            url + "docs/%E8%A7%84%E5%88%99.md": raw,
            url + "shared/conditions.md?v=1": "条件全文\n[循环](../docs/规则.md)".encode(),
        }
        with patch.object(prototype_link, "fetch", side_effect=content.__getitem__) as get:
            catalog = prototype_link.catalog(url)
            result = prototype_link.read_pages(url, ["order.html"], catalog["snapshot"])
            self.assertEqual(result["segments"][-2]["text"].encode(), raw)
            self.assertIn("Markdown · " + url + "docs/规则.md", result["segments"][-2]["location"])
            self.assertEqual(result["segments"][-1]["text"], "条件全文\n[循环](../docs/规则.md)")
            targets = [call.args[0] for call in get.call_args_list]
            self.assertEqual(targets.count(url + "docs/%E8%A7%84%E5%88%99.md"), 1)
            self.assertEqual(targets.count(url + "shared/conditions.md?v=1"), 1)
            self.assertNotIn(url + "private.md", targets)
            self.assertNotIn(url + "pages/wallet.html", targets)
            same = prototype_link.read_pages(url, ["order.html"], catalog["snapshot"])
            self.assertEqual(same, result)
            content[url + "docs/%E8%A7%84%E5%88%99.md"] = raw + "新增业务规则".encode()
            changed = prototype_link.read_pages(url, ["order.html"], catalog["snapshot"])
            self.assertNotEqual(changed["snapshot_ref"], result["snapshot_ref"])
            self.assertEqual(result["segments"][-2]["text"].encode(), raw)

    def test_markdown_links_parse_html_and_reference_links_but_ignore_code_and_images(self):
        text = (
            '[规则][rules]\n\n[rules]: docs/rules.md "说明"\n\n'
            '<a href="docs/a&amp;b.md" target="_blank">原型链接</a>\n\n'
            "![图片](image.md)\n\n`[代码](inline.md)`\n\n"
            '```html\n<a href="code.md">代码</a>\n```\n'
        )
        self.assertEqual(prototype_link.markdown_links(text), ["docs/rules.md", "docs/a&b.md"])

    def test_markdown_references_cannot_escape_the_original_prototype_directory(self):
        root = "https://prototype.geekuat.com/p/Test123/"
        for href in (
            "https://evil.test/rules.md",
            "//127.0.0.1/private.md",
            "/p/Other/rules.md",
            "../../private.md",
            "docs/%2e%2e/%2e%2e/private.md",
            "docs/%252e%252e/private.md",
            "docs%5cprivate.md",
            "docs/%00private.md",
            "http://prototype.geekuat.com/p/Test123/rules.md",
            "https://user@prototype.geekuat.com/p/Test123/rules.md",
            "file:///C:/private.md",
            "docs/%FF.md",
            "docs/%oops.md",
            "docs/\nprivate.md",
        ):
            with self.subTest(href=href), self.assertRaises(AppError) as error:
                prototype_link.markdown_url(root, root, href)
            self.assertEqual(error.exception.detail, "prototype_link_markdown_unsupported")
        for href in ("#rules.md", "image.png", "https://example.com/help"):
            self.assertIsNone(prototype_link.markdown_url(root, root, href))
        self.assertEqual(
            prototype_link.markdown_url(root, root + "docs/rules.md", "../共享.md?版本=1#规则"),
            root + "%E5%85%B1%E4%BA%AB.md?%E7%89%88%E6%9C%AC=1",
        )

    def test_markdown_read_failure_never_returns_a_silently_incomplete_snapshot(self):
        root = "https://prototype.geekuat.com/p/Test123/"
        catalog = {
            "snapshot": "a" * 64,
            "pages": [{"file": "order.html", "path": "订单", "url": root + "pages/order.html"}],
            "notes": {"order.html": {"规则": ["[规则](r.md)"]}},
        }
        for body in (
            b"",
            b"\xef\xbb\xbf \n",
            b"\xff",
            b"a\x00b",
            b"<!doctype html><html>404</html>",
        ):
            with (
                self.subTest(body=body),
                patch.object(prototype_link, "catalog", return_value=catalog),
                patch.object(prototype_link, "fetch", side_effect=[b"HTML", body]),
                self.assertRaises(AppError) as error,
            ):
                prototype_link.read_pages(root, ["order.html"], "a" * 64)
            self.assertEqual(error.exception.detail, "prototype_link_markdown_unavailable")
        for detail in ("prototype_link_unavailable", "prototype_link_too_large"):
            with (
                patch.object(prototype_link, "catalog", return_value=catalog),
                patch.object(prototype_link, "fetch", side_effect=[b"HTML", AppError(422, detail)]),
                self.assertRaises(AppError) as error,
            ):
                prototype_link.read_pages(root, ["order.html"], "a" * 64)
            self.assertEqual(
                error.exception.detail,
                detail if detail.endswith("too_large") else "prototype_link_markdown_unavailable",
            )
        with (
            patch.object(prototype_link, "catalog", return_value=catalog),
            patch.object(prototype_link, "fetch", side_effect=[b"HTML", b"x" * 31]),
            patch.object(prototype_link, "MAX_INPUT", 30),
            self.assertRaises(AppError) as error,
        ):
            prototype_link.read_pages(root, ["order.html"], "a" * 64)
        self.assertEqual(error.exception.detail, "prototype_link_too_large")

    def test_appended_annotations_constants_and_fixed_loops_preserve_page_pairing(self):
        url = "https://prototype.geekuat.com/p/Test123/"
        source = r"""
window.PROTOTYPE_PAGES = [{title:'订单', module:'业务', file:'order.html'}];
window.PROTOTYPE_ANNOTATIONS = {};
window.PROTOTYPE_ANNOTATIONS['*'] = [{title:'说明',items:['公共条件']}];
window.PROTOTYPE_ANNOTATIONS['order.html'] = [{title:'说明',items:['订单条件']}];
window.PROTOTYPE_PAGES.push({title:'详情',module:'业务',file:'detail.html'});
[['order.html', [{title:'追加',markdown:'金额规则\n保持完整'}]]].forEach(function(entry){
 var file = entry[0], sections = entry[1];
 window.PROTOTYPE_ANNOTATIONS[file] = (window.PROTOTYPE_ANNOTATIONS[file] || []).concat(sections);
});
[['detail.html','order.html']].forEach(function(pair){
 window.PROTOTYPE_ANNOTATIONS[pair[0]] = window.PROTOTYPE_ANNOTATIONS[pair[1]] || [];
});
const extra = '独立说明';
window.PROTOTYPE_ANNOTATIONS['detail.html'] = [{title:'详情说明',markdown:extra+'\n观察位置'}];
"""
        content = {
            url: b'<script src="assets/annotations.js"></script>',
            url + "assets/annotations.js": source.encode(),
            url + "pages/order.html": b"<h1>Order</h1>",
            url + "pages/detail.html": b"<h1>Detail</h1>",
        }
        with patch.object(prototype_link, "fetch", side_effect=content.__getitem__):
            catalog = prototype_link.catalog(url)
            self.assertEqual(len(catalog["pages"]), 2)
            result = prototype_link.read_pages(
                url, ["order.html", "detail.html"], catalog["snapshot"]
            )
            self.assertEqual(
                [s["text"] for s in result["segments"]],
                [
                    "<h1>Order</h1>",
                    "公共条件\n订单条件",
                    "金额规则\n保持完整",
                    "<h1>Detail</h1>",
                    "公共条件",
                    "独立说明\n观察位置",
                ],
            )
            self.assertIn("订单 · 批注：追加", result["segments"][2]["location"])
        # Copy-by-file alias is static data, never an executed callback.
        from app.integrations.prototype_data import read_registry

        aliases = source[: source.index("const extra")]
        self.assertEqual(
            read_registry(aliases)["PROTOTYPE_ANNOTATIONS"]["detail.html"],
            read_registry(aliases)["PROTOTYPE_ANNOTATIONS"]["order.html"],
        )
        for suffix in [
            "window.PROTOTYPE_ANNOTATIONS['order.html']=fetch('https://bad.test');",
            "window.PROTOTYPE_ANNOTATIONS['order.html']=[{title:'x',items:[`x${run()}`]}];",
            "[['order.html',[]]].forEach(function(entry){run();});",
        ]:
            with self.assertRaises(AppError):
                read_registry(aliases + suffix)

    def test_generic_link_catalog_rejects_unsafe_files_and_invalid_notes(self):
        url = "https://prototype.geekuat.com/p/Test123/"
        page = {"title": "页面", "module": "目录", "file": "order.html"}
        for filename in (
            "../order.html",
            "https://example.com/order.html",
            "order.html?x=1",
            "order.html#x",
            "a/order.html",
            "a\\order.html",
            "%2e%2e.html",
        ):
            with self.subTest(filename=filename):
                if filename != "a/order.html":
                    with self.assertRaises(ValidationError):
                        AnalysisSelection(document_id=1, version_id=None, paths=[filename])
                source = (
                    "window.PROTOTYPE_PAGES="
                    + json.dumps([{**page, "file": filename}])
                    + ";window.PROTOTYPE_ANNOTATIONS={};"
                ).encode()
                with patch.object(
                    prototype_link,
                    "fetch",
                    side_effect=[b'<script src="assets/annotations.js"></script>', source],
                ) as get:
                    with self.assertRaises(AppError):
                        prototype_link.catalog(url)
                    self.assertEqual(get.call_count, 2)
        for pages, notes in [
            ([page, page], {}),
            ([{**page, "module": 1}], {}),
            ([page], {"order.html": [{"title": "说明", "items": [123]}]}),
            ([page], {"order.html": [{"title": "说明", "markdown": []}]}),
            ([page], {"order.html": "not a list"}),
        ]:
            source = (
                "window.PROTOTYPE_PAGES="
                + json.dumps(pages)
                + ";window.PROTOTYPE_ANNOTATIONS="
                + json.dumps(notes)
            ).encode()
            with (
                patch.object(
                    prototype_link,
                    "fetch",
                    side_effect=[b'<script src="assets/annotations.js"></script>', source],
                ),
                self.assertRaises(AppError),
            ):
                prototype_link.catalog(url)

    def test_url_scope_and_remote_read_whitelist(self):
        self.assertEqual(GitScope(connection_id=1, repository_id=1, branch="main").path, "")
        self.assertEqual(
            GitScope(connection_id=1, repository_id=1, branch="main", path="  ").path, ""
        )
        for url in [
            "javascript:alert(1)",
            "file:///x",
            "https://u:password@example.com",
            "https://example.com\\@private",
            "https://example.com:bad",
        ]:
            with self.assertRaises(ValidationError):
                LiveInput(kind="LINK", name="页面", url=url, revision=0)
        for path in ["../x", "/x", "a//b", "a\\b", "a/./b"]:
            with self.assertRaises(ValidationError):
                GitScope(connection_id=1, repository_id=1, branch="main", path=path)
        with self.assertRaises(AppError):
            github.github_get("synthetic", "push", full_name="team/web")
        with self.assertRaises(AppError):
            github.github_get("synthetic", "tree", full_name="team/..", sha=TREE)
        with self.assertRaises(AppError):
            github.github_get("synthetic", "tree", full_name="team/web", sha="main?x=1")

    def test_tree_is_fixed_complete_and_does_not_follow_symlinks(self):
        responses = [
            {
                "id": 5,
                "full_name": "team/web",
                "private": True,
                "default_branch": "main",
                "owner": {"login": "team", "type": "Organization"},
            },
            {"name": "main", "commit": {"sha": SHA}},
            {"sha": SHA, "tree": {"sha": TREE}},
            {
                "sha": TREE,
                "truncated": False,
                "tree": [
                    FILE,
                    {**FILE, "path": "prototype-link/out.html"},
                    {**FILE, "path": "prototype/link.html", "mode": "120000"},
                ],
            },
        ]
        with patch.object(github, "github_get", side_effect=responses) as get:
            result = github.prototype_scope("synthetic", 5, "main", "prototype")
        self.assertEqual(result["files"], [{k: FILE[k] for k in ("path", "sha", "size")}])
        self.assertEqual(get.call_args_list[-1].kwargs["sha"], TREE)
        with patch.object(github, "github_get", side_effect=responses):
            whole = github.prototype_scope("synthetic", 5, "main", "")
        self.assertEqual(
            [f["path"] for f in whole["files"]], ["prototype-link/out.html", FILE["path"]]
        )
        with patch.object(github, "github_get", side_effect=[responses[0], *responses[2:]]) as get:
            fixed = github.prototype_scope("synthetic", 5, SHA, "prototype")
        self.assertEqual(fixed["commit"], SHA)
        self.assertEqual(fixed["files"], result["files"])
        self.assertNotIn("branch", [call.args[1] for call in get.call_args_list])
        responses[-1] = {
            **responses[-1],
            "tree": [{**FILE, "path": f"prototype/page-{i}.html"} for i in range(1001)],
        }
        with patch.object(github, "github_get", side_effect=responses):
            many = github.prototype_scope("synthetic", 5, "main", "")
        self.assertEqual(len(many["files"]), 1001)
        payload = LiveInput(
            kind="GITHUB",
            name="整库原型",
            revision=0,
            git=GitScope(connection_id=1, repository_id=1, branch="main"),
            commit=SHA,
            selected_paths=[f["path"] for f in many["files"]],
        )
        self.assertEqual(len(payload.selected_paths), 1001)
        partial = {**responses[-1], "truncated": True}
        with (
            patch.object(github, "github_get", side_effect=[*responses[:-1], partial, partial]),
            self.assertRaises(AppError) as error,
        ):
            github.prototype_scope("synthetic", 5, "main", "prototype")
        self.assertEqual(error.exception.detail, "prototype_tree_incomplete")

    def test_large_tree_response_and_large_file_metadata_are_not_capped(self):
        data = {"sha": TREE, "truncated": False, "tree": [FILE], "padding": "x" * 3_000_000}
        with patch.object(github, "build_opener") as opener:
            opener.return_value.open.return_value = io.BytesIO(json.dumps(data).encode())
            result = github.github_get("synthetic", "tree", full_name="team/web", sha=TREE)
        self.assertEqual(len(result["padding"]), 3_000_000)

    def test_truncated_tree_walks_only_selected_directories_without_losing_files(self):
        child_sha = "d" * 40
        responses = [
            {
                "id": 5,
                "full_name": "team/web",
                "private": True,
                "default_branch": "main",
                "owner": {"login": "team", "type": "Organization"},
            },
            {"name": "main", "commit": {"sha": SHA}},
            {"sha": SHA, "tree": {"sha": TREE}},
            {"sha": TREE, "truncated": True, "tree": [FILE]},
            {
                "sha": TREE,
                "truncated": False,
                "tree": [
                    {"path": "prototype", "type": "tree", "sha": child_sha},
                    {"path": "unrelated", "type": "tree", "sha": "e" * 40},
                ],
            },
            {
                "sha": child_sha,
                "truncated": False,
                "tree": [
                    {**FILE, "path": "index.html", "size": 11 * 1024 * 1024},
                    {**FILE, "path": "other.html"},
                ],
            },
        ]
        with patch.object(github, "github_get", side_effect=responses) as get:
            result = github.prototype_scope("synthetic", 5, "main", "prototype")
        self.assertEqual(
            [f["path"] for f in result["files"]], ["prototype/index.html", "prototype/other.html"]
        )
        self.assertEqual(result["files"][0]["size"], 11 * 1024 * 1024)
        self.assertEqual(
            [c.kwargs["sha"] for c in get.call_args_list if c.args[1] == "tree_shallow"],
            [TREE, child_sha],
        )
        with (
            patch.object(
                github,
                "github_get",
                side_effect=[
                    {"sha": TREE, "truncated": True, "tree": []},
                    {
                        "sha": TREE,
                        "truncated": False,
                        "tree": [{"path": "loop", "type": "tree", "sha": TREE}],
                    },
                ],
            ),
            self.assertRaises(AppError),
        ):
            github.prototype_tree("synthetic", "team/web", TREE, "")


@unittest.skipUnless(os.environ.get("RUN_AUTH_DB_TESTS") == "1", "requires migrated PostgreSQL")
class PrototypeDatabaseTests(unittest.TestCase):
    setUpClass = classmethod(test_auth.AuthDatabaseTests.setUpClass.__func__)
    login = test_auth.AuthDatabaseTests.login

    def setUp(self):
        test_auth.AuthDatabaseTests.setUp(self)
        self.storage = tempfile.TemporaryDirectory()
        self.environment = patch.dict(os.environ, {"DOCUMENT_STORAGE_PATH": self.storage.name})
        self.environment.start()
        with Session(self.connection, join_transaction_mode="create_savepoint") as db:
            project = Project(
                name="原型测试",
                identifier=self.prefix,
                owner_id=self.admin_id,
                created_by=self.admin_id,
            )
            db.add(project)
            db.flush()
            self.project_id = project.id
            db.add(ProjectMember(project_id=project.id, user_id=self.member_id))
            repo = ProjectRepository(
                project_id=project.id,
                github_id=5,
                full_name="team/web",
                kind="WEB",
                default_branch="main",
                updated_by=self.admin_id,
            )
            connection = GitHubConnection(
                owner_id=self.admin_id,
                name="本人连接",
                kind="automatic",
                resource_owner="team",
                github_login="test",
                encrypted_token=token_cipher().encrypt(b"synthetic-test-token").decode(),
                version=1,
            )
            foreign = GitHubConnection(
                owner_id=self.member_id,
                name="他人连接",
                kind="automatic",
                resource_owner="team",
                github_login="test",
                encrypted_token=token_cipher().encrypt(b"synthetic-test-token").decode(),
                version=1,
            )
            db.add_all([repo, connection, foreign])
            db.flush()
            self.repo_id, self.connection_id, self.foreign_id = repo.id, connection.id, foreign.id
            for c in [connection, foreign]:
                db.add(
                    GitHubRepository(
                        connection_id=c.id,
                        github_id=5,
                        full_name="team/web",
                        default_branch="main",
                        private=True,
                        owner_type="Organization",
                    )
                )
            db.commit()
        self.base = f"/api/projects/{self.project_id}/prototypes"
        self.docs = f"/api/projects/{self.project_id}/documents"
        self.git = {
            "connection_id": self.connection_id,
            "repository_id": self.repo_id,
            "branch": "main",
            "path": "prototype",
        }
        self.sha = SHA
        self.tree = [dict(FILE)]
        self.assertEqual(self.login().status_code, 200)

    def tearDown(self):
        test_auth.AuthDatabaseTests.tearDown(self)
        self.environment.stop()
        self.storage.cleanup()

    def remote(self, token, operation, **kwargs):
        self.assertEqual(token, "synthetic-test-token")
        if operation == "repository":
            return {
                "id": 5,
                "full_name": "team/web",
                "private": True,
                "default_branch": "main",
                "owner": {"login": "team", "type": "Organization"},
            }
        if operation == "branch":
            return {"name": kwargs["branch"], "commit": {"sha": self.sha}}
        if operation == "git_commit":
            return {"sha": kwargs["sha"], "tree": {"sha": TREE}}
        if operation == "tree":
            return {"sha": TREE, "truncated": False, "tree": self.tree}
        self.fail("unexpected remote operation")

    def post(self, path, payload):
        return self.client.post(self.base + path, json=payload, headers=test_auth.ORIGIN)

    def revision(self):
        return self.client.get(self.base).json()["revision"]

    def test_project_git_history_rechecks_owner_grant_and_project(self):
        route = f"/api/projects/{self.project_id}/repositories/{self.repo_id}/versions"
        result = {
            "items": [{"name": "main", "sha": SHA, "message": "", "date": ""}],
            "has_more": False,
            "page": 1,
            "kind": "branches",
            "repository_id": 5,
            "ref": "",
        }
        with patch.object(github, "repository_versions", return_value=result) as read:
            response = self.client.get(route, params={"connection_id": self.connection_id})
            self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual(response.json()["association_id"], self.repo_id)
            self.assertEqual(response.json()["project_id"], self.project_id)
            read.assert_called_once_with("synthetic-test-token", 5, "branches", "", 1)
        with patch.object(github, "repository_versions") as read:
            self.assertEqual(
                self.client.get(route, params={"connection_id": self.foreign_id}).status_code, 404
            )
            self.assertEqual(
                self.client.get(
                    route, params={"connection_id": self.connection_id, "kind": "push"}
                ).status_code,
                422,
            )
            self.assertEqual(
                self.client.get(
                    route, params={"connection_id": self.connection_id, "ref": "main?token=x"}
                ).status_code,
                422,
            )
            read.assert_not_called()

        def revoked(*args):
            with Session(self.connection, join_transaction_mode="create_savepoint") as db:
                db.execute(
                    delete(GitHubRepository).where(
                        GitHubRepository.connection_id == self.connection_id
                    )
                )
                db.commit()
            return result

        with patch.object(github, "repository_versions", side_effect=revoked):
            response = self.client.get(route, params={"connection_id": self.connection_id})
            self.assertEqual(response.status_code, 403, response.text)

    def test_link_catalog_requires_project_access_and_keeps_source_read_only(self):
        url = "https://prototype.geekuat.com/p/Test123/"
        created = self.post(
            "", {"kind": "LINK", "name": "页面", "url": url, "revision": self.revision()}
        )
        self.assertEqual(created.status_code, 201, created.text)
        source_id = created.json()["sources"][0]["id"]
        with patch.object(
            prototype_link,
            "catalog",
            return_value={
                "snapshot": "a" * 64,
                "pages": [
                    {"file": "page-1.html", "path": "首页", "url": url + "pages/page-1.html"}
                ],
                "notes": {},
            },
        ) as fetch:
            response = self.client.get(self.base + f"/{source_id}/pages")
            self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual(response.json()["pages"][0]["path"], "首页")
            fetch.assert_called_once_with(url)
            self.assertEqual(
                self.client.get(
                    f"/api/projects/{self.project_id + 1000000}/prototypes/{source_id}/pages"
                ).status_code,
                404,
            )

    def test_more_than_one_thousand_files_can_be_saved_and_checked(self):
        self.tree = [{**FILE, "path": f"prototype/page-{i}.html"} for i in range(1001)]
        with patch.object(github, "github_get", side_effect=self.remote):
            result = self.post("/scope", self.git)
            self.assertEqual(result.status_code, 200)
            paths = [f["path"] for f in result.json()["files"]]
            saved = self.post(
                "",
                {
                    "kind": "GITHUB",
                    "name": "全部原型文件",
                    "revision": self.revision(),
                    "git": self.git,
                    "commit": SHA,
                    "selected_paths": paths,
                },
            )
            self.assertEqual(saved.status_code, 201, saved.text)
            row = saved.json()["sources"][0]
            self.assertEqual(len(row["selected_paths"]), 1001)
            checked = self.post(f"/{row['id']}/check", {"connection_id": self.connection_id})
            self.assertEqual(checked.status_code, 200, checked.text)
            self.assertEqual(len(checked.json()["source"]["files"]), 1001)

    def test_groups_links_images_scope_and_immutable_image_versions(self):
        group = self.post("/groups", {"revision": 0, "name": "页面"})
        self.assertEqual(group.status_code, 201, group.text)
        group_id = group.json()["groups"][0]["id"]
        req_group = self.client.post(
            self.docs + "/groups", json={"revision": 1, "name": "页面"}, headers=test_auth.ORIGIN
        )
        self.assertEqual(req_group.status_code, 201, req_group.text)
        payload = {
            "kind": "LINK",
            "name": "原型地址",
            "url": "https://example.com/prototype",
            "group_id": group_id,
            "revision": 2,
        }
        response = self.post("", payload)
        self.assertEqual(response.status_code, 201, response.text)
        link = response.json()["sources"][0]
        self.assertIsNone(link["current"])
        self.assertEqual(self.client.get(self.docs).json()["documents"], [])
        self.assertEqual(self.post("", payload).status_code, 409)
        edited = self.client.patch(
            self.base + f"/{link['id']}",
            json={**payload, "url": "https://example.com/new", "revision": self.revision()},
            headers=test_auth.ORIGIN,
        )
        self.assertEqual(edited.status_code, 200, edited.text)
        self.assertEqual(edited.json()["sources"][0]["id"], link["id"])
        self.assertEqual(len(edited.json()["sources"]), 1)
        req_group_id = req_group.json()["groups"][0]["id"]
        self.assertEqual(
            self.post(
                "/move",
                {
                    "revision": self.revision(),
                    "document_ids": [link["id"]],
                    "group_id": req_group_id,
                },
            ).status_code,
            404,
        )
        params = {
            "filename": "页面.png",
            "name": "页面截图",
            "description": "订单列表",
            "upload_id": str(uuid4()),
            "revision": self.revision(),
            "group_id": group_id,
        }
        image = self.client.post(
            self.base + "/upload", params=params, content=PNG, headers=test_auth.ORIGIN
        )
        self.assertEqual(image.status_code, 201, image.text)
        source = next(s for s in image.json()["sources"] if s["kind"] == "FILE")
        old_version = source["current"]
        self.assertEqual(self.client.get(self.docs).json()["documents"], [])
        self.assertEqual(
            len(self.client.get(self.docs + "?include_prototypes=true").json()["documents"]), 1
        )
        self.assertEqual(
            self.client.post(
                self.docs + "/upload",
                params={k: v for k, v in params.items() if k not in {"name", "description"}},
                content=PNG,
                headers=test_auth.ORIGIN,
            ).status_code,
            409,
        )
        params.update(document_id=source["id"], upload_id=str(uuid4()), revision=self.revision())
        second = self.client.post(
            self.base + "/upload", params=params, content=PNG, headers=test_auth.ORIGIN
        )
        self.assertEqual(second.status_code, 201, second.text)
        versions = self.client.get(self.docs + f"/{source['id']}/versions").json()
        self.assertEqual([v["number"] for v in versions], [2, 1])
        download = self.client.get(self.docs + f"/versions/{old_version['id']}/file?inline=true")
        self.assertEqual(download.content, PNG)
        self.assertIn("sandbox", download.headers["content-security-policy"])
        params.update(filename="bad.zip", upload_id=str(uuid4()), revision=self.revision())
        self.assertEqual(
            self.client.post(
                self.base + "/upload", params=params, content=b"<script>", headers=test_auth.ORIGIN
            ).status_code,
            422,
        )
        self.assertEqual(self.login(self.member_name).status_code, 200)
        self.assertEqual(self.client.get(self.base).status_code, 200)
        with Session(self.connection, join_transaction_mode="create_savepoint") as db:
            db.execute(
                delete(ProjectMember).where(
                    ProjectMember.project_id == self.project_id,
                    ProjectMember.user_id == self.member_id,
                )
            )
            db.commit()
        self.assertEqual(self.client.get(self.base).status_code, 404)
        self.assertEqual(
            self.client.get(self.docs + f"/versions/{old_version['id']}/file").status_code, 404
        )

    def test_html_upload_versions_preview_download_and_analysis(self):
        from pathlib import Path

        from app.modules.requirements.analysis_materials import file_material

        body = "<!doctype html><html><h1>订单</h1><script>alert(1)</script></html>".encode()
        params = {"filename": "页面.HTML", "upload_id": str(uuid4()), "revision": self.revision()}
        response = self.client.post(
            self.base + "/upload", params=params, content=body, headers=test_auth.ORIGIN
        )
        self.assertEqual(response.status_code, 201, response.text)
        source = response.json()["sources"][0]
        old = source["current"]
        url = self.docs + f"/versions/{old['id']}"
        preview = self.client.get(url + "/preview")
        self.assertEqual(preview.status_code, 200, preview.text)
        self.assertEqual(preview.json()["kind"], "text")
        self.assertEqual(preview.json()["text"], body.decode())
        browser = self.client.get(url + "/browser")
        self.assertEqual(browser.status_code, 200, browser.text)
        self.assertEqual(browser.content, body)
        self.assertIn("text/html", browser.headers["content-type"])
        policy = browser.headers["content-security-policy"]
        self.assertIn("sandbox allow-scripts;", policy)
        self.assertNotIn("allow-same-origin", policy)
        self.assertIn("default-src 'none'", policy)
        self.assertEqual(browser.headers["cache-control"], "no-store")
        download = self.client.get(url + "/file?inline=true")
        self.assertEqual(download.content, body)
        self.assertIn("attachment", download.headers["content-disposition"])
        self.assertIn("text/plain", download.headers["content-type"])
        self.assertIn("sandbox", download.headers["content-security-policy"])
        for invalid in (b"", b"\x00\x01"):
            params.update(upload_id=str(uuid4()), revision=self.revision())
            rejected = self.client.post(
                self.base + "/upload", params=params, content=invalid, headers=test_auth.ORIGIN
            )
            self.assertEqual(rejected.status_code, 422, rejected.text)
        params.update(
            document_id=source["id"],
            filename="页面.htm",
            upload_id=str(uuid4()),
            revision=self.revision(),
        )
        updated = self.client.post(
            self.base + "/upload",
            params=params,
            content=body + b"<!--new-->",
            headers=test_auth.ORIGIN,
        )
        self.assertEqual(updated.status_code, 201, updated.text)
        self.assertEqual(updated.json()["sources"][0]["current"]["number"], 2)
        self.assertEqual(self.client.get(url + "/file").content, body)
        self.assertEqual(
            [v["number"] for v in self.client.get(self.docs + f"/{source['id']}/versions").json()],
            [2, 1],
        )
        params.update(document_id=None, upload_id=str(uuid4()), revision=self.revision())
        self.assertEqual(
            self.client.post(
                self.docs + "/upload",
                params={k: v for k, v in params.items() if v is not None},
                content=body,
                headers=test_auth.ORIGIN,
            ).status_code,
            422,
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "page.html"
            full = body.decode() + "正文" * 100000
            path.write_text(full, encoding="utf-8")
            material = file_material(path, "html", "source-1", path.name)
            self.assertEqual(material["read_state"], "READABLE")
            self.assertEqual("".join(x["text"] for x in material["segments"]), full)
        self.assertEqual(self.login(self.member_name).status_code, 200)
        self.assertEqual(self.client.get(url + "/file").content, body)
        with Session(self.connection, join_transaction_mode="create_savepoint") as db:
            db.execute(
                delete(ProjectMember).where(
                    ProjectMember.project_id == self.project_id,
                    ProjectMember.user_id == self.member_id,
                )
            )
            db.commit()
        self.assertEqual(self.client.get(url + "/file").status_code, 404)
        self.assertEqual(self.client.get(url + "/browser").status_code, 404)

    def test_github_fixed_scope_updates_editing_and_authorization_rechecks(self):
        with patch.object(github, "github_get", side_effect=self.remote):
            options = self.client.get(self.base + "/options").json()
            self.assertEqual([c["id"] for c in options], [self.connection_id])
            self.assertEqual(
                self.post("/scope", {**self.git, "connection_id": self.foreign_id}).status_code, 404
            )
            result = self.post("/scope", self.git)
            self.assertEqual(result.status_code, 200, result.text)
            self.assertEqual(result.json()["commit"], SHA)
            without_path = {k: v for k, v in self.git.items() if k != "path"}
            self.assertEqual(self.post("/scope", without_path).status_code, 200)
            self.git["path"] = ""
            payload = {
                "kind": "GITHUB",
                "name": "Git原型",
                "git": self.git,
                "selected_paths": [FILE["path"]],
                "commit": SHA,
                "revision": self.revision(),
            }
            saved = self.post("", payload)
            self.assertEqual(saved.status_code, 201, saved.text)
            source = saved.json()["sources"][0]
            self.sha = "d" * 40
            checked = self.post(f"/{source['id']}/check", {"connection_id": self.connection_id})
            self.assertEqual(checked.status_code, 200, checked.text)
            self.assertTrue(checked.json()["changed"])
            self.assertEqual(checked.json()["source"]["latest_commit"], self.sha)
            self.assertEqual(len(self.client.get(self.base).json()["sources"]), 1)
            self.assertFalse(
                self.post(f"/{source['id']}/check", {"connection_id": self.connection_id}).json()[
                    "changed"
                ]
            )
            self.assertEqual(
                self.post("", {**payload, "revision": self.revision()}).status_code, 409
            )
            self.tree = [{**FILE, "path": "prototype/other.html"}]
            self.sha = "e" * 40
            failed = self.post(f"/{source['id']}/check", {"connection_id": self.connection_id})
            self.assertEqual(failed.status_code, 409)
            self.assertEqual(
                self.client.get(self.base).json()["sources"][0]["latest_commit"], "d" * 40
            )
            self.tree = [dict(FILE)]
            edited = self.client.patch(
                self.base + f"/{source['id']}",
                json={
                    **payload,
                    "name": "修改来源",
                    "commit": self.sha,
                    "revision": self.revision(),
                },
                headers=test_auth.ORIGIN,
            )
            self.assertEqual(edited.status_code, 200, edited.text)
            self.assertEqual(edited.json()["sources"][0]["id"], source["id"])
            self.assertEqual(
                self.post(
                    "/scope", {**self.git, "repository_id": self.repo_id + 100000}
                ).status_code,
                404,
            )

        def revoked(token, operation, **kwargs):
            response = self.remote(token, operation, **kwargs)
            if operation == "tree":
                with Session(self.connection, join_transaction_mode="create_savepoint") as db:
                    db.execute(
                        delete(GitHubRepository).where(
                            GitHubRepository.connection_id == self.connection_id
                        )
                    )
                    db.commit()
            return response

        with patch.object(github, "github_get", side_effect=revoked):
            self.assertEqual(
                self.post(
                    f"/{source['id']}/check", {"connection_id": self.connection_id}
                ).status_code,
                403,
            )
        with Session(self.connection, join_transaction_mode="create_savepoint") as db:
            self.assertEqual(
                db.scalar(
                    select(SourceDocument).where(SourceDocument.id == source["id"])
                ).latest_commit,
                "e" * 40,
            )
