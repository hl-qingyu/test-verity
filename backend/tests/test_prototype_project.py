import json
import unittest
from unittest.mock import patch

from pydantic import ValidationError

from app.core.errors import AppError
from app.integrations import prototype_link
from app.integrations.prototype_project import annotation_blocks, assignments, manifest, tree_pages
from app.modules.requirements.risk_schemas import AnalysisSelection

ROOT = "http://127.0.0.1:4173/"
LINK = ROOT + "#page=pages%2Fadmin%2Fsettings-store-edit.html"
APP = {"key": "admin", "name": "管理后台", "pages": "pages/admin/", "tree": "trees/admin.js"}


def project_html(apps):
    data = {"format": "html-prototype-project", "version": 1, "apps": apps}
    return (
        "<script>window.PROTO_PROJECT="
        + json.dumps(data)
        + ";</script>"
        + "".join(f'<script src="{app["tree"]}"></script>' for app in apps)
    ).encode()


class PrototypeProjectTests(unittest.TestCase):
    def fixtures(self):
        mobile = {"key": "h5", "name": "员工", "pages": "pages/h5/", "tree": "trees/h5.js"}
        return {
            ROOT: project_html([APP, mobile]),
            ROOT + APP["tree"]: (
                "window.PROTO_TREE=[{group:'系统设置',pages:["
                "{file:'settings-store-edit.html',title:'门店编辑',states:[{title:'新增'}]}],"
                "groups:[{group:'资料',pages:[{file:'docs/rules.html',title:'规则'}]}]},"
                "{group:'需求资料',pages:[{file:'hidden.html',title:'隐藏'}]}]"
                ".filter(group => group.group !== '需求资料'); // 保留隐藏配置\n"
            ).encode(),
            ROOT + mobile["tree"]: b"window.PROTO_TREE=[{file:'home.html',title:'Home'}];",
            ROOT + "pages/admin/settings-store-edit.html": b"<h1>Store</h1>",
            ROOT + "pages/admin/settings-store-edit.annotations.js": (
                "window.PROTO_ANNOTATIONS=window.PROTO_ANNOTATIONS||{};"
                'window.PROTO_ANNOTATIONS["pages/admin/settings-store-edit.html"]='
                '{sections:[{t:"字段",d:["必填规则","[详细规则](docs/rules.md)"]}],'
                'annos:[{text:"按钮说明",x:10,y:20}]};'
            ).encode(),
            ROOT + "pages/admin/docs/rules.md": "# 详细规则\n完整正文".encode(),
        }

    def test_multi_app_catalog_and_selected_annotations_are_fixed(self):
        content = self.fixtures()
        with patch.object(prototype_link, "fetch", side_effect=content.__getitem__) as get:
            index = prototype_link.catalog(LINK)
            self.assertEqual(
                [p["file"] for p in index["pages"]],
                ["admin/settings-store-edit.html", "admin/docs/rules.html", "h5/home.html"],
            )
            self.assertEqual(index["pages"][1]["path"], "管理后台 / 系统设置 / 资料 / 规则")
            selected = ["admin/settings-store-edit.html"]
            result = prototype_link.read_pages(LINK, selected, index["snapshot"])
            self.assertEqual(
                [s["text"] for s in result["segments"]],
                [
                    "<h1>Store</h1>",
                    "必填规则\n[详细规则](docs/rules.md)",
                    "按钮说明",
                    "# 详细规则\n完整正文",
                ],
            )
            fetched = [call.args[0] for call in get.call_args_list]
            self.assertNotIn(ROOT + "pages/h5/home.html", fetched)
            self.assertNotIn(ROOT + "pages/admin/docs/rules.html", fetched)
            annotation = ROOT + "pages/admin/settings-store-edit.annotations.js"
            content[annotation] = content[annotation].replace(
                "按钮说明".encode(), "新说明".encode()
            )
            changed = prototype_link.read_pages(LINK, selected, index["snapshot"])
            self.assertNotEqual(result["snapshot_ref"], changed["snapshot_ref"])
            content[ROOT + APP["tree"]] += b"\n// changed"
            with self.assertRaises(AppError) as error:
                prototype_link.read_pages(LINK, selected, index["snapshot"])
            self.assertEqual(error.exception.detail, "prototype_link_changed")

    def test_local_source_is_limited_to_the_authorized_service(self):
        for url in (ROOT, LINK, ROOT + "index.html?end=admin#page=pages/admin/a.html"):
            self.assertEqual(prototype_link.base_url(url), ROOT)
        for url in (
            "http://127.0.0.1:8000/",
            "http://localhost:4173/",
            "http://127.0.0.2:4173/",
            ROOT + "../",
            ROOT + "?url=http://localhost/",
            ROOT + "?end=admin&end=h5",
            ROOT + "#page=pages%2F..%2Fsecret.html",
            ROOT + "?token=secret",
        ):
            with (
                self.subTest(url=url),
                self.assertRaises(AppError),
                patch.object(prototype_link, "fetch") as get,
            ):
                prototype_link.catalog(url)
            get.assert_not_called()

    def test_literal_parser_rejects_executable_or_ambiguous_data(self):
        for source in (
            "window.PROTO_TREE=run();",
            "window.PROTO_TREE=[{file:`${run()}.html`}];",
            "window.PROTO_TREE=[];fetch('http://localhost');",
            "window.PROTO_TREE=[].filter(group => run(group));",
            "window.PROTO_TREE=[];window.PROTO_TREE=[];",
        ):
            with self.subTest(source=source), self.assertRaises(AppError):
                tree_pages(source, APP, ROOT)
        for file in (
            "../a.html",
            "https://host/a.html",
            "a/%2e%2e/x.html",
            "a\\b.html",
            "a.html?x=1",
        ):
            with self.subTest(file=file), self.assertRaises(AppError):
                tree_pages(
                    "window.PROTO_TREE=" + json.dumps([{"file": file, "title": "x"}]), APP, ROOT
                )
        bad_app = {**APP, "tree": "http://127.0.0.1:8000/"}
        with self.assertRaises(AppError):
            manifest(project_html([bad_app]).decode())
        with self.assertRaises(AppError):
            assignments("window.PROTO_TREE=[];window.OTHER={};", {"PROTO_TREE"})

    def test_annotations_must_belong_to_the_selected_page(self):
        for key, data in (
            ("pages/other.html", "{}"),
            ("pages/admin/a.html", '{sections:[{t:"规则",d:[123]}]}'),
            ("pages/admin/a.html", "{annos:[{text:123}]}"),
        ):
            with self.assertRaises(AppError):
                annotation_blocks(
                    f'window.PROTO_ANNOTATIONS={{}};window.PROTO_ANNOTATIONS["{key}"]={data}',
                    "admin/a.html",
                )
        self.assertEqual(
            annotation_blocks(
                'window.PROTO_ANNOTATIONS={};window.PROTO_ANNOTATIONS["pages/admin/a.html"]={note:"原说明"}',
                "admin/a.html",
            ),
            {"页面说明": ["原说明"]},
        )

    def test_nested_selection_paths_are_safe_relative_paths(self):
        item = AnalysisSelection(document_id=1, version_id=None, paths=["admin/docs/a.html"])
        self.assertEqual(item.paths, ["admin/docs/a.html"])
        for path in (
            "../a.html",
            "admin/../a.html",
            "/admin/a.html",
            "admin//a.html",
            "admin/a.html#x",
        ):
            with self.assertRaises(ValidationError):
                AnalysisSelection(document_id=1, version_id=None, paths=[path])


if __name__ == "__main__":
    unittest.main()
