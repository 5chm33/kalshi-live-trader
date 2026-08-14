"""Regression tests proving V11 research code has no legacy execution dependency."""
from __future__ import annotations

import ast
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

from research.kalshi_readonly import ReadOnlyKalshiClient

ROOT = Path(__file__).resolve().parents[1]
RESEARCH = ROOT / "research"
FORBIDDEN_IMPORT_PREFIXES = ("core.kalshi_client", "core.api_interface")
FORBIDDEN_NAMES = {"place_order", "place_limit_order", "cancel_order", "amend_order", "execute_trade"}
FORBIDDEN_HTTP_METHODS = {"post", "put", "patch", "delete"}


class ResearchIsolationTests(unittest.TestCase):
    def test_research_source_has_no_legacy_execution_import_or_http_mutation(self) -> None:
        violations: list[str] = []
        for path in RESEARCH.glob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        if alias.name.startswith(FORBIDDEN_IMPORT_PREFIXES):
                            violations.append(f"{path.name}:{node.lineno}: import {alias.name}")
                elif isinstance(node, ast.ImportFrom):
                    module = node.module or ""
                    if module.startswith(FORBIDDEN_IMPORT_PREFIXES):
                        violations.append(f"{path.name}:{node.lineno}: from {module}")
                    for alias in node.names:
                        if alias.name in FORBIDDEN_NAMES:
                            violations.append(f"{path.name}:{node.lineno}: import {alias.name}")
                elif isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                    if node.func.attr in FORBIDDEN_HTTP_METHODS:
                        violations.append(f"{path.name}:{node.lineno}: .{node.func.attr}()")
                elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                    if node.func.id in FORBIDDEN_NAMES:
                        violations.append(f"{path.name}:{node.lineno}: {node.func.id}()")
        self.assertEqual([], violations, "\n".join(violations))

    def test_readonly_client_only_calls_session_get(self) -> None:
        # Build without __init__ so no key material is required; this exercises
        # the sole network method with all alternate HTTP verbs trapped.
        client = object.__new__(ReadOnlyKalshiClient)
        client.base_url = "https://example.invalid"
        client._last_request = 0.0
        client._min_interval = 0.0
        client._headers = Mock(return_value={})
        response = Mock()
        response.json.return_value = {"ok": True}
        response.raise_for_status.return_value = None
        session = Mock()
        session.get.return_value = response
        for method in FORBIDDEN_HTTP_METHODS:
            setattr(session, method, Mock(side_effect=AssertionError(f"unexpected HTTP {method.upper()}")))
        client.session = session
        self.assertEqual({"ok": True}, client.get("/markets"))
        session.get.assert_called_once()
        for method in FORBIDDEN_HTTP_METHODS:
            getattr(session, method).assert_not_called()


if __name__ == "__main__":
    unittest.main()
