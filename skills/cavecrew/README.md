# oncrew

Decision guide. When to delegate to onman subagents instead of doing the work inline.

## What it does

Tells main thread when to spawn a onman-style subagent. Compact return
contracts can reduce repeated prose when results return to main context, but
effect depends on task, agent, and delegation count. This skill publishes no
universal reduction rate.

Three subagents:

| Subagent | Job | Use when |
|----------|-----|----------|
| `oncrew-investigator` | Locate code (read-only) | "Where is X defined / what calls Y / list uses of Z" |
| `oncrew-builder` | Surgical edit, 1-2 files | Scope is obvious, ≤2 files. Refuses 3+ file scope. |
| `oncrew-reviewer` | Diff/file review | One-line findings with severity emoji |

Use vanilla `Explore` or `Code Reviewer` when you want prose, architecture commentary, or rationale. Use main thread directly for one-line answers and 3+ file refactors.

This skill is a decision guide, not a slash command. It activates when the conversation mentions delegation.

## How to invoke

Triggers on phrases like "delegate to subagent", "use oncrew", "spawn investigator", "save context", "compressed agent output".

## Example chaining

Locate → fix → verify (most common):

1. `oncrew-investigator` returns site list (`path:line`, symbol, note)
2. Main thread picks 1-2 sites, hands paths to `oncrew-builder`
3. `oncrew-reviewer` audits the resulting diff

Parallel scout: spawn 2-3 `oncrew-investigator` calls in one message with different angles (defs, callers, tests). Aggregate in main.

## Model overrides

By default, `oncrew-reviewer` and `oncrew-investigator` pin `model: haiku` in their frontmatter; `oncrew-builder` has no `model:` line (uses the API session default). Set env vars in your shell before launching Claude Code to override per-agent:

| Env var | Agent |
|---|---|
| `ONCREW_REVIEWER_MODEL` | `oncrew-reviewer` |
| `ONCREW_BUILDER_MODEL` | `oncrew-builder` |
| `ONCREW_INVESTIGATOR_MODEL` | `oncrew-investigator` |

Example: run reviewer on sonnet and keep others on default.

```sh
export ONCREW_REVIEWER_MODEL=sonnet
```

Use the same model name strings you'd use in any Claude Code agent frontmatter (e.g. `haiku`, `sonnet`, `opus`).

Overrides patch only `model:` line in installed agent frontmatter; prompt body
stays untouched and continues receiving upstream updates. Only plugin installs
have local agent files to patch. Empty variables do nothing. Patch persists until
plugin update or reinstall.

## See also

- [`SKILL.md`](./SKILL.md): full decision matrix and output contracts
- [`agents/oncrew-investigator.md`](../../agents/oncrew-investigator.md)
- [`agents/oncrew-builder.md`](../../agents/oncrew-builder.md)
- [`agents/oncrew-reviewer.md`](../../agents/oncrew-reviewer.md)
- [Onman README](../../README.md): repo overview
