# CSNZ Server Management Tool

A graphical administration console for the CSNZ server (server build 2728, private release).

## Starting

Place the whole `gm-tool` folder in the server root (next to `CSNZ_Server.exe`), then double-click `Start.bat`.

The tool location and language can be changed in `config.json`:

```json
{
  "server_root": "..",      // path relative to GM_Tool, or an absolute path
  "language": "en",         // "en" (default), "zh-CN", or any locale JSON file
  "lang_file": "",          // empty = auto-detect _unpack/resource/cso_chn.txt
  "auto_backup": true,      // back up before every database write
  "max_backups": 50         // number of backups to keep
}
```

Requirements: Python 3.8+, standard library only (tkinter / sqlite3 / csv); no pip packages are needed.

## Layout adaptation

All pages **do not scroll at the page level** — everything fits on one screen. Data tables themselves still scroll (1,639 inventory rows cannot fit on one screen; that is table-internal scrolling, not page scrolling).

The window size is calculated from the usable screen area (`ui/layout.py`):

| Screen | Window | Mode |
|---|---|---|
| 1920x1080 | 1789x949 | centered |
| 1366x768 | 1350x720 | maximized |
| 1920x1080 @150% scaling | 1264x672 | maximized |
| 2560x1440 | 2391x1280 | centered |

The window **remembers its last position and size** (stored in `window_geometry` in `config.json`). After changing monitors, resolution, or scaling, if the previous coordinates are off-screen or the size is too small, the window falls back to a size computed for the current screen, so it never "disappears".

The minimum window size is 1180x700. Tested in the 1024x700 – 2560x1400 range: all six pages fit without vertical overflow or clipped controls. Fields use multi-column grids (4 columns on the configuration page, 6 columns for metadata switches), and table columns stretch with the window.

## Features

| Page | Capabilities |
|---|---|
| Server configuration | Network (server port / client IP and port), start/stop and automatic restart, HostName/welcome message, plus 34 metadata switches |
| User management | Account list and search, points/EXP/level editing, GM rights, inventory viewing and slot clearing |
| Item delivery | Search all 3,743 items (ID / internal name / localized name / alias / category), mark items already owned, batch delivery, custom localized names |
| Shop management | Add/remove products, currency switching, **add/edit/remove tiers (quantity/days/price/bonus/badge)**, recommended/popular slots, validation and backup, hot reload |
| Ban management | Three channels: account / IP / HWID; one-click triple ban and unban |
| Runtime and logs | Start/stop the server, console commands, live logs, audit trail |
| Security log | Failed logins, rate limiting, and credential-stuffing sources from the authentication service; one-click IP ban/unban |

## Networking: only one port

**The server and client use the same port.** From the source code `serverconfig.cpp`:

```cpp
tcpPort = udpPort = cfg.value("Port", DEFAULT_PORT);
```

`ServerConfig.json` has a single `Port`; TCP and UDP share it, both variables are always assigned the same value, and they cannot be configured separately. The client must connect to the same port, otherwise it cannot connect. The tool therefore asks for the port once and writes it to both `ServerConfig.json` and `launcher.ini`, guaranteeing they stay consistent.

| Item | Location | Editable |
|---|---|---|
| Port | `ServerConfig.json` `Port` + `launcher.ini` `port` | Yes, synchronized |
| Listen address | Hard-coded in the server | **No** |
| Client connection IP | `launcher.ini` `ip` | Yes, select a local NIC |

The listen address cannot be changed: `ServerInstance` calls `getaddrinfo(NULL, port, &hints, &result)` with `hints.ai_flags = AI_PASSIVE`; passing `NULL` is equivalent to binding `0.0.0.0`. `ServerConfig.json` has no IP / bind field at all (all keys were checked).

`launcher.ini` is read and written by the tool, preserving the original file's **UTF-8 BOM and CRLF** — the launcher reads it as ANSI, and losing the BOM would corrupt the Chinese comments.

## Process supervision (start / stop / auto-restart)

The configuration page provides **Start server**, **Stop server**, and **Force kill** buttons, plus process supervision.

**There are only two supervision rules**, no switch is needed; supervision becomes active as soon as the tool starts the server:

| Situation | Behavior |
|---|---|
| The server was not stopped with the button and goes down (crash / killed externally / OOM) | Automatically restarted after N seconds |
| Stopped via **Stop server** or **Force kill** | **Not restarted** |

The restart delay is adjustable in the UI (default 5 seconds).

**Why not use the server's built-in `RestartOnCrash`?**
That switch is really implemented (`crashdump.cpp`), but on a crash it calls `ForceEndServer()` and then launches a **brand-new detached process** with `ShellExecute`. The new process does not connect to this tool's command pipe, so the tool loses control of it — the symptom is "the tool says it is not running, but the port is occupied". In testing, the second instance crashes immediately with `bind failed: 10048`. Supervision is therefore handled by the tool; the new process always stays in the pipe and commands continue to work.

**Crash-loop protection**: based on "survival time", not "successful start". The server must stay up for 30 seconds to count as a normal start (the counter is reset, so occasional crashes can still be supervised); if it exits before 30 seconds, that is abnormal, and after 20 consecutive occurrences supervision stops and asks you to check `Logs` and `*.mdmp`. Otherwise a server that "starts and crashes after 2 seconds" would be relaunched forever and drag the machine down.

## Ban status detection

The user management page has a separate **Ban** column showing the type and time remaining:

| Display | Meaning |
|---|---|
| (empty) | Not banned |
| Ban · 7d left | Reason-visible ban, lifted automatically after 7 days |
| Silent · 2h left | Silent ban (client cannot see the reason) |
| Ban · permanent | term=0, permanent ban |

Expired bans do not count as bans. `UserBan.term` is an expiry minute timestamp; the server runs `DELETE FROM UserBan WHERE term <= now` every minute. If the server is not running, expired rows remain in the database, and a naive `type != 0` check would wrongly show already-unbanned players as banned.

The check is therefore centralized in the data layer (`Database._ban_active`); the user management page and the ban management page share the same logic.

The top bar's **banned only** filter shows all accounts with an active ban.

## Authentication service (required by the launcher)

The management tool hosts the authentication service process directly, so **there is no need for a separate cmd window**.

On the **Server configuration** page, in the **Network and runtime** section:

| Button | Purpose |
|---|---|
| Start auth | Launches AuthServer and returns only when the port is actually reachable |
| Stop auth | Terminate, kill on timeout, ensuring no process is left holding the port |
| Port + Apply port | Changes the auth port and synchronizes it to three configuration files |

Status display distinguishes two states (this matters):

- **Running · 127.0.0.1:38120** — the port is reachable and the launcher really works
- **Starting…** — the process is up but the port is not reachable yet; uvicorn initialization takes a few hundred milliseconds

Checking only "the process is alive" is not enough: uvicorn has a delay between start and being able to respond, and releasing too early makes the launcher fail intermittently.

### The authentication service is supervised too

If the authentication service goes down, **no player on the server can log in**, and it is more insidious than the game server going down — players only see "cannot connect to the login server", while the administrator may think the game server is fine. It must be supervised.

The rules are identical to the game server:

| Situation | Behavior |
|---|---|
| Auth process crashes / is killed / OOM | Automatically restarted after N seconds |
| **Stop auth** clicked | **Not restarted** |

Crash-loop protection is the same: staying up for 30 seconds counts as a normal start (counter reset); exiting before 30 seconds is abnormal, and after 20 consecutive occurrences supervision stops and asks you to check the logs.

The status display includes "(supervised)" so you can confirm supervision is active.

### Linked startup

When you click **Start server**, the authentication service is **started automatically** if it is not ready. The operator presses the button once; the game server (30002) and authentication (38120) come up together and the launcher is immediately usable.

### Changing the auth port

Enter the port directly in the auth row on the **Server configuration** page and click **Apply port**; the tool writes three files automatically:

| File | Field |
|---|---|
| `AuthServer/config.json` | `listen_port` |
| `Launcher/config.json` | `auth_base_url` |
| `GM_Tool/config.json` | `auth_base_url` |

**The launcher does not need manual edits** — that is the point of putting this in the tool.

The default port is **38120** (chosen because it is not in a common service range and does not conflict with system ports). Three checks are performed before changing it:

- Must be a number from 1 to 65535
- Must not equal the game server port (30002)
- Must not be occupied by another program

If the authentication service is running, the tool warns that a restart is required for the change to take effect.

On cloud servers, remember to open the new port in the security group, otherwise players cannot connect.

### Port source

The management tool does not store the auth port itself; it reads `listen_port` from `AuthServer/config.json` every time. This avoids the tool and the auth service each storing a copy and one change not being synchronized.

---

## Integration with the authentication service

The **Security log** page reads the auth service's `/events` and `/events/ip-summary`, completing the loop:

    spot an IP with an abnormal number of failures -> double-click for details -> one-click IP ban (writes IPBanList)
                                                      or reset the rate limit (player got locked by mistake)

Two fields must be set in `GM_Tool/config.json` (when unset, the page only shows a hint and other features are unaffected):

    {
      "auth_base_url": "http://your-server:8080",
      "auth_api_key": "the same key as the authentication service"
    }

## Online player count

The top-right corner of the main window permanently shows "online N / limit", refreshed every second.

The data source is the `UserSession` table, not `User.lastLogonTime`: the server `INSERT`s into `UserSession` on successful login and `DropSession` deletes the row on logout, so the row count is the number of sessions that are really online. No log parsing or restart is needed.

**Clicking the count** opens details: UID, account, nickname, IP, and online duration.

Note that `UserSession` only has rows after a player actually logs in; right after the server starts with nobody online it is 0. That is normal and does not mean the statistics are broken.

## Key design: write the DB offline, use commands online

The server holds `IUser` objects in memory; any online activity (leveling up, shopping, changing outfits) overwrites the database via `UpdateCharacter` with in-memory values. Therefore:

- **User offline** → the tool writes `UserDatabase.db3` directly
- **User online** → the tool sends GM console commands (`giveitem` / `givepoints` / `togglegamemaster`) and lets the server apply them, avoiding overwrites

Online/offline status is determined by whether the userID exists in `UserSession`.

## Shop tiers (sub-products)

A product can have multiple tiers, for example "1 item / 3 days / 100 points", "1 item / 10 days / 300 points", "1 item / 30 days / 800 points". Select a product on the **Shop management** page and the table below shows its tiers; they are directly editable:

| Field | Meaning | Valid range | Basis |
|---|---|---|---|
| Count | Items given per purchase | 1 – 65535 | `WriteUInt16` |
| Days | Duration, 0 = permanent | 0 – 32767 | `WriteInt16` |
| Price | Points or cash, according to product currency | 0 – 4294967295 | `WriteUInt32` |
| Bonus | Extra points returned after purchase | 0 – 4294967295 | `WriteUInt32` |
| Clan bonus | **Not used by the server** | 0 – 4294967295 | Parse/write-back only |
| Badge | Product badge marker | 0 – 255 | `WriteUInt8` |

Out-of-range values are **silently truncated** by the server (enter 70000 and the client may show 4464), so the tool rejects them before saving.

The "clan bonus" (`AdditionalClanPoints`) appears only three times in the whole server — definition, JSON parsing, JSON write-back — it is neither sent to the client nor used in `BuyProduct` settlement, so setting it has no effect.

Changing count/price does not change tier order and therefore does not shift client tier IDs; but **every save must be followed by a reload**, otherwise players still buy at the old price. The tool highlights unsaved/unreloaded state in red.

## Known server defects (worked around by the tool)

**`shopreload` doubles the product list.** `CommandShopReload` calls `g_ShopManager.Init()` directly, while the list-clearing `Shutdown()` is not called, so every execution appends the list to the old one:

```
initial      47 products
shopreload   94 products
shopreload   141 products
shopreload   188 products
dbreload     47 products   ← only it calls Shutdown before Init
```

The consequence is duplicate products in the client shop, shifted sub-product IDs, and players possibly buying the wrong thing.
**Use `dbreload` to reload the shop**; the button on this tool's shop page already uses dbreload.

## Data rules (reproduced from the server source; must be followed when editing the DB)

1. **Timestamp unit is minutes, not seconds** (the `GetCurrentTime()` comment says `timestamp in minutes`).
2. Permanent item: `status=1, inUse=1, expiryDate=0`; timed item: `expiryDate = now + days × 1440`.
3. Stackable items (`Category==9` and `UseType∈{0,1,2}`, or `Category==8` and `UseType∈{0,2}`) accumulate `count` for the same ID instead of creating a new row.
4. New items preferentially reuse an empty row with `itemID=0`; only when there is no empty slot use `nextInventorySlot` to insert and increment.
   **Do not compute `max(slot)+1` yourself** — it conflicts with the auto-increment cursor.
5. Clearing an item means writing the row back as an empty row with `itemID=0`, not DELETE.
6. `itemID=166` (password box) does not occupy an inventory slot; it accumulates `UserCharacter.passwordBoxes`.
7. Costumes (`Category==12` or `ClassName==Tattoo`) are only owned when stored; wearing them requires writing `UserCostumeLoadout`.
8. A player's inventory is considered full when the number of valid items ≥ `ServerConfig.InventorySlotMax` (default 4000).
9. A ban's `term` is an **expiry minute timestamp**; the server runs `DELETE FROM UserBan WHERE term <= now` every minute.

## Localized item names

The `Name` column in `Item.csv` contains English internal names. Localized names come from the client language pack `_unpack/resource/cso_chn.txt` (UTF-16LE + BOM, 51,059 tokens, key rule `CSO_<Name>`).
In testing only about 31% of items match, and generic class-name entries such as `CSO_Equipment="Equipment"` must be filtered out (otherwise every weapon would display as "Equipment").

For items without a localized name, you can enter a custom name on the right side of the **Item delivery** page; it is stored in the tool-side `item_aliases.json` and **does not modify `Item.csv`** (modifying it would affect the metadata sent to clients).

## Localization

All UI text and error messages are loaded from JSON locale files:

- `gm-tool/locales/en.json` — English (default)
- `gm-tool/locales/zh-CN.json` — Simplified Chinese

Choose the language in `config.json` (`"language": "en"` or `"zh-CN"`), or use the language selector in the top bar. The application restarts automatically after switching so every page is rebuilt in the new language. Adding another language is as simple as copying `en.json`, translating the values, naming the file with the language tag (for example `ru.json`, `tr.json`, `fr.json`, `de.json`, `it.json`, `es.json`, `pl.json`, `pt-BR.json`), and setting `_name` to the language's display name.
