<div align="center">

# CSNZ Server Toolkit

**Server management tools for Counter-Strike Online / Nexon Zombies private servers**

Server management · account authentication — two components working together

[![Python](https://img.shields.io/badge/Python-3.8%2B-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![Platform](https://img.shields.io/badge/Platform-Windows-0078D4?logo=windows&logoColor=white)](#)
[![License](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![CSNZ Build](https://img.shields.io/badge/CSNZ%20Build-2728-blueviolet)](#)
[![Languages](https://img.shields.io/badge/Languages-EN%20%7C%20ZH-blue)](#-localization)

[Features](#-features) · [Quick start](#-quick-start) · [Architecture](#-architecture) · [Documentation](#-documentation) · [Known issues](#-known-issues)

</div>

---

## What is this?

A management toolkit for the **CSNZ (CSO / Nexon Zombies) server build 2728** that solves three practical administration problems:

- **Changing configuration means editing ten JSON/CSV files with different encodings** → graphical editing with automatic validation and backups
- **Sending items or changing points requires console commands and looking up item IDs manually** → full-text search across 3,743 items with one-click delivery
- **No way to manage player account security** → a dedicated authentication service with rate limiting and automatic brute-force IP bans

Every write rule is **reproduced from the server source code line by line** — these are not guessed field meanings.

## ✨ Features

### 🖥️ Server management tool (`gm-tool/`)

| Module | Capabilities |
|---|---|
| **Overview** | Server state, online player count, ban counters, live log |
| **User management** | Account list and search, ban status (including time remaining), points/EXP/level editing, GM rights, inventory viewer |
| **Item delivery** | Full-text search across 3,743 items (ID / internal name / localized name / category), marks items already owned, batch delivery |
| **Shop management** | Add/remove products, add/edit/remove tiers (quantity/days/price/bonus), recommended and popular slots |
| **Server configuration** | Port, welcome message, 34 metadata switches, authentication port, start/stop |
| **Ban management** | Account / IP / HWID channels with one-click triple ban |
| **Runtime and logs** | Start/stop the server, console commands, live logs, audit trail |
| **Security log** | Failed logins, rate limiting, credential-stuffing sources; one-click ban/unban |

### 🔐 Authentication service (`auth-server/`)

- Account registration / login verification / session kick
- **Brute-force rate limiting**: independent counters per IP and per account, cleared on success
- **Automatic banning**: IPs are blacklisted automatically after too many failures
- Event audit: login records and credential-stuffing source analysis

## 🚀 Quick start

### Requirements

- Windows 10/11
- Python 3.8+ (**no pip packages required** — standard library only)
- A CSNZ server (build 2728)

> The authentication service needs `fastapi` and `uvicorn`; see [auth-server/requirements.txt](auth-server/requirements.txt).

### Deployment

```bash
git clone https://github.com/Eyef/csnz-server-toolkit_lozalized.git
cd csnz-server-toolkit_lozalized
```

Place the three directories in the CSNZ server root (next to `CSNZ_Server.exe`):

```
CSNZ_server/
├── CSNZ_Server.exe
├── UserDatabase.db3
├── ServerConfig.json
├── Data/
├── gm-tool/          ← management tool
└── auth-server/      ← authentication service
```

### Start

1. Double-click `gm-tool/Start.bat`
2. On the **Server configuration** page, click **Start server**
3. The game server (30002) and the authentication service (38120) start together
4. Players connect their client launcher to `http://your-address:38120` to verify their account

> Before first use, change the `api_key` in all three configuration files to the same long random string.
> See [deployment docs](docs/deployment.md).

## 📦 Building a standalone exe

Both programs can be packaged with PyInstaller. The result matches the upstream
release (`CSNZ.GMTool.exe` only); the optional auth server exe removes the
Python requirement for the authentication service as well.

```powershell
python -m pip install -r requirements-build.txt
powershell -ExecutionPolicy Bypass -File build.ps1                      # GM tool only
powershell -ExecutionPolicy Bypass -File build.ps1 -WithAuthServer      # + auth server
```

Or double-click `build.bat` (add `-WithAuthServer` for both). The script runs
`scripts/selftest.py`, bundles the locale catalogs inside each executable, and
produces:

| File | Purpose |
|---|---|
| `dist/CSNZ.GMTool.exe` | Onefile, windowed; no Python needed on the target PC |
| `dist/config.json` | Template with `"server_root": "."` |
| `dist/AuthServer/CSNZ.AuthServer.exe` | Optional, `-WithAuthServer`; console onefile |
| `dist/AuthServer/config.json` | Auth service template (`server_root: ".."`) |
| `dist/SHA256.txt` | Checksums of the built executables |

Deploy by copying `CSNZ.GMTool.exe` and `config.json` into the CSNZ server root
(next to `CSNZ_Server.exe`). The exe reads and writes `config.json`, `logs/`,
`backups/`, and `item_aliases.json` next to itself; locale files are embedded,
so the language selector keeps working. If you place the exe in a subfolder,
set `server_root` accordingly.

If you built the auth server, copy the whole `AuthServer` folder next to
`CSNZ_Server.exe` as well. The GM tool finds it under either `AuthServer/` or
`auth-server/`, starts `CSNZ.AuthServer.exe` when present (no `server.py` or
Python installation required), and otherwise falls back to `python server.py`.
`-WithAuthServer` needs `fastapi` and `uvicorn`, installed automatically from
[auth-server/requirements.txt](auth-server/requirements.txt) unless `-NoInstall`
is passed.

## 🌐 Localization

The interface and all messages are localized. Language strings live in JSON files:

| Path | Contents |
|---|---|
| `gm-tool/locales/*.json` | Management tool UI, messages, and errors |
| `auth-server/locales/*.json` | Authentication service API messages |

English is the default language; Simplified Chinese is included. The language can be changed in `config.json`:

```json
{
  "language": "en"
}
```

or from the language selector in the management tool's top bar (the tool restarts to apply the change). The repository is ready for additional locales: copy `en.json` to `<language-tag>.json`, translate the values, and set `_name` to the language's display name — the file then appears in the selector.

## 🏗️ Architecture

```
┌─────────────────────────────────────────────┐
│  Player client launcher      Player PC      │
│  Register / login (calls the APIs below)    │
└──────────────────┬──────────────────────────┘
                   │ HTTPS + API key
┌──────────────────▼──────────────────────────┐
│  Authentication service       Cloud server  │
│  /register /login /kick /events             │
└──────────────────┬──────────────────────────┘
                   │ reads SQLite on the same host
┌──────────────────▼──────────────────────────┐
│  CSNZ server + UserDatabase.db3             │
│  ▲                                          │
│  │ stdin pipe / process supervision         │
│  ┌──────────────────────────────────┐       │
│  │  Management tool (gm-tool)       │       │
│  └──────────────────────────────────┘       │
└─────────────────────────────────────────────┘
```

**Why is the authentication service necessary?** Three hard facts make it unavoidable:

1. `UserDatabase.db3` is a local SQLite file that should not exist on player PCs.
2. The server's `LoginUser()` requires an established game socket; an external process cannot log in on behalf of a player.
3. The server exposes no HTTP / RPC management interface.

## 📚 Documentation

| Document | Contents |
|---|---|
| [Deployment guide](docs/deployment.md) | Cloud deployment, ports, HTTPS, security groups |
| [Data rules](docs/data-rules.md) | Timestamp units, item stacking, slot allocation, and other server rules |
| [Known issues](docs/known-issues.md) | Server defects and workarounds |

## ⚠️ Known issues

The following are **defects in the server itself**; the toolkit works around them:

| Issue | Impact | Workaround |
|---|---|---|
| `shopreload` does not clear the old list | Product count doubles (47→94→141→188) | Use `dbreload` instead |
| Passwords stored in plain text | Cannot hash them or game login breaks | HTTPS is mandatory |
| `IPBanList` has no expiry field | Automatic bans can only be permanent | Use a conservative threshold and unban manually |
| Listen address hard-coded to `0.0.0.0` | Cannot bind to a specific NIC | Only the port can be changed |

See [known-issues.md](docs/known-issues.md) for details.

## 🤝 Contributing

Issues and pull requests are welcome. Before submitting, please ensure that:

- New configuration write rules are backed by the server source code (include file and line number)
- Database write changes are tested on a copy, never on a real save

## 📄 License

[MIT](LICENSE)

## Disclaimer

This project is intended **only for private-server hosting and study/research**. It is not affiliated with the server's developers.
Do not use it for commercial purposes or to infringe on the rights of others.
