# onman-mcp

The Onman MCP server: five compression tools — `onman_compress`,
`onman_retrieve`, `onman_stats`, `onman_toon_encode`, and
`onman_toon_decode` — over stdio, for any MCP host. It links the
[Onman Engine](../engine) in-process. **Local-only** (opens no
network connection) and **inferred-only** (it never claims `verified` savings).

## Install (Claude Code)

```jsonc
// .mcp.json / claude mcp config
{
  "mcpServers": {
    "onman": { "command": "npx", "args": ["-y", "onman-mcp"] }
  }
}
```

The launcher downloads matching binary on first run, verifies
key-signed checksum manifest plus artifact SHA-256, and caches it under
`~/.onman/bin`. No Go toolchain or global Onman install is required.
To use an existing reviewed binary instead:

```bash
ONMAN_MCP_BIN=/path/to/onman-mcp npx onman-mcp
```

npm launcher and downloaded binary are both Apache-2.0; see `BINARY_LICENSE.md`.

## Tools

| Tool | Input | Returns |
|---|---|---|
| `onman_compress` | `input` (string) | compressed text, inferred `ratio`, `recovery_handle` (null on pass-through) |
| `onman_retrieve` | `recovery_handle` (string), optional `query` | byte-exact original without a query; ranked complete records with a query; error on unknown handle |
| `onman_stats` | — | this MCP process's compression-call totals, including repeated inputs and pass-throughs: tokens before/after, `requests`, `ratio`, `basis:"inferred"`, `scope:"session"` |
| `onman_toon_encode` | `input` (JSON string) | explicit JSON→TOON result with sizes; pass-through plus note when not encodable |
| `onman_toon_decode` | `input` (TOON string) | decoded JSON; error on invalid TOON |

Compression is lossy (S4) but **reversible**: every drop is recoverable via
`onman_retrieve`. Incompressible or malformed input passes through unchanged
with `ratio:0` — never an error.

Repeated recovery calls remain available after host compaction. An empty query
returns the exact stored original on every call; a nonempty query keeps the same
record-narrowing behavior regardless of how many earlier calls were made.
