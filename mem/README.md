# onmem

Durable, compression-native agent memory: `remember`, `recall`, `supersede`,
`history`, `forget`.
Memories live in a local SQLite store; recall ranks them with BM25 behind a
conservative threshold and compresses each hit through the
[Onman engine](../engine), so the inferred token cost is honest and the dropped
detail stays recoverable. Counts are inferred; component never claims `verified`
savings.

Go core, binary, and thin JS/Python clients ship under Apache-2.0. See
`LICENSE` and `../LICENSING.md`.

## CLI

```bash
go build -o onmem ./mem/cmd/onmem
./onmem remember "the deploy key lives in vault under ops/deploy"
./onmem recall   "where is the deploy key"      # JSON: { hits: [...], basis: "inferred" }
./onmem recall   "full migration context" 5 0   # explicit 0 token budget = unlimited
./onmem supersede mem_xxxxxxxx "deploy key moved to vault ops/deploy-v2"
./onmem history   mem_yyyyyyyy                  # oldest → current
./onmem forget   mem_xxxxxxxx
./onmem          # runs the MCP server over stdio
```

## MCP

```jsonc
{ "mcpServers": { "onmem": { "command": "onmem" } } }
```

## Libraries

Thin clients shell text to the binary over stdin (avoiding OS argument-size limits;
set `CAVEMEM_BIN` if it is not on PATH):
an oversized `remember` exits with code 65; both clients export
`MEMORY_TOO_LARGE_EXIT_CODE` so callers can branch without parsing stderr.

```js
import { remember, recall, supersede, history, forget } from "onmem"; // js/index.mjs
await remember("…"); await recall("…", 5, 2000); await recall("…", 5, 0); // unlimited
```
```python
import onmem                                            # py/onmem.py
onmem.remember("…"); onmem.recall("…", limit=5, token_budget=2000)
```

## Guarantees

- Byte-safe write: raw text is stored before anything else, so a memory is never lost.
- Off-topic query recalls nothing rather than guessing.
- Recall packs at most 2000 inferred tokens by default. CLI, MCP,
  JS, and Python callers may explicitly request `token_budget: 0` for unlimited
  recall; omitting it never disables the cap.
- Recall excludes superseded facts by default; history stays local and auditable.
- Every compressed recall hit carries a `recovery_handle`.
