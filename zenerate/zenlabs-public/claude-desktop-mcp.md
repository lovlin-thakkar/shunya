# Connecting Claude Desktop to ZenLabs

ZenLabs exposes its API as an MCP server, so Claude Desktop can read and write your data using the same permissions as your ZenLabs account.

## Endpoint

```
https://zenarate-web-prod.fly.dev/api/v1/mcp-stream
```

This is the Streamable HTTP MCP endpoint. Auth is OAuth — Claude Desktop opens a browser window for you to log in, pick a workspace (tenant), and grant access.

---

## Add the connector

1. Open Claude Desktop or Web
2. Go to **Settings → Connectors** (or **Settings → Developer → Connectors** on some versions).
3. Click **Add custom connector**.
4. Fill in:
  - **Name:** `ZenLabs`
  - **URL:** `https://zenarate-web-prod.fly.dev/api/v1/mcp-stream`
5. Click **Save**, then **Connect**.
6. In case you see auth issues, try clearing cookies for  [https://zenarate-prod.vercel.app/](https://zenarate-prod.vercel.app/)

Claude Desktop will:

- Open a browser tab.
- Show the ZenLabs login screen — sign in with your email + password.
- Show a workspace picker — pick the tenant you want Claude to operate in.
- Show a consent screen — approve the requested scopes.

After the popup closes, the connector shows a green dot. You're ready.

---

## `whoami` example

Open a new conversation in Claude Desktop and ask:

```
Use the ZenLabs connector. Run whoami.
```

Claude calls the `whoami` tool and replies with something like:

```
User: jane@acme.com
Tenant: Acme Pets (id=42)
```

This confirms the connection is live and bound to the workspace you picked during OAuth.

Try a real call next:

```
Using ZenLabs, list the first 5 workflows in my tenant.
```

Claude picks the right tool from the ~270 auto-discovered endpoints and returns the result inline.

---

## Switching to a different workspace

OAuth tokens are bound to one tenant. To switch:

1. Quit Claude Desktop.
2. Remove the cached auth: `rm -rf ~/.mcp-auth`
3. Relaunch Claude Desktop.
4. Trigger any ZenLabs tool — the OAuth popup opens again and you can pick a different workspace.

---

## Troubleshooting


| Symptom                                   | Fix                                                                       |
| ----------------------------------------- | ------------------------------------------------------------------------- |
| Connector shows red / "failed to connect" | Check your network — the endpoint must be reachable over HTTPS.           |
| OAuth popup loops without finishing       | Clear `~/.mcp-auth`, quit Claude Desktop, relaunch.                       |
| 401 on every tool call                    | Your access token expired or was revoked. Force re-auth as above.         |
| Tools work in one chat but not another    | Restart Claude Desktop — the connector caches tool discovery per session. |


