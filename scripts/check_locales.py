#!/usr/bin/env python3
"""Validate locale catalogs before release.

Every ``*.json`` in ``gm-tool/locales`` and ``auth-server/locales`` is
compared against the English reference (``en.json``) in the same folder:

* valid JSON, UTF-8 (a BOM is allowed), flat string -> string mapping
* no duplicate keys
* exactly the same key set as the reference
* exactly the same ``{placeholder}`` names as the reference
* a translation is empty only where the reference is empty
* a non-empty, unique ``"_name"`` for every non-English catalog

Exit code is 0 when everything is fine and 1 otherwise.

Usage:
    python scripts/check_locales.py
    python scripts/check_locales.py --root path/to/repo
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from string import Formatter

CATALOGS = ("gm-tool", "auth-server")
REFERENCE = "en"
NAME_KEY = "_name"
MAX_PRINTED = 10


def _safe_stdout() -> None:
    """Do not crash on consoles that cannot encode every language name."""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="replace")
        except (AttributeError, ValueError):
            pass


def _short(items: list[str]) -> str:
    shown = ", ".join(items[:MAX_PRINTED])
    if len(items) > MAX_PRINTED:
        shown += ", ... (+%d more)" % (len(items) - MAX_PRINTED)
    return shown


def _placeholders(text: str) -> list[str]:
    """Return ``{name}`` fields, ignoring escaped ``{{braces}}``."""
    return sorted({
        field for _, field, _, _ in Formatter().parse(text)
        if field is not None
    })


def load_catalog(path: Path) -> tuple[dict, list[str]]:
    """Load a catalog and report keys that appeared more than once."""
    duplicates: list[str] = []

    def hook(pairs):
        data = {}
        for key, value in pairs:
            if key in data and key not in duplicates:
                duplicates.append(key)
            data[key] = value
        return data

    text = path.read_text(encoding="utf-8-sig")
    return json.loads(text, object_pairs_hook=hook), duplicates


def check_catalog(path: Path, reference: dict) -> list[str]:
    """Return a list of human-readable problems for one catalog file."""
    errors: list[str] = []
    try:
        data, duplicates = load_catalog(path)
    except (OSError, ValueError) as exc:
        return ["cannot read JSON: %s" % exc]

    if not isinstance(data, dict):
        return ["top level must be a JSON object"]

    for key in duplicates:
        errors.append("duplicate key: %s" % key)

    strings = {}
    for key, value in data.items():
        if isinstance(value, str):
            strings[key] = value
        else:
            errors.append("%s: value must be a string" % key)

    if path.stem != REFERENCE:
        name = strings.get(NAME_KEY, "")
        if not name.strip():
            errors.append('missing or empty "%s"' % NAME_KEY)

    for key, value in strings.items():
        if key == NAME_KEY:
            continue
        try:
            list(Formatter().parse(value))
        except ValueError as exc:
            errors.append("%s: malformed braces (%s)" % (key, exc))

    reference_keys = set(reference) - {NAME_KEY}
    reference_strings = {
        key: value for key, value in reference.items()
        if key != NAME_KEY and isinstance(value, str)
    }
    # Key presence is judged on every key, even when its value has the wrong
    # type; otherwise one bad value would also be reported as a missing key.
    keys = set(data) - {NAME_KEY}
    missing = sorted(reference_keys - keys)
    extra = sorted(keys - reference_keys)
    if missing:
        errors.append("missing keys: %s" % _short(missing))
    if extra:
        errors.append("extra keys: %s" % _short(extra))

    for key in sorted(set(reference_strings) & set(strings)):
        expected_text = reference_strings[key]
        actual_text = strings[key]
        if expected_text.strip() and not actual_text.strip():
            errors.append("%s: empty translation" % key)
        elif actual_text.strip() and not expected_text.strip():
            errors.append("%s: must be empty like the reference" % key)
        try:
            expected = _placeholders(expected_text)
            actual = _placeholders(actual_text)
        except ValueError:
            continue  # malformed braces are already reported above
        if expected != actual:
            errors.append(
                "%s: placeholders expected {%s}, got {%s}"
                % (key, ", ".join(expected), ", ".join(actual))
            )

    return errors


def check_directory(directory: Path) -> int:
    """Check one locales folder; return the number of errors found."""
    reference_path = directory / ("%s.json" % REFERENCE)
    if not reference_path.exists():
        print("  ERROR: reference %s is missing" % reference_path.name)
        return 1

    try:
        reference, _ = load_catalog(reference_path)
    except (OSError, ValueError) as exc:
        print("  ERROR: cannot read %s: %s" % (reference_path.name, exc))
        return 1
    if not isinstance(reference, dict):
        print("  ERROR: %s must be a JSON object" % reference_path.name)
        return 1

    total = 0
    errors = check_catalog(reference_path, reference)
    if errors:
        total += len(errors)
        print("  %-16s FAIL" % reference_path.name)
        for error in errors:
            print("    %s" % error)
    else:
        print("  %-16s OK (%d keys)"
              % (reference_path.name, len(reference) - 1))

    display_names: dict[str, list[str]] = {}
    for path in sorted(directory.glob("*.json")):
        if path.name == reference_path.name:
            continue
        errors = check_catalog(path, reference)
        if errors:
            total += len(errors)
            print("  %-16s FAIL" % path.name)
            for error in errors:
                print("    %s" % error)
            continue

        data, _ = load_catalog(path)
        print("  %-16s OK (%d keys)" % (path.name, len(data) - 1))
        name = data.get(NAME_KEY, "")
        if isinstance(name, str) and name:
            display_names.setdefault(name, []).append(path.name)

    for name, files in sorted(display_names.items()):
        if len(files) > 1:
            print('    duplicate "%s" "%s": %s'
                  % (NAME_KEY, name, ", ".join(files)))
            total += 1

    return total


def main(argv: list[str] | None = None) -> int:
    _safe_stdout()
    parser = argparse.ArgumentParser(
        description="Validate locale catalogs against the English reference."
    )
    parser.add_argument(
        "--root",
        default=Path(__file__).resolve().parent.parent,
        type=Path,
        help="repository root (defaults to the parent of scripts/)",
    )
    args = parser.parse_args(argv)

    root = args.root.resolve()
    errors = 0
    for catalog in CATALOGS:
        directory = root / catalog / "locales"
        print("\n%s/locales" % catalog)
        if not directory.is_dir():
            print("  ERROR: directory not found")
            errors += 1
            continue
        errors += check_directory(directory)

    print()
    if errors:
        print("FAILED: %d problem(s) found" % errors)
        return 1
    print("OK: all locale catalogs are consistent")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
