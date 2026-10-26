# onman-help

Quick-reference card. One shot, no mode change.

## What it does

Prints a cheat sheet of all onman modes, sibling skills, deactivation triggers, and how to set the default mode via env var or config file. One-shot display — does not flip the active mode, write flag files, or persist anything. Use when you forget the slash commands.

## How to invoke

```
/onman-help
```

Also triggers on "onman help", "what onman commands", "how do I use onman".

## Example output

```
Modes:
  /onman              full (default)
  /onman lite         lighter
  /onman ultra        extreme
  /onman wenyan       classical Chinese

Skills:
  /onman-commit       terse Conventional Commits
  /onman-review       one-line PR comments
  /onman-stats        session token savings

Deactivate:
  "stop onman" or "normal mode"
```

## See also

- [`SKILL.md`](./SKILL.md) — full reference card
- [Onman README](../../README.md) — repo overview
