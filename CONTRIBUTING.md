# Contributing

## Development Environment

- Python 3.8+
- Windows (some features depend on Win32 APIs such as DPAPI)

```bash
pip install -r auth-server/requirements.txt
```

The management tool uses **only the standard library** and needs no extra dependencies.

## Code Style

- Chinese comments are acceptable; explain "why", not "what"
- For code that mirrors server rules, cite the source file in a comment
- Use full words for names instead of abbreviations

## Pre-commit Checks

### 1. Compile check

```bash
python -m compileall gm-tool auth-server scripts
```

### 2. Locale catalogs

Every user-facing string lives in `gm-tool/locales/*.json` or `auth-server/locales/*.json`. After changing a catalog, or when adding a language, run:

```bash
python scripts/check_locales.py
```

The script compares each file with `en.json` in the same folder and reports:

- invalid JSON, a non-object root, or non-string values
- duplicate keys
- missing or extra keys relative to `en.json`
- mismatched `{placeholder}` names
- an empty translation where the English reference is not empty (and the reverse)
- a missing, empty, or duplicated `_name`

To add a language, copy `en.json` to `<language-tag>.json`, translate only the values, and set `_name` to the language's own name (for example `"Русский"`). Keep the file stem exactly as it should appear in `config.json` (`ru`, not `ru-RU`); only `pt` → `pt-BR` is aliased currently. The management tool picks the file up automatically and shows it in the language selector; the auth service uses the `language` setting in its config file. Both require a restart.

CI runs the same check, so a broken catalog cannot reach `main`.

### 3. Data safety

Changes that write to the database **must be tested on a copy**:

```python
import shutil, tempfile, pathlib
tmp = pathlib.Path(tempfile.mkdtemp())
shutil.copy2("UserDatabase.db3", tmp / "UserDatabase.db3")
# work on the copy
```

Never modify the real save data directly.

### 4. Rule provenance

New configuration-writing rules must cite the server source, for example:

```python
# Mirrors CItemManager::AddItem:
# stackable items accumulate count for the same ID; no new row
if item.stackable and exists:
    ...
```

## Pull Request Requirements

- One PR does one thing
- Explain what changed, why, and how it was verified
- Include screenshots for UI changes

## Security

- Do not commit `config.json` (it contains secrets)
- Do not commit `UserDatabase.db3` (it contains player data)
- Do not commit `*.log` / `*.mdmp` (they may contain private data)
