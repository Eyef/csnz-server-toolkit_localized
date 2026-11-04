# Contributing

## Development Environment

- Python 3.8+
- Windows (some features depend on Win32 APIs such as DPAPI)

```bash
pip install -r auth-server/requirements.txt
```

The management tool and launcher use **only the standard library** and need no extra dependencies.

## Code Style

- Chinese comments are acceptable; explain "why", not "what"
- For code that mirrors server rules, cite the source file in a comment
- Use full words for names instead of abbreviations

## Pre-commit Checks

### 1. Compile check

```bash
python -m compileall gm-tool auth-server launcher
```

### 2. Data safety

Changes that write to the database **must be tested on a copy**:

```python
import shutil, tempfile, pathlib
tmp = pathlib.Path(tempfile.mkdtemp())
shutil.copy2("UserDatabase.db3", tmp / "UserDatabase.db3")
# work on the copy
```

Never modify the real save data directly.

### 3. Rule provenance

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
