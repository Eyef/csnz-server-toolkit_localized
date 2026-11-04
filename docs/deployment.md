# Deployment Guide

## Port Plan

| Service | Default port | Configurable | Notes |
|---|---|---|---|
| CSNZ game server | 30002 | Yes (`ServerConfig.Port`) | Shared by TCP + UDP |
| Authentication service | 38120 | Yes (from the management tool) | TCP only |
| Client UDP | 27015 / 27005 | No | Fixed by the game engine |

**There is only one source for the port.** In the server source:

```cpp
tcpPort = udpPort = cfg.value("Port", DEFAULT_PORT);
```

TCP and UDP share the same port, and clients must connect to that same port, so the tool asks for it only once.

## Security Group

Allow these ports on the cloud server:

- `30002` TCP + UDP (players connect to the game)
- `38120` TCP (the launcher connects to the authentication service)

> Forgetting to open the authentication port is the most common cause of "the launcher cannot connect".

## API Key

All three configuration files must use **the same key**:

| File | Field |
|---|---|
| `auth-server/config.json` | `api_key` |
| `gm-tool/config.json` | `auth_api_key` |

Generate one with:

```bash
python -c "import secrets;print(secrets.token_hex(32).upper())"
```

After changing any of them, synchronize the others too, otherwise the launcher receives 401.

## HTTPS (required in production)

Passwords are stored and compared in **plaintext** by the server:

```sql
SELECT userID FROM User WHERE userName = ? AND password = ?
```

Hashing them would break the game client's built-in login, so encrypted storage is not possible. The only mitigation is transport encryption.

`auth-server/config.json`:

```json
{
  "use_https": true,
  "cert_file": "cert.pem",
  "key_file": "key.pem"
}
```

Put the certificates in the `auth-server/` directory.

The launcher's `auth_base_url` must also use `https://`.

## Address Configuration

The player launcher needs two addresses:

- Authentication service: `https://your-domain:38120`
- Game server: `your-public-ip:30002`

Both must be reachable over the public internet.

## Reverse Proxy (recommended)

Use Nginx for HTTPS and let the authentication service listen only on 127.0.0.1:

```nginx
server {
    listen 443 ssl;
    server_name auth.example.com;

    ssl_certificate     /etc/ssl/cert.pem;
    ssl_certificate_key /etc/ssl/key.pem;

    location / {
        proxy_pass http://127.0.0.1:38120;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header Host $host;
    }
}
```

The authentication service reads the first entry of `X-Forwarded-For` as the real client IP, so rate limiting and automatic bans count the real source.

With this setup, `auth-server/config.json` can set `listen_host: "127.0.0.1"`.

## Starting at Boot

The management tool does not register a service. To start it at boot:

1. `Win + R` → `shell:startup`
2. Put a shortcut to `gm-tool/Start.bat` (or `CSNZ.GMTool.exe`) in that folder
