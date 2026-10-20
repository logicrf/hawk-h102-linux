#!/usr/bin/env python3
"""Copyright (C) LogicRF Technologies (Chengdu) Co., Ltd. All Rights Reserved.

@file       check_distribution.py
@brief      Verify the English H102 integration source package without device access.
@details    Check exact regular-file membership, SHA-256, text language, Python syntax,
            local import closure and Markdown links. External SDK/image inputs remain
            separate and are never downloaded, executed or treated as qualified here.
@author     LogicRF Technologies
@architect  LogicRF
@email      info@logicrf.com
@website    https://www.logicrf.com
@version    1.0.0
@date       2026-10-20
"""
from __future__ import annotations

import ast
import hashlib
import json
from pathlib import Path
import re
import sys
from urllib.parse import unquote

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = "SOURCE-FILES.json"
EXTERNAL_MODULES = {
    "numpy", "paramiko", "pytest", "h102_iio_demo", "runtime_archive",
    "iio_runtime_archive", "h102_runtime_usb_rx", "usb_runtime_candidate",
    "usb_rx_reuse_candidate",
}
"""Host libraries and matching installed SDK/GNU Radio helpers supplied separately.

The control-service installer pins native helpers before runtime import. Naming
them here documents source-package dependencies, never authorizes a device entry.
"""


def files() -> dict[str, Path]:
    """Return package files while ignoring only Git metadata and Python bytecode caches."""
    result = {}
    for path in ROOT.rglob("*"):
        relative = path.relative_to(ROOT)
        if any(part in {".git", "__pycache__", ".pytest_cache"} for part in relative.parts):
            continue
        if path.is_symlink():
            raise ValueError("SYMLINK_NOT_ALLOWED: " + str(relative))
        if path.is_file() and str(relative) != MANIFEST:
            result[str(relative)] = path
    return result


def verify() -> dict:
    """Validate local package integrity and report explicit external-input limitations.

    No subprocess, network, block-device or board operation is performed. A raised
    error fails the CLI instead of silently omitting a damaged source file.
    """
    expected = json.loads((ROOT / MANIFEST).read_text())["files"]
    actual = files()
    errors = []
    if set(actual) != set(expected):
        errors.append({"file_set": {"missing": sorted(set(expected) - set(actual)),
                                    "extra": sorted(set(actual) - set(expected))}})
    local_modules = {p.stem for p in (ROOT / "scripts").glob("*.py")}
    local_modules |= {p.stem for p in (ROOT / "control-api").glob("*.py")}
    local_modules |= {"h102_control", "h102_api", "managed_iq", "managed_session"}
    python_count = markdown_count = 0
    optional_imports = set()
    for name, path in sorted(actual.items()):
        raw = path.read_bytes()
        if hashlib.sha256(raw).hexdigest() != expected.get(name, {}).get("sha256"):
            errors.append({"hash": name})
        try:
            text = raw.decode("utf-8-sig")
        except UnicodeDecodeError:
            errors.append({"nontext": name})
            continue
        if re.search(r"[\u3400-\u9fff]", text):
            errors.append({"language": name})
        if name.endswith(".py"):
            python_count += 1
            try:
                tree = ast.parse(text, filename=name)
            except SyntaxError as error:
                errors.append({"syntax": name, "line": error.lineno})
                continue
            for node in ast.walk(tree):
                imports = []
                if isinstance(node, ast.Import):
                    imports = [entry.name for entry in node.names]
                elif isinstance(node, ast.ImportFrom) and not node.level and node.module:
                    imports = [node.module]
                for imported in imports:
                    top = imported.split(".")[0]
                    if top in sys.stdlib_module_names or top in local_modules:
                        continue
                    if top in EXTERNAL_MODULES:
                        optional_imports.add(top)
                    else:
                        errors.append({"unresolved_import": imported, "file": name})
        if name.endswith(".md"):
            markdown_count += 1
            for target in re.findall(r"\]\(([^)]+)\)", text):
                if target.startswith(("http:", "https:", "mailto:", "#")):
                    continue
                target = unquote(target.split("#")[0])
                if target and not (path.parent / target).exists():
                    errors.append({"broken_link": target, "file": name})
    return {"status": "FAIL" if errors else "PASS_SOURCE_PACKAGE_ONLY",
            "files": len(actual), "python_files": python_count,
            "markdown_files": markdown_count, "external_imports": sorted(optional_imports),
            "full_image_reconstruction": "NOT_RUN_EXTERNAL_PINNED_INPUTS_REQUIRED",
            "hardware": "NOT_RUN", "errors": errors}


def main() -> int:
    """Print a machine-readable result and return nonzero for invalid distribution input."""
    try:
        result = verify()
    except (OSError, ValueError) as error:
        result = {"status": "FAIL", "error": str(error)}
    print(json.dumps(result, indent=2))
    return 0 if result["status"] == "PASS_SOURCE_PACKAGE_ONLY" else 1


if __name__ == "__main__":
    raise SystemExit(main())

# End of file: check_distribution.py
# Architect : LogicRF
# Contact   : info@logicrf.com
# Website   : https://www.logicrf.com
