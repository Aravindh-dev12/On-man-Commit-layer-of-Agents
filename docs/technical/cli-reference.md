# CLI reference

`onman` and `cave` invoke the same command-line program. The short alias is
useful in terminals; scripts should prefer `onman` because its meaning is
clearer to readers. The npm CLI requires Node.js 22.13 or newer.

Run `onman help <command>` for installed-version help. This page explains the
command groups and important behavior; command help remains the exact source
for accepted flags.

## Main commands

| Command | Purpose | Account needed |
|---|---|---:|
| `onman <agent>` | Persistently enable native integration, then run supported agent | No |
| `onman wrap <agent>` | Run one ephemeral wrapped session without persistent host config | No |
| `onman run -- <command>` | Run an arbitrary command through the local layer | No |
| `onman learn` | Rank locally observed improvements | No |
| `onman status` | Show local runtime, mode, and connection state | No |
| `onman login` | Connect the installation to Onman Cloud | Yes |
| `onman tools` | Open the local tool namespace | No |
| `onman cloud` | Open the connected-service namespace | Yes |

Supported agent shortcuts are `aider`, `claude`, `codex`, `gemini`, `hermes`,
`kilo` (`kilocode` alias), `openclaw`, `opencode`, `pi`, and `qwen`.

```bash
onman claude
onman kilo run "review this repository"
onman qwen -p "review this repository"
onman codex --full-auto
onman run -- my-agent --project .
```

Arguments after an agent name are passed to that agent. Arguments after `--`
in `onman run` are passed to the selected command.

## Local tool namespace

`onman tools` groups less frequent local commands by job.

| Group | Commands |
|---|---|
| Think | `compress`, `shrink`, `toon`, `convert` |
| Remember | `mem`, `retrieve` |
| Execute | `mcp`, `hooks`, `browse`, `skills`, `sdk` |
| Inspect | `stats`, `trial`, `evals`, `config` |

### `compress`

Compress text from standard input or a file. Compression is local. Lossy output
contains a recovery handle when a recovery store is available.

```bash
onman tools compress < long-context.txt
onman tools retrieve ccr_0123456789abcdef0123456789abcdef
```

Use `onman start` when an application needs an HTTP proxy instead of a
one-shot command.

### `shrink`

Reduce large command or tool output while preserving selected structure and a
recovery reference. Input larger than the command limit is rejected rather
than partially processed.

### `toon`

Encode or decode structured data using TOON. Encoding only wins on suitable
data, commonly uniform arrays of objects. It is not a byte-preserving
transformation.

### `convert`

Pack supported installed skills into pixel form for selected agent or project;
flags include `--agent`, `--project`, `--skill`, `--dir`, `--density`,
`--dry-run`, `--revert`, and `--force`. Run a dry run before changing a large
skill tree.

### `mem`

Manage local durable memory. Available operations include `remember`, `recall`,
`supersede`, `history`, and `forget`. See [Local tools](local-tools.md).

### `mcp`

Install or remove local Model Context Protocol registrations for detected
agents. Server choices include recovery, browser, connected read-only evidence,
and opt-in delegation tools.

```bash
onman tools mcp install claude --server onman
onman tools mcp uninstall claude --server onman
onman tools mcp install qwen --server onman
onman tools mcp uninstall qwen --server onman
```

Qwen registration is written to `~/.qwen/settings.json`. Onman preserves
sibling settings and refuses to replace or remove an entry that is not recorded
as Onman-owned.

`onman-mcp` binary itself serves compression, recovery, statistics, and TOON
tools over standard input and output.

### `hooks`

Install or inspect supported agent hooks. Hooks add local context and compact
output behavior to agent-native event systems. See
[Skills, hooks, and plugins](skills-hooks-and-plugins.md).

### `browse`

Control a Chrome session through the local browser bridge.

```bash
onman tools browse https://example.com "main article"
onman tools browse act '<element-reference>' click
onman tools browse eval 'document.title'
onman tools browse recover '<recovery-handle>'
onman tools browse close
```

Browser evaluation executes JavaScript in the attached page. Treat expressions
as code, and use them only on pages you trust.

### `skills`

List, preview, install, add, or import skills. Preview an external skill before
installation.

```bash
onman tools skills list
onman tools skills preview owner/repository
onman tools skills install owner/repository
```

### `sdk`

Print or apply integration recipes for supported SDKs and agent frameworks.
Recipes cover Anthropic, OpenAI, Google Gen AI, Vercel AI SDK, LangChain,
LiteLLM, CrewAI, Pydantic AI, OpenAI Agents SDK, and direct `curl` use.

### `stats`, `trial`, and `evals`

- `stats` reports local compression and usage records.
- `trial` exercises local features against fixtures or configured providers.
- `evals` runs evaluation-related commands available in the installed build.

Local observations are not verified savings. See
[Accounting and evidence](accounting-and-evidence.md).

### `config`

Read or change local feature configuration.

```bash
onman tools config path
onman tools config get think.mode
onman tools config set think.mode compress
```

See [Configuration](configuration.md) for keys, values and precedence.

## Runtime commands

### `start`

Start the loopback HTTP proxy. Default address is `127.0.0.1:8787`.

```bash
onman start
```

The proxy uses `~/.onman/onman.yaml` unless `ONMAN_CONFIG` names another
file. It stores local operational data in `~/.onman/onman.db`.

### `setup`

Inspect or install local runtime components.

```bash
onman setup
onman setup --install
onman setup --json
onman setup --agent-native claude
onman setup --agent-native codex
```

Add `--remove` to an `--agent-native` command to remove that integration.

### `wrap`

`wrap` is the explicit form used by agent shortcuts.

```bash
onman wrap claude
onman wrap --off codex
onman wrap --pixel gemini
onman wrap --workflow review opencode
onman wrap qwen
```

- Default mode enables supported local compression, structured-data encoding,
  recovery, and output shrinking.
- `--off` runs byte-safe pass-through recording.
- `--pixel` enables lossy text-to-image context transport for models listed in
  configuration.
- `--workflow` selects a named workflow when the installed profile supports it.

Record mode never changes model-visible request bytes.

## Learning commands

`onman learn` reads local observations and ranks possible improvements.

```bash
onman learn
onman learn --since 7d --sources claude,codex,gemini,opencode,aider
onman learn --all
onman learn --repo my-project
onman learn --json
onman learn implement codex --prompt "focus on config fixes"
onman learn apply claude_md_weight:project --dry-run
onman learn simulate claude_md_weight:project recurring_context:repaste:<fingerprint>
onman learn applied claude_md_weight:project --fix-kind claude_md_weight --note "approved and re-measured"
```

Output formats include plain text, JSON, and Markdown. `--all` adds every sink,
confirmed outcomes, per-repository observations, and advanced command hints.
`--repo` filters sessions before analysis. `apply` prepares one candidate;
`simulate` totals counterfactual scale over scanned history; `applied` records a
completed, re-measured fix in Onman's outcome store. A recommendation remains
an inferred opportunity until stronger evidence exists. Aider scanning remains
opt-in through `ONMAN_AIDER_ROOT` because its history is repository-local.
Full reference: [onman learn](./learn.md).

## Connected namespace

`onman cloud` is the account and network namespace. Its command groups cover:

- account: `whoami`, `projects`, `keys`, `providers`, `billing`;
- evidence: `score`, `costs`, `plan`, `traces`, `experiments`, `receipts`;
- governance: `audit`, `sync`, `agent`.

These commands require a connected installation and may depend on plan or
organization policy. This repository documents client behavior and public
contracts, not hosted implementation details.

## Exit and failure behavior

Commands use nonzero exit status for invalid arguments, rejected configuration,
missing dependencies, and failed operations. Destructive or ambiguous local
transformations should use `--dry-run` where offered. Compression paths prefer
original input over unsafe or incomplete output.
