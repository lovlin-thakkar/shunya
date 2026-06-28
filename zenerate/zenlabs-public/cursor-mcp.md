# Connecting Cursor to ZenLabs

Cursor connects to the same MCP server as Claude Desktop. Same endpoint, same OAuth flow, same tools.

## Endpoint

```
https://zenarate-web-prod.fly.dev/api/v1/mcp-stream
```

Requires **Cursor 0.45 or newer** — earlier builds don't support remote MCP servers.

---

## Setup

1. Open Cursor.
2. Go to **Cursor Settings → MCP** (`⌘,` → search "MCP").
3. Click **Add new MCP server**.
4. Fill in:
   - **Name:** `zenlabs`
   - **Type:** `streamable-http` (or `http`, depending on Cursor's labels)
   - **URL:** `https://zenarate-web-prod.fly.dev/api/v1/mcp-stream`
5. Save.

Cursor opens a browser window:

1. Sign in to ZenLabs.
2. Pick a workspace (tenant).
3. Approve the access request.

After the popup closes the entry shows a green indicator and a tool count. You're ready.

---

## Using the tools

Open Composer (`⌘I`) or the chat panel and try:

```
Use the zenlabs MCP server. Run whoami.
```

Expected reply:

```
User: jane@acme.com
Tenant: Acme Pets (id=42)
```

Then try a real call:

```
List the first 5 workflows in my tenant using zenlabs.
```

Cursor will pick the right endpoint out of the ~270 auto-discovered tools.

---

## Switching workspace

OAuth binds a token to one tenant. To switch:

1. Quit Cursor.
2. Remove cached auth: `rm -rf ~/.cursor/mcp`
3. Relaunch Cursor.
4. Trigger any zenlabs tool — the OAuth popup reopens and you can pick a different workspace.

---

## Troubleshooting

| Symptom | Fix |
|---------|-----|
| Server entry has zero tools | Toggle the server off/on in **Settings → MCP** — Cursor caches discovery aggressively. |
| "Cannot reach server" | Confirm you can `curl -X POST https://zenarate-web-prod.fly.dev/api/v1/mcp-stream/` and get a JSON response. |
| OAuth popup never returns | Disable any browser extension that interferes with redirects; retry. |
| Works in Claude Desktop, not in Cursor | Check **Settings → MCP → View Logs**. Most issues are version-related — upgrade Cursor. |
