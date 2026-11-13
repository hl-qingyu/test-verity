"""Require Chinese table/column descriptions in every registered business model."""

import unittest

from app.db import models  # noqa: F401
from app.db.session import Base


class DatabaseCommentTests(unittest.TestCase):
    def test_every_table_and_column_has_chinese_comment(self) -> None:
        for table in Base.metadata.tables.values():
            with self.subTest(table=table.name):
                self.assertRegex(table.comment or "", r"[\u4e00-\u9fff]")
            for column in table.columns:
                with self.subTest(table=table.name, column=column.name):
                    self.assertRegex(column.comment or "", r"[\u4e00-\u9fff]")
