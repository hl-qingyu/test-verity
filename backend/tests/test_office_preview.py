import base64
import tempfile
import unittest
import zipfile
from datetime import datetime
from pathlib import Path

import openpyxl

from app.modules.documents.files import preview, validate_file


class OfficePreviewTests(unittest.TestCase):
    def test_xlsx_names_dates_formulas_merges_and_bounds(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "file"
            book = openpyxl.Workbook()
            sheet = book.active
            sheet.title = "中文需求"
            sheet["A1"] = "订单验收"
            sheet.merge_cells("A1:C1")
            sheet["A2"] = datetime(2026, 9, 12)
            sheet["A2"].number_format = "yyyy-mm-dd"
            sheet["B2"] = 0.25
            sheet["B2"].number_format = "0%"
            sheet["C2"] = 7
            sheet["C2"].number_format = "0000"
            sheet["D2"] = "=1+1"
            sheet["A201"] = "不在首屏"
            book.create_sheet("第二张空表")
            book.save(path)
            book.close()
            validate_file(path, "xlsx")
            result = preview(path, "xlsx")
            self.assertEqual(result["kind"], "workbook")
            self.assertEqual([s["name"] for s in result["sheets"]], ["中文需求", "第二张空表"])
            first = result["sheets"][0]
            self.assertEqual(first["merges"], [[0, 0, 1, 3]])
            self.assertTrue(first["rows"][1][0].startswith("2026-09-12"))
            self.assertEqual(first["rows"][1][1:3], ["25%", "0007"])
            self.assertIn("未重新计算", first["rows"][1][3])
            self.assertEqual(len(first["rows"]), 200)
            self.assertTrue(result["truncated"])
            self.assertEqual(result["sheets"][1]["rows"], [])

    def test_legacy_xls_real_binary_and_corrupt_file(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "file"
            path.write_bytes(
                base64.b64decode(
                    (Path(__file__).parent / "fixtures/office-legacy-xls.b64").read_text()
                )
            )
            validate_file(path, "xls")
            result = preview(path, "xls")
            self.assertEqual(result["kind"], "workbook", result)
            self.assertEqual(result["sheets"][0]["name"], "旧版需求")
            self.assertEqual(result["sheets"][0]["rows"][1], ["扫码核销", "25%"])
            self.assertEqual(result["sheets"][0]["merges"], [[2, 0, 1, 2]])
            path.write_bytes(b"broken")
            self.assertEqual(preview(path, "xls")["kind"], "unsupported")

    def test_word_paragraph_table_merged_cells_and_unsafe_xml(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "file"
            body = """<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body>
            <w:p><w:pPr><w:pStyle w:val="Heading1"/></w:pPr><w:r><w:t>需求说明</w:t></w:r></w:p>
            <w:p><w:r><w:t>正文</w:t><w:br/><w:t>第二行</w:t></w:r></w:p>
            <w:tbl><w:tr><w:tc><w:tcPr><w:gridSpan w:val="2"/></w:tcPr>
            <w:p><w:r><w:t>合并表头</w:t></w:r></w:p></w:tc></w:tr>
            <w:tr><w:tc><w:p><w:r><w:t>字段</w:t></w:r></w:p></w:tc><w:tc><w:p><w:r><w:t>含义</w:t></w:r></w:p></w:tc></w:tr></w:tbl>
            </w:body></w:document>"""
            with zipfile.ZipFile(path, "w") as z:
                z.writestr("word/document.xml", body)
            result = preview(path, "docx")
            self.assertEqual(result["kind"], "word")
            self.assertEqual(result["blocks"][0]["kind"], "heading")
            self.assertEqual(result["blocks"][1]["text"], "正文\n第二行")
            self.assertEqual(result["blocks"][2]["rows"][0][0]["colspan"], 2)
            with zipfile.ZipFile(path, "w") as z:
                z.writestr("word/document.xml", '<!DOCTYPE x [<!ENTITY y "bad">]><x>&y;</x>')
            self.assertEqual(preview(path, "docx")["kind"], "unsupported")
