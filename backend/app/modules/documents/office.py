"""Local, non-executing Office previews with bounded output."""

import io
import re
import zipfile
from contextlib import ExitStack
from datetime import date, datetime, time
from pathlib import Path
from xml.etree import ElementTree

import openpyxl
import xlrd
from openpyxl.utils.cell import (
    column_index_from_string,
    coordinate_from_string,
    get_column_letter,
    range_boundaries,
)

from app.core.errors import AppError

MAX_ROWS, MAX_COLUMNS, MAX_SHEETS = 200, 50, 20
W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


def xml(data: bytes) -> ElementTree.Element:
    declarations = data.replace(b"\x00", b"").upper()
    if b"<!DOCTYPE" in declarations or b"<!ENTITY" in declarations:
        raise ValueError("unsafe XML")
    return ElementTree.fromstring(data)


def archive(path: Path) -> zipfile.ZipFile:
    z = zipfile.ZipFile(path)
    if len(z.infolist()) > 3000 or sum(f.file_size for f in z.infolist()) > 50 * 1024 * 1024:
        z.close()
        raise AppError(422, "document_expansion_limit")
    return z


def worksheet_shape(root: ElementTree.Element) -> tuple[int, int]:
    """Use actual cell coordinates; some exporters write dimension=A1 for a full sheet."""
    ns = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
    data = root.find(ns + "sheetData")
    max_row = max_column = last_row = 0
    if data is None:
        return 0, 0
    for row in data.findall(ns + "row"):
        last_row = int(row.get("r", str(last_row + 1)))
        if not 1 <= last_row <= 1048576:
            raise ValueError("invalid worksheet row")
        max_row = max(max_row, last_row)
        column = 0
        for cell in row.findall(ns + "c"):
            column = (
                column_index_from_string(coordinate_from_string(cell.get("r"))[0])
                if cell.get("r")
                else column + 1
            )
            if column > 16384:
                raise ValueError("invalid worksheet column")
            max_column = max(max_column, column)
    return max_row, max_column


def paragraph_text(node: ElementTree.Element) -> str:
    result = []
    for element in node.iter():
        if element.tag == W + "t":
            result.append(element.text or "")
        elif element.tag == W + "tab":
            result.append("\t")
        elif element.tag in (W + "br", W + "cr"):
            result.append("\n")
    return "".join(result)


def word_preview(path: Path) -> dict:
    blocks, plain = [], []
    truncated, length = False, 0
    with archive(path) as z:
        root = xml(z.read("word/document.xml"))
        body = root.find(W + "body")
        if body is None:
            raise ValueError("missing body")
        for node in body:
            if len(blocks) >= 500 or length >= 100000:
                truncated = True
                break
            if node.tag == W + "p":
                full_text = paragraph_text(node)
                text = full_text[: 100000 - length]
                truncated |= len(text) < len(full_text)
                style = node.find(W + "pPr/" + W + "pStyle")
                style_name = style.get(W + "val", "") if style is not None else ""
                heading = re.search(r"(?:heading|标题)([1-6])", style_name, re.I)
                block = {
                    "kind": "heading" if heading else "paragraph",
                    "text": text,
                    "level": int(heading[1]) if heading else 0,
                }
                if node.find(W + "pPr/" + W + "numPr") is not None:
                    block["text"] = "• " + text
                blocks.append(block)
                plain.append(text)
                length += len(text)
            elif node.tag == W + "tbl":
                rows, active = [], {}
                for row_index, row in enumerate(node.findall(W + "tr")):
                    if row_index >= MAX_ROWS or length >= 100000:
                        truncated = True
                        break
                    cells, next_active, column = [], {}, 0
                    for cell_node in row.findall(W + "tc"):
                        if column >= MAX_COLUMNS or length >= 100000:
                            truncated = True
                            break
                        span = cell_node.find(W + "tcPr/" + W + "gridSpan")
                        colspan = (
                            min(MAX_COLUMNS - column, max(1, int(span.get(W + "val", "1"))))
                            if span is not None
                            else 1
                        )
                        full_text = "\n".join(paragraph_text(p) for p in cell_node.iter(W + "p"))
                        text = full_text[: min(4000, 100000 - length)]
                        truncated |= len(text) < len(full_text)
                        length += len(text)
                        plain.append(text)
                        merge = cell_node.find(W + "tcPr/" + W + "vMerge")
                        continuing = merge is not None and merge.get(W + "val") != "restart"
                        if continuing and column in active:
                            previous = active[column]
                            previous["rowspan"] += 1
                            next_active[column] = previous
                        else:
                            cell = {"text": text, "colspan": colspan, "rowspan": 1}
                            cells.append(cell)
                            if merge is not None:
                                next_active[column] = cell
                        column += colspan
                    active = next_active
                    rows.append(cells)
                blocks.append({"kind": "table", "rows": rows})
    return {"kind": "word", "text": "\n".join(plain), "blocks": blocks, "truncated": truncated}


def display_value(value: object, number_format: str = "") -> str:
    if value is None:
        return ""
    if isinstance(value, datetime | date | time):
        return value.isoformat(sep=" ") if isinstance(value, datetime) else value.isoformat()
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, int | float):
        if re.fullmatch(r"0(?:\.0+)?%", number_format):
            decimals = len(number_format.split(".")[1].rstrip("%")) if "." in number_format else 0
            return f"{value * 100:.{decimals}f}%"
        if re.fullmatch(r"0{2,}", number_format) and int(value) == value:
            return str(int(value)).zfill(len(number_format))
        if isinstance(value, float) and value.is_integer():
            return str(int(value))
    return str(value)


def excel_preview(path: Path, extension: str) -> dict:
    sheets, plain = [], []
    length, truncated = 0, False

    def append_sheet(
        name: str, total_rows: int, total_columns: int, values: list[list[str]], merges: list
    ) -> None:
        nonlocal length, truncated
        rows = []
        cut = total_rows > MAX_ROWS or total_columns > MAX_COLUMNS
        for row_index, row in enumerate(values):
            if length >= 100000:
                cut = True
                break
            cells = []
            for column, value in enumerate(row):
                cell = value[: min(4000, max(0, 100000 - length))]
                cut |= len(cell) < len(value)
                length += len(cell)
                cells.append(cell)
                if cell:
                    plain.append(f"{get_column_letter(column + 1)}{row_index + 1}: {cell}")
            rows.append(cells)
        sheets.append(
            {
                "name": name,
                "rows": rows,
                "merges": merges,
                "total_rows": total_rows,
                "total_columns": total_columns,
                "truncated": cut,
            }
        )
        truncated |= cut

    if extension == "xlsx":
        with archive(path) as z, ExitStack() as stack:
            # Reject DTD/entities in every XML part before third-party readers see it.
            for entry in z.infolist():
                if entry.filename.endswith((".xml", ".rels")):
                    xml(z.read(entry))
            values_book = openpyxl.load_workbook(
                stack.enter_context(path.open("rb")),
                read_only=True,
                data_only=True,
                keep_links=False,
            )
            formulas_book = openpyxl.load_workbook(
                stack.enter_context(path.open("rb")),
                read_only=True,
                data_only=False,
                keep_links=False,
            )
            stack.callback(values_book.close)
            stack.callback(formulas_book.close)
            truncated = len(values_book.worksheets) > MAX_SHEETS
            for sheet, formulas in zip(
                values_book.worksheets[:MAX_SHEETS],
                formulas_book.worksheets[:MAX_SHEETS],
                strict=True,
            ):
                if length >= 100000:
                    truncated = True
                    break
                merge_root = xml(z.read(sheet._worksheet_path))
                total_rows, total_columns = worksheet_shape(merge_root)
                sheet.reset_dimensions()
                formulas.reset_dimensions()
                nr, nc = min(total_rows, MAX_ROWS), min(total_columns, MAX_COLUMNS)
                rows = []
                if nr and nc:
                    for cells, formula_cells in zip(
                        sheet.iter_rows(max_row=nr, max_col=nc),
                        formulas.iter_rows(max_row=nr, max_col=nc),
                        strict=True,
                    ):
                        row = []
                        for cell, formula in zip(cells, formula_cells, strict=True):
                            value = display_value(cell.value, cell.number_format or "")
                            if formula.data_type == "f":
                                value += f"（公式：{formula.value}；未重新计算）"
                            row.append(value)
                        rows.append(row)
                # Read merge ranges without expanding cells.
                merges = []
                for merge in merge_root.iter(
                    "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}mergeCell"
                ):
                    c1, r1, c2, r2 = range_boundaries(merge.get("ref", ""))
                    if r1 <= nr and c1 <= nc:
                        merges.append([r1 - 1, c1 - 1, min(r2, nr) - r1 + 1, min(c2, nc) - c1 + 1])
                append_sheet(sheet.title, total_rows, total_columns, rows, merges)
    else:
        if path.stat().st_size > 50 * 1024 * 1024:
            raise AppError(422, "document_expansion_limit")
        book = xlrd.open_workbook(
            str(path), on_demand=True, formatting_info=True, logfile=io.StringIO()
        )
        try:
            truncated = book.nsheets > MAX_SHEETS
            for index in range(min(book.nsheets, MAX_SHEETS)):
                if length >= 100000:
                    truncated = True
                    break
                sheet = book.sheet_by_index(index)
                nr, nc = min(sheet.nrows, MAX_ROWS), min(sheet.ncols, MAX_COLUMNS)
                rows = []
                for r in range(nr):
                    row = []
                    for c in range(nc):
                        cell = sheet.cell(r, c)
                        value = cell.value
                        if cell.ctype == xlrd.XL_CELL_DATE:
                            value = xlrd.xldate_as_datetime(value, book.datemode)
                        elif cell.ctype == xlrd.XL_CELL_BOOLEAN:
                            value = bool(value)
                        elif cell.ctype == xlrd.XL_CELL_ERROR:
                            value = xlrd.error_text_from_code.get(value, "单元格错误")
                        fmt = book.format_map[book.xf_list[cell.xf_index].format_key].format_str
                        row.append(display_value(value, fmt))
                    rows.append(row)
                merges = [
                    [r1, c1, min(r2, nr) - r1, min(c2, nc) - c1]
                    for r1, r2, c1, c2 in sheet.merged_cells
                    if r1 < nr and c1 < nc
                ]
                append_sheet(sheet.name, sheet.nrows, sheet.ncols, rows, merges)
                book.unload_sheet(index)
        finally:
            book.release_resources()
    return {"kind": "workbook", "text": "\n".join(plain), "sheets": sheets, "truncated": truncated}


def preview_office(path: Path, extension: str) -> dict:
    try:
        return word_preview(path) if extension == "docx" else excel_preview(path, extension)
    except (
        ValueError,
        OverflowError,
        KeyError,
        IndexError,
        TypeError,
        AttributeError,
        RuntimeError,
        zipfile.BadZipFile,
        ElementTree.ParseError,
        xlrd.XLRDError,
        AppError,
    ):
        return {
            "kind": "unsupported",
            "text": "此文件无法安全预览，可能已加密、损坏或超出预览范围。原件已保留，请下载查看。",
        }
