import csv
import io
import struct
import zipfile
from contextlib import ExitStack
from pathlib import Path
from xml.etree import ElementTree

import openpyxl
import xlrd
from openpyxl.utils.cell import range_boundaries

from app.core.errors import AppError
from app.modules.documents.files import decode_text
from app.modules.documents.office import archive, display_value, worksheet_shape, xml

MAX_ROWS, MAX_COLUMNS, MAX_CHARS = 20000, 200, 5_000_000


def read_import(path: Path, extension: str) -> dict:
    """Bound parsing, not upload size. Fail rather than silently importing a prefix."""
    try:
        if path.stat().st_size > 50 * 1024 * 1024:
            raise AppError(422, "case_import_limit")
        sheets = []
        chars = 0

        def append(name, rows, formulas, merges):
            nonlocal chars
            if any("\x00" in value for row in rows for value in row):
                raise AppError(422, "case_import_invalid")
            if len(rows) > MAX_ROWS or any(len(row) > MAX_COLUMNS for row in rows):
                raise AppError(422, "case_import_limit")
            chars += sum(len(v) for row in rows for v in row)
            if chars > MAX_CHARS:
                raise AppError(422, "case_import_limit")
            sheets.append({"name": name, "rows": rows, "formulas": formulas, "merges": merges})

        if extension == "csv":
            raw = decode_text(path.read_bytes())
            sample = raw[:8000]
            try:
                dialect = csv.Sniffer().sniff(sample, delimiters=",;\t")
            except csv.Error:
                dialect = csv.excel
            rows = []
            for row in csv.reader(io.StringIO(raw, newline=""), dialect=dialect, strict=True):
                rows.append(row)
                if len(rows) > MAX_ROWS or len(row) > MAX_COLUMNS:
                    raise AppError(422, "case_import_limit")
            # Leading '=' in CSV is literal text, never executed; Excel formulas have typed cells.
            append("CSV", rows, [], [])
            return {
                "sheets": sheets,
                "encoding": "自动识别：UTF-8 / UTF-16 BOM / GB18030",
                "parser_version": 2,
            }
        if extension == "xlsx":
            with archive(path) as z, ExitStack() as stack:
                for item in z.infolist():
                    if item.filename.endswith((".xml", ".rels")):
                        xml(z.read(item))
                book = openpyxl.load_workbook(
                    stack.enter_context(path.open("rb")),
                    read_only=True,
                    data_only=False,
                    keep_links=False,
                )
                stack.callback(book.close)
                if len(book.worksheets) > 30:
                    raise AppError(422, "case_import_limit")
                for sheet in book:
                    sheet_root = xml(z.read(sheet._worksheet_path))
                    nr, nc = worksheet_shape(sheet_root)
                    sheet.reset_dimensions()
                    if nr > MAX_ROWS or nc > MAX_COLUMNS:
                        raise AppError(422, "case_import_limit")
                    rows, formulas = [], []
                    if nr and nc:
                        for ri, row in enumerate(sheet.iter_rows(max_row=nr, max_col=nc)):
                            values = []
                            for ci, cell in enumerate(row):
                                if cell.data_type == "f":
                                    formulas.append([ri, ci])
                                values.append(display_value(cell.value, cell.number_format or ""))
                            rows.append(values)
                    merges = []
                    for item in sheet_root.iter(
                        "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}mergeCell"
                    ):
                        c1, r1, c2, r2 = range_boundaries(item.get("ref", ""))
                        merges.append([r1 - 1, c1 - 1, r2, c2])
                    append(sheet.title, rows, formulas, merges)
        elif extension == "xls":
            book = xlrd.open_workbook(
                str(path), on_demand=True, formatting_info=True, logfile=io.StringIO()
            )
            try:
                if book.nsheets > 30:
                    raise AppError(422, "case_import_limit")
                for index in range(book.nsheets):
                    sheet = book.sheet_by_index(index)
                    if sheet.nrows > MAX_ROWS or sheet.ncols > MAX_COLUMNS:
                        raise AppError(422, "case_import_limit")
                    rows = []
                    for r in range(sheet.nrows):
                        values = []
                        for c in range(sheet.ncols):
                            cell = sheet.cell(r, c)
                            value = cell.value
                            if cell.ctype == xlrd.XL_CELL_DATE:
                                value = xlrd.xldate_as_datetime(value, book.datemode)
                            elif cell.ctype == xlrd.XL_CELL_BOOLEAN:
                                value = bool(value)
                            elif cell.ctype == xlrd.XL_CELL_ERROR:
                                value = xlrd.error_text_from_code.get(value, "单元格错误")
                            fmt = book.format_map[book.xf_list[cell.xf_index].format_key].format_str
                            values.append(display_value(value, fmt))
                        rows.append(values)
                    # xlrd returns formula caches. Inspect BIFF worksheet records so formulas
                    # cannot masquerade as ordinary values. Version is pinned in pyproject.
                    formulas = []
                    position = book._sh_abs_posn[index]
                    memory = book.mem
                    while position + 4 <= len(memory):
                        code, size = struct.unpack_from("<HH", memory, position)
                        position += 4
                        if position + size > len(memory):
                            raise ValueError("truncated BIFF")
                        if code in (0x0006, 0x0206, 0x0406) and size >= 4:
                            r, c = struct.unpack_from("<HH", memory, position)
                            formulas.append([r, c])
                        position += size
                        if code == 0x000A:
                            break
                    append(
                        sheet.name,
                        rows,
                        formulas,
                        [[r1, c1, r2, c2] for r1, r2, c1, c2 in sheet.merged_cells],
                    )
                    book.unload_sheet(index)
            finally:
                book.release_resources()
        else:
            raise AppError(422, "case_import_format")
        return {"sheets": sheets, "encoding": "Excel原文件编码", "parser_version": 2}
    except AppError:
        raise
    except (
        ValueError,
        KeyError,
        IndexError,
        TypeError,
        AttributeError,
        RuntimeError,
        OverflowError,
        csv.Error,
        struct.error,
        zipfile.BadZipFile,
        ElementTree.ParseError,
        xlrd.XLRDError,
    ) as exc:
        raise AppError(422, "case_import_invalid") from exc
