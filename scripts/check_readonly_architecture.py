"""Reject accidental writer reachability from public read-only entry points.

This is a static CI boundary, not an execution sandbox.  It keeps collectors
from importing the completed pilot/funding writers or introducing POST/DELETE
calls as a convenience change.
"""
from __future__ import annotations

import ast
import subprocess
import sys
from pathlib import Path

READ_ONLY_ENTRYPOINTS = (
    "main.py",
    "observe_30m.py",
    "collect_shadow.py",
    "collect_mlb_microstructure.py",
    "weather_forward.py",
    "scan_mlb_f3_partitions.py",
)
FORBIDDEN_MODULES = {"pilot_live", "fund_pilot", "core.pilot_venue", "core.pilot_retirement"}
FORBIDDEN_CALLS = {"post", "delete", "submit_ioc", "cancel_owned_resting", "once_post"}


def tracked_modules(root: Path) -> dict[str, Path]:
    result = {}
    names = subprocess.check_output(["git", "ls-files", "*.py"], cwd=root, text=True).splitlines()
    for name in names:
        if name.startswith("tests/"):
            continue
        path = root / name
        parts = Path(name).with_suffix("").parts
        if parts[-1] == "__init__":
            parts = parts[:-1]
        if parts:
            result[".".join(parts)] = path
    return result


def import_names(tree: ast.AST) -> set[str]:
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
    return names


def module_for_path(root: Path, path: Path) -> str:
    parts = path.relative_to(root).with_suffix("").parts
    return ".".join(parts[:-1] if parts[-1] == "__init__" else parts)


def direct_violations(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    problems = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            imported = [alias.name for alias in node.names] if isinstance(node, ast.Import) else [node.module]
            for name in imported:
                if name in FORBIDDEN_MODULES:
                    problems.append(f"forbidden writer import {name}")
        if isinstance(node, ast.Call):
            func = node.func
            name = func.id if isinstance(func, ast.Name) else func.attr if isinstance(func, ast.Attribute) else None
            if name in FORBIDDEN_CALLS:
                problems.append(f"forbidden write-like call {name}()")
    return problems


def check(root: Path | None = None) -> list[str]:
    root = root or Path(__file__).resolve().parents[1]
    modules = tracked_modules(root)
    problems = []
    for entry in READ_ONLY_ENTRYPOINTS:
        path = root / entry
        if not path.exists():
            problems.append(f"missing read-only entry point: {entry}")
            continue
        pending = [module_for_path(root, path)]
        visited = set()
        while pending:
            module = pending.pop()
            if module in visited:
                continue
            visited.add(module)
            if module in FORBIDDEN_MODULES:
                problems.append(f"{entry} reaches forbidden writer module {module}")
                continue
            source = modules.get(module)
            if source is None:
                continue
            for problem in direct_violations(source):
                problems.append(f"{entry}: {source.relative_to(root)}: {problem}")
            tree = ast.parse(source.read_text(encoding="utf-8"), filename=str(source))
            for imported in import_names(tree):
                if imported in modules:
                    pending.append(imported)
    return sorted(set(problems))


def main() -> int:
    problems = check()
    if problems:
        print("\n".join(problems), file=sys.stderr)
        return 1
    print(f"Read-only architecture verified for {len(READ_ONLY_ENTRYPOINTS)} entry points")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
