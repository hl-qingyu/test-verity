"""Fixed-version asset embedding without network or filesystem path access."""

import base64
import unittest
from html.parser import HTMLParser

from app.modules.prototypes.html_preview import local_path, render


class Elements(HTMLParser):
    def __init__(self, source):
        super().__init__()
        self.tags = []
        self.feed(source)

    def handle_starttag(self, tag, attrs):
        self.tags.append((tag, dict(attrs)))


def data_body(value):
    return base64.b64decode(value.split(",", 1)[1].split("#", 1)[0])


class DirectoryHtmlPreviewTests(unittest.TestCase):
    def preview(self, source, assets):
        reads = []
        index = {path: {"path": path, "extension": path.rsplit(".", 1)[-1]} for path in assets}

        def read(entry):
            reads.append(entry["path"])
            return assets[entry["path"]]

        return render(source, "site/pages/a.html", index, read), reads

    def test_relative_assets_preserve_content_and_do_not_read_unreferenced_files(self):
        source = (
            '<script src="../assets/common.js?v=42" defer></script>\r\n'
            '<link rel="stylesheet" href="../assets/app.css">'
            '<img src="../图片/订单.png">'
            '<p>中文 &amp; 正文</p><script>window.after="</not-a-tag>";</script>'
        )
        assets = {
            "site/assets/common.js": b"window.ready=true;",
            "site/assets/app.css": b"body{color:green}",
            "site/图片/订单.png": b"image-bytes",
            "site/assets/unused.js": b"unused",
        }
        output, reads = self.preview(source, assets)
        tags = Elements(output).tags
        self.assertEqual(data_body(tags[0][1]["src"]), assets["site/assets/common.js"])
        self.assertIn("defer", tags[0][1])
        self.assertEqual(data_body(tags[1][1]["href"]), assets["site/assets/app.css"])
        self.assertEqual(data_body(tags[2][1]["src"]), assets["site/图片/订单.png"])
        self.assertEqual(len(reads), 3)
        self.assertNotIn("site/assets/unused.js", reads)
        self.assertIn(source[source.index("<p>") :], output)

    def test_css_imports_images_and_cycles_are_resolved_against_each_stylesheet(self):
        output, reads = self.preview(
            '<link rel="stylesheet" href="../assets/a.css">',
            {
                "site/assets/a.css": b'@import "b.css"; .a{background:url(../images/a.png)}',
                "site/assets/b.css": b'@import url("a.css"); .b{color:red}',
                "site/images/a.png": b"image-bytes",
            },
        )
        css = data_body(Elements(output).tags[0][1]["href"]).decode()
        imported = css.split('"', 2)[1]
        self.assertIn('url("data:text/css,")', data_body(imported).decode())
        self.assertIn(base64.b64encode(b"image-bytes").decode(), css)
        self.assertEqual(len(reads), 3)

    def test_missing_external_and_escaping_references_remain_blocked_by_csp(self):
        source = (
            '<script src="https://example.test/a.js"></script>'
            '<script src="//example.test/a.js"></script>'
            '<script src="../../../outside.js"></script>'
            '<script src="/api/users"></script>'
            '<script src="../assets/a.css"></script>'
            '<link rel="stylesheet" href="missing.css">'
            '<img src="data:image/png;base64,aW1hZ2U=">'
        )
        output, reads = self.preview(source, {"site/assets/a.css": b"body{}"})
        self.assertEqual(output, source)
        self.assertEqual(reads, [])
        self.assertEqual(local_path("site/pages/a.html", "../%E5%9B%BE.png?v=1"), "site/图.png")
        self.assertIsNone(local_path("site/pages/a.html", "..%2f..%2f..%2fsecret.js"))
        self.assertIsNone(local_path("site/pages/a.html", "..%5csecret.js"))

    def test_script_source_cannot_break_out_of_its_tag(self):
        script = b'window.example="</script><img src=invalid>";'
        output, _ = self.preview(
            '<script src="../assets/a.js" integrity="old-hash"></script><p>after</p>',
            {"site/assets/a.js": script},
        )
        tags = Elements(output).tags
        self.assertEqual([tag for tag, _ in tags], ["script", "p"])
        self.assertEqual(data_body(tags[0][1]["src"]), script)
        self.assertNotIn("integrity", tags[0][1])

    def test_inline_css_uses_the_html_directory_and_preserves_unicode_offsets(self):
        source = (
            "<p>第一行\u2028继续</p>\r\n<style>.a{background:url(../images/a.png)}</style>"
            '<div style="background:url(../images/a.png)">正文</div>'
        )
        output, reads = self.preview(source, {"site/images/a.png": b"image-bytes"})
        self.assertTrue(output.startswith("<p>第一行\u2028继续</p>\r\n<style>"))
        self.assertEqual(output.count("data:image/png;base64,aW1hZ2UtYnl0ZXM="), 2)
        self.assertTrue(output.endswith(">正文</div>"))
        self.assertEqual(reads, ["site/images/a.png"])
