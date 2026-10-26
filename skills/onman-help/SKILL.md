---
name: onman-help
description: >
  Quick-reference card for onman modes, skills and commands.
  Trigger: /onman-help or "onman help".
---

# Onman Help

Display this reference card when invoked. One-shot — do NOT change mode, write flag files, or persist anything. Output in onman style.

## Modes

| Mode | Trigger | What change |
|------|---------|-------------|
| **Lite** | `/onman lite` | Drop filler. Keep sentence structure. |
| **Full** | `/onman` | Drop articles, filler, pleasantries, hedging. Fragments OK. Default. |
| **Ultra** | `/onman ultra` | Extreme compression. Bare fragments. Tables over prose. |
| **Wenyan-Lite** | `/onman wenyan-lite` | Classical Chinese style, light compression. |
| **Wenyan-Full** | `/onman wenyan` | Full 文言文. Maximum classical terseness. |
| **Wenyan-Ultra** | `/onman wenyan-ultra` | Extreme. Ancient scholar on a budget. |

Mode stick until changed or session end.

## Skills

| Skill | Trigger | What it do |
|-------|---------|-----------|
| **onman-commit** | `/onman-commit` | Terse commit messages. Conventional Commits. ≤50 char subject. |
| **onman-review** | `/onman-review` | One-line PR comments: `L42: bug: user null. Add guard.` |
| **onman-compress** | `/onman-compress <file>` | Compress .md files to onman prose. Saves ~46% input tokens. |
| **onman-help** | `/onman-help` | This card. |

## Deactivate

Say "stop onman" or "normal mode". Resume anytime with `/onman`.

## Language

Keep user's language by default — reply in the language user writes, never switch regardless of example text or multilingual context elsewhere. Compress the style, not the language. Technical terms, code, commands, commit types, and exact error strings stay verbatim unless user ask for translation.

## Configure Default Mode

Default mode = `full`. Change it:

**Environment variable** (highest priority):
```bash
export ONMAN_DEFAULT_MODE=ultra
```

**Config file** (`~/.config/onman/config.json`):
```json
{ "defaultMode": "lite" }
```

Set `"off"` to disable auto-activation on session start. User can still activate manually with `/onman`.

Resolution: env var > config file > `full`.

## More

Full docs: https://github.com/Aravindh-dev12/onman
