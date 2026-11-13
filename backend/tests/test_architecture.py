"""Executable dependency rules for the modular monolith; no database or network."""

import ast
import unittest
from pathlib import Path


class ArchitectureTests(unittest.TestCase):
    def test_layer_boundaries_and_no_import_cycles(self) -> None:
        root = Path(__file__).resolve().parents[1] / "app"
        files = {
            "app." + ".".join(p.relative_to(root).with_suffix("").parts): p
            for p in root.rglob("*.py")
        }
        graph: dict[str, set[str]] = {}
        for module, path in files.items():
            dependencies = set()
            for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
                if isinstance(node, ast.Import):
                    dependencies.update(alias.name for alias in node.names)
                elif isinstance(node, ast.ImportFrom):
                    self.assertEqual(node.level, 0, f"Use explicit layer imports: {path}")
                    dependencies.add(node.module or "")
                    dependencies.update(f"{node.module}.{alias.name}" for alias in node.names)
            if path.name in ("service.py", "schemas.py") or any(
                module.startswith(f"app.{layer}.")
                for layer in ("core", "db", "security", "integrations")
            ):
                self.assertFalse(
                    any(
                        d.startswith(("fastapi", "starlette", "app.api")) or d.endswith(".router")
                        for d in dependencies
                    ),
                    module,
                )
            if module.startswith("app.core."):
                self.assertFalse(
                    any(
                        d.startswith("app.") and not d.startswith("app.core.") for d in dependencies
                    ),
                    module,
                )
            if module.startswith(("app.db.", "app.security.", "app.integrations.")):
                self.assertFalse(any(d.startswith("app.modules.") for d in dependencies), module)
            if module.startswith("app.integrations."):
                self.assertFalse(
                    any(d.startswith(("sqlalchemy", "app.db.")) for d in dependencies), module
                )
            if path.name == "router.py" and module.startswith("app.modules."):
                self.assertFalse(
                    any(
                        d.startswith(("sqlalchemy", "urllib", "app.integrations."))
                        for d in dependencies
                    ),
                    module,
                )
            graph[module] = {d for d in dependencies if d in files}

        visited, active = set(), set()

        def visit(module: str) -> None:
            self.assertNotIn(module, active, f"Import cycle: {module}")
            if module in visited:
                return
            active.add(module)
            for dependency in graph[module]:
                visit(dependency)
            active.remove(module)
            visited.add(module)

        for module in graph:
            visit(module)
