# Prisma SD-WAN Network Experience

Customer-facing portal powered by the repository's existing `prisma_sdwan_mcp` tools.

## Repository layout

Place this directory directly under the repository root:

```text
prisma-sdwan-mcp/
├── prisma_sdwan_mcp/
└── webtester/
    ├── server.py
    ├── app/
    └── static/
```

The application derives all filesystem locations from `__file__`. It does not depend on a Windows drive, username, clone directory, or current working directory.

## Run

From the repository root:

```bash
python webtester/server.py
```

Or from any directory:

```bash
python /path/to/prisma-sdwan-mcp/webtester/server.py
```

Default address:

```text
http://127.0.0.1:8765/
```

## Configuration

No credentials or tenant values are stored in the source code.

Supported environment variables:

| Variable | Purpose | Default |
|---|---|---|
| `PAN_CLIENT_ID` | Prisma service-account client ID | none |
| `PAN_CLIENT_SECRET` | Prisma service-account secret | none |
| `PAN_TSG_ID` | Tenant service group ID | none |
| `PAN_REGION` | Optional Prisma region | none |
| `PRISMA_PORTAL_HOST` | Web server bind address | `127.0.0.1` |
| `PRISMA_PORTAL_PORT` | Web server port | `8765` |
| `PRISMA_MCP_ROOT` | Optional repository root override | auto-detected |
| `PRISMA_PORTAL_DEBUG` | Include server traceback when set to `1` | disabled |

Linux/macOS example:

```bash
export PAN_CLIENT_ID='...'
export PAN_CLIENT_SECRET='...'
export PAN_TSG_ID='...'
python webtester/server.py
```

PowerShell example:

```powershell
$env:PAN_CLIENT_ID='...'
$env:PAN_CLIENT_SECRET='...'
$env:PAN_TSG_ID='...'
python .\webtester\server.py
```

CLI options override host and port defaults:

```bash
python webtester/server.py --host 127.0.0.1 --port 9000
```

## Security defaults

- Binds to localhost by default.
- Credentials are not committed or written to disk.
- Browser-entered credentials are held only by the running Python process.
- Static files and API calls are same-origin.
- Debug tracebacks are disabled by default.

Do not bind to `0.0.0.0` unless the deployment is protected by appropriate authentication, TLS, and network controls.

## Preview mode

The Preview switch uses clearly isolated sample data from `app/demo.py`. It does not call Prisma SD-WAN and contains no real customer data or credentials.
