# CSNZ Authentication Service

Runs on a cloud server alongside the CSNZ game server. The launcher uses it to verify accounts; it reads `UserDatabase.db3` (a local SQLite file).

## Why this layer is required

Three hard facts:

1. `UserDatabase.db3` is a local SQLite file that players neither have nor should have.
2. The server's `LoginUser(IExtendedSocket*, ...)` requires an already established game socket; an external program cannot "log in on behalf of the player".
3. The server exposes no HTTP / RPC management interface.

Therefore, to verify an account, the launcher needs a middle layer that can read the database.

## Starting

> **Recommended**: do not start it manually. On the **Server configuration** page of the CSNZ Server Management Tool, click **Start server**, which also launches the authentication service. You can also click **Start auth** separately.
> The command-line method below is only for running it without the management tool.

```bat
pip install -r requirements.txt
python server.py
```

It listens on `0.0.0.0:38120` by default. The port can be changed on the **Server configuration** page of the management tool and is synchronized to the launcher automatically.

### Packaged executable

Building with `build.ps1 -WithAuthServer` produces `dist/AuthServer/CSNZ.AuthServer.exe` — a single file that needs no Python, `pip`, or `server.py` on the target machine. Copy the whole `AuthServer` folder next to `CSNZ_Server.exe`; the exe reads `config.json` and writes `auth.log` / `auth_events.db3` in that folder. The management tool detects the exe and starts it automatically.

> The bundled exe still needs `fastapi` and `uvicorn` at **build** time only: `pip install -r auth-server/requirements.txt`.

## API

All endpoints require an `X-Api-Key` header matching `api_key` in `config.json`.

| Method | Path | Description |
|---|---|---|
| GET | `/health` | Health check |
| POST | `/register` | Register. Body: `{username, password}` |
| POST | `/login` | Login verification. Body: `{username, password, kick_existing?}` |
| POST | `/kick` | Clear a stale session. Body: `{user_id}` |
| GET | `/status?user_id=1` | Query account status |
| GET | `/events` | Event list (filterable by kind / ip / username) |
| GET | `/events/ip-summary` | Failure counts aggregated by IP |
| GET | `/events/stats` | Statistics + current rate-limit snapshot |
| POST | `/rate-limit/reset` | Reset the rate limit for an IP / account |

`/login` returns `has_character`:

- `true` → the account has a character and enters the lobby directly
- `false` → new account; the character-creation screen appears on first entry

If the account is already online (`UserSession` has a row), the response is 409 with `can_kick: true`, and the launcher uses this to ask the player whether to kick the existing session.

## Account rules (reproduced from the server)

| Item | Rule | Source location |
|---|---|---|
| Account | 5–15 characters, Latin letters and digits only | `RegisterUser` |
| Password | 5–15 characters, not all digits | `RegisterUser` |
| Registrations per IP | Limited by `MaxRegistrationsPerIP` | `Register` |
| userID allocation | Incremented from `UserDist.userIDNext` | `Register` |

## Rate limiting and automatic banning

To prevent brute force, two dimensions are counted independently:

| Dimension | Description |
|---|---|
| IP | The same IP trying different accounts (typical credential stuffing) |
| Account | The same account tried from different IPs |

Default configuration (`rate_limit`): 5 failures in 10 minutes → locked for 10 minutes.
**A successful login clears the counters immediately**, so normal players are never locked out by their own typos.

### Automatic banning

When cumulative failures reach `auto_ban.threshold` (default 30), the IP is automatically written to `IPBanList`. The server rejects that IP at TCP connection establishment.

Two key design decisions:

1. **Use the cumulative count, not a single window.** A single window would be cleared when the cooldown ends, and an attacker could try 4 times every 10 minutes forever. The in-process cumulative value is not cleared and truly reflects "this IP keeps credential-stuffing".
2. **Attempts made while rate-limited also count toward the cumulative total.** Otherwise an attacker would stop being counted once rate-limited and automatic banning would never trigger. This was found in testing and fixed.

⚠ **Automatic bans are permanent; there is no automatic unban.** The reason is that the `IPBanList` table has only one column, `ip` (defined by the server, and columns cannot be added), so no expiry time can be stored. Therefore:

- The default threshold is 30, on the conservative side
- **For shared IPs such as internet cafes or campus networks, raise it above 100**, otherwise one attacker gets the whole shop banned
- A mistaken ban can be lifted by selecting the IP on the **Security log** page of the GM tool and clicking **Unban IP**

## Security notes

**Passwords are stored and compared in plain text.** The server SQL is:

```sql
SELECT userID FROM User WHERE userName = ? AND password = ?
```

`User.password` is `VARCHAR(32)`. Hashing it would **break the game client's built-in login**, so it cannot be changed. The only mitigations are:

1. **HTTPS is mandatory in production** (`use_https: true` + certificates), otherwise account names and passwords travel in plain text
2. Set `api_key` to a long random string
3. Do not expose the auth port directly; put it behind Nginx/Caddy and rate-limit it

## Deploying to a cloud server

```json
{
  "server_root": "..",
  "listen_host": "0.0.0.0",
  "listen_port": 38120,
  "api_key": "replace with a long random string",
  "use_https": true,
  "cert_file": "cert.pem",
  "key_file": "key.pem"
}
```

`server_root` points to the CSNZ server root (containing `UserDatabase.db3` and `ServerConfig.json`).

**Note**: the authentication service only reads account tables. Do not let it write `UserCharacter` / `UserInventory` — those are managed by the game server, and concurrent writes would conflict.

## Localization

API messages and audit event labels are loaded from JSON:

- `auth-server/locales/en.json` — English (default)
- `auth-server/locales/zh-CN.json` — Simplified Chinese

Select the language with `"language": "en"` (or `"zh-CN"`, etc.) in `auth-server/config.json`, then restart the service. The language is fixed per process; the service does not switch per request. To add a language, copy `en.json`, translate the values, save it under the corresponding language tag (for example `ru.json`, `tr.json`, `fr.json`, `de.json`, `it.json`, `es.json`, `pl.json`, `pt-BR.json`), and set `_name` to the language's display name. Missing keys fall back to English automatically.
