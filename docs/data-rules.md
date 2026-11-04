# Data Rules

Every rule below is **copied from the server source code**. Violating any of them while editing the database can corrupt data.

## Timestamps

**The unit is minutes, not seconds.**

```cpp
time_t CServerInstance::GetCurrentTime() {
    return m_CurrentTime;  // timestamp in minutes
}
```

`29876183` corresponds to 2026-10-21 08:23 UTC. One day = 1440.

## Item Delivery

Copied from `CItemManager::AddItem` and `CUserDatabaseSQLite::AddInventoryItem`:

| Rule | Description |
|---|---|
| Permanent item | `status=1, inUse=1, expiryDate=0` |
| Timed item | `expiryDate = now + days × 1440` |
| Stackability | `Category==9` and `UseType∈{0,1,2}`, or `Category==8` and `UseType∈{0,2}` |
| Stackable handling | Add to `count` for the same itemID; do not create a new row |
| Slot allocation | Reuse an empty row with `itemID=0` first; otherwise use `nextInventorySlot` and increment it |
| Clearing an item | Write back an empty row with `itemID=0`; **do not DELETE** |
| Password box (166) | Does not occupy a slot; adds to `UserCharacter.passwordBoxes` |
| Inventory limit | A valid item count ≥ `InventorySlotMax` (default 4000) means full |

> **Never compute `max(slot)+1` yourself** — it conflicts with the `nextInventorySlot` cursor.

## Costumes

Items with `Category==12` or `ClassName=="Tattoo"` are only **owned** when added to the inventory.
Wearing them requires writing `UserCostumeLoadout` (or `UserZBCostumeLoadout`) separately.

## Account Registration

Validation in `RegisterUser`:

- Username: 5–15 characters, Latin letters + digits only
- Password: 5–15 characters, cannot be all digits

`Register` writes only the `User` table and **does not create a character**. This is intentional — the server's `LoginUser` has a branch:

```cpp
if (!newUser->IsCharacterExists())
    g_PacketManager.SendCharacter(socket);   // show character creation
else
    SendLoginPacket(newUser, character);     // go straight to the lobby
```

A new account sees the character creation screen once on first login, then goes straight to the lobby.

`userID` comes from the `UserDist.userIDNext` counter; do not use `MAX(userID)+1`.

## Bans

| Channel | Table | Granularity |
|---|---|---|
| Account | `UserBan` | `term` is the expiry timestamp in minutes |
| IP | `IPBanList` | Only an ip column; **permanent** |
| HWID | `HWIDBanList` | Only an hwid column; **permanent** |

`UserBan.term=0` means permanent. The server runs every minute:

```sql
DELETE FROM UserBan WHERE term <= now
```

**Check whether `term` has expired when evaluating a ban**, not just `type != 0` — while the server is not running, expired rows remain in the database and can cause false positives.

## Online Status

`UserSession` is authoritative: a row is `INSERT`ed on login and removed by `DropSession` on logout.
The row count is the current number of online sessions.

## Shop

| Rule | Description |
|---|---|
| `Version` | Must be `1`, otherwise `dbreload` shuts the server down |
| Tier IDs | Assigned sequentially by JSON order at load time; reload after changes |
| One item per tier | A tier can sell only one item; use `ItemRewards` for bundles |
| Field widths | `duration` Int16 / `count` UInt16 / `price` UInt32 / `adType` UInt8 |

Out-of-range values are **silently truncated** (70000 displays as 4464 on the client); the tool blocks them.
