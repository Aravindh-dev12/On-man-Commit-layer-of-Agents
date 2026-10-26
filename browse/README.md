# onman-browse

`onman-browse` is a local browser-interaction MCP server. It attaches to
Chrome, reads `Accessibility.getFullAXTree`, compresses the AX payload through
the Onman engine's forced-only `a11y` compressor, and exposes four tools:

- `browser_snapshot`
- `browser_act`
- `browser_eval`
- `browser_recover`

Savings are always `inferred`. Recovery is CCR-backed: `browser_recover` returns
the byte-exact original AX payload for a snapshot handle.

Source and binaries ship under Apache-2.0. See `LICENSE` and `../LICENSING.md`.

`browser_snapshot.query` is the token-efficient path on large pages. It keeps
best matching accessible nodes and ancestors while CCR retains full raw tree;
compact output uses `[uid] role "name"` lines, with UID tokens reserved for
actionable or unknown custom roles. `tokens_after` counts exact agent-visible
JSON result, and `view_tokens` isolates compact tree cost.

Build:

```bash
go build ./browse/cmd/onman-browse
```

Run as MCP server:

```bash
onman-browse
```

Direct CLI helper:

```bash
onman-browse snapshot http://127.0.0.1:3000
onman-browse snapshot http://127.0.0.1:3000 "save settings"
onman-browse act <uid> click
onman-browse recover <handle>
onman-browse close
```

Direct commands share one detached, isolated Chrome until `close`; first use
creates profile and CCR directories. Actions report `settled:false` until another
focused snapshot proves state, while navigation permits `http(s)`, `about:blank`,
and bounded `data:text/html` but rejects local files and privileged schemes.

Proof and comparison: [BENCHMARK.md](BENCHMARK.md). Large-page query focus wins
sharply; tiny-page results can exceed bare Playwright ARIA text because Onman
also returns UIDs, recovery, and exact accounting.
