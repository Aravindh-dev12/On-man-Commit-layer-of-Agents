# onman — opencode plugin

Native opencode plugin. Mirrors the Claude Code hook architecture using
opencode's `session.created` + `tui.prompt.append` lifecycle hooks.

## What this ships

| File | Role |
|---|---|
| `plugin.js` | ESM Bun module. Default-exports an opencode `Plugin` factory. |
| `package.json` | Marks the directory as ESM so Bun loads `plugin.js` correctly. |
| `commands/*.md` | Six slash-command prompt templates (`/onman`, `/onman-commit`, …). |

The installer (`bin/install.js --only opencode`) copies these alongside
`src/hooks/onman-config.js` (for the symlink-safe flag-write helpers, renamed
to `onman-config.cjs` because this directory is `"type": "module"`) into
`~/.config/opencode/plugins/onman/` and patches `opencode.json` with a
`"plugin"` array entry.

## What it does

- `session.created` → writes the configured default mode to
  `~/.config/opencode/.onman-active` via the same `safeWriteFlag` helper
  Claude Code uses (O_NOFOLLOW, atomic temp+rename, 0600 perms, symlink
  refusal, ownership check).
- `tui.prompt.append` → flips the flag in response to `/onman[ <level>]`,
  `/onman-commit`, `/onman-review`, `/onman-compress`, and natural
  language ("turn on onman", "stop onman", "normal mode"). When a
  non-independent mode is active, appends a one-line reinforcement to keep
  onman in the model's attention each turn.

## What it does NOT do

- **No statusline badge.** opencode's TUI does not expose a plugin-writable
  statusline. The flag file is at `~/.config/opencode/.onman-active` if
  you want to surface mode in your shell prompt.
- **No system-prompt injection from `session.created`.** opencode's docs
  don't expose a return shape for that. The always-on onman ruleset comes
  from `~/.config/opencode/AGENTS.md` (also written by the installer) so
  the rules load even when the plugin runtime is broken.

## Why no separate npm package

Plugin code reuses `onman-config.js` from the main repo. Shipping as an
in-repo plugin avoids a second release cadence and a name collision with
the existing third-party `opencode-onman` npm package.
