# Known Issues

This page documents **defects in the server itself**, not problems in this tool.
The tool works around them, but keep them in mind if you modify the server or use third-party tools.

## 1. `shopreload` duplicates products ⚠️

`CommandShopReload` calls `g_ShopManager.Init()` directly, but `Shutdown()`, which clears the list, is never called:

```cpp
void CommandShopReload(...) {
    g_ShopManager.Init();   // m_Products.clear() lives in Shutdown(), which is not called
    ...
}
```

So each execution appends another copy to the old list. Measured behavior:

```
initial     47 products
shopreload  94 products
shopreload  141 products
shopreload  188 products
dbreload    47 products   ← only dbreload calls Shutdown before Init
```

**Consequence**: clients see duplicate products and shifted tier IDs, so players may buy the wrong item.

**Workaround**: use `dbreload` to reload the shop. The button on the tool's shop page already uses `dbreload`.

## 2. Passwords are stored in plaintext

`User.password` is `VARCHAR(32)`, compared in plaintext by SQL:

```sql
SELECT userID FROM User WHERE userName = ? AND password = ?
```

**Why it cannot be changed**: the game client's built-in login submits plaintext, so hashing would break it — and the client's automatic login feature is required.

**Workarounds**:

- **HTTPS is mandatory in production** (see the deployment guide)
- Store remembered passwords with DPAPI encryption so no plaintext touches disk
- Use a long random API key

## 3. `IPBanList` has no expiry column

The table has only an `ip` column, defined by the server. **Columns cannot be added** — doing so breaks server reads and writes.

Automatic bans are therefore permanent, with no automatic unban.

**Workarounds**:

- The default threshold is 30 attempts, which is conservative
- For shared IPs such as internet cafés or school networks, raise it above 100
- False positives can be removed manually on the **Security log** page

## 4. The listen address is hard-coded to `0.0.0.0`

```cpp
hints.ai_flags = AI_PASSIVE;
getaddrinfo(NULL, port.c_str(), &hints, &result);
```

Passing `NULL` binds all interfaces. `ServerConfig.json` has no IP / bind field.

**Workaround**: only the port can be changed, not the interface. To bind a specific IP, restrict it at the firewall level.

## 5. `stdout` is fully buffered

Once the server process's stdout is redirected to a pipe, it becomes fully buffered (4 KB) and is not flushed proactively, so logs stay stuck in the buffer.

**Workaround**: use `Logs/Server_*.log` as the real-time source (`CFileLogger` writes each line with `fopen/fclose`). The tool does exactly that.

## 6. `RestartOnCrash` spawns an unmanaged process

The server's built-in crash restart is:

```cpp
ForceEndServer();
ShellExecute(NULL, "open", szPath, NULL, NULL, 1);  // detached process
```

The new process does not connect to the management tool's command pipe, so it becomes an orphan that the tool cannot manage while it still holds the port. In testing, the second instance crashes immediately with `bind failed: 10048`.

**Workaround**: keep `RestartOnCrash: false` and use the management tool's supervision feature instead.
