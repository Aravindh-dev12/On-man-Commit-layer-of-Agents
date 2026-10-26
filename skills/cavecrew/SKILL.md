---
name: oncrew
description: >
  When to delegate to `oncrew-investigator` (locate code), `oncrew-builder`
  (1-2 file edit) or `oncrew-reviewer` (diff review) instead of working inline
  or using `Explore`. Their output is compressed, so main context lasts longer.
---

Oncrew = three subagent presets that emit onman output. Same job as Anthropic defaults (`Explore`, edit-style agents, reviewer); difference is the tool-result they return is compressed, so main context shrinks per delegation.

## When to use oncrew vs alternatives

| Task | Use |
|---|---|
| "Where is X defined / what calls Y / list uses of Z" | `oncrew-investigator` |
| Same but you also want suggestions/architecture commentary | `Explore` (vanilla) |
| Surgical edit, ≤2 files, scope obvious | `oncrew-builder` |
| New feature / 3+ files / cross-cutting refactor | Main thread or `feature-dev:code-architect` |
| Review diff, branch, or file for bugs | `oncrew-reviewer` |
| Deep code review with rationale + alternatives | `Code Reviewer` (vanilla) |
| One-line answer you already know | Main thread, no subagent |

Rule of thumb: **if you'd want the subagent's output in 1/3 the tokens, pick oncrew. If you'd want prose, pick vanilla.**

## Why this exists (the real win)

Subagent tool results get injected into main context verbatim. A vanilla `Explore` that returns 2k tokens of prose costs 2k tokens of main-context budget every time. The same finding from `oncrew-investigator` returns ~700 tokens. Across 20 delegations in one session that's the difference between context exhaustion and finishing the task.

## Output contracts

What main thread can rely on per agent:

**`oncrew-investigator`**
```
<Header>:
- path:line — `symbol` — short note
totals: <counts>.
```
Or `No match.` Always file-path-first, line-number-attached, backticked symbols. Safe to grep with `path:\d+`.

**`oncrew-builder`**
```
<path:line-range> — <change ≤10 words>.
verified: <re-read OK | mismatch @ path:line>.
```
Or one of: `too-big.` / `needs-confirm.` / `ambiguous.` / `regressed.` (terminal first token).

**`oncrew-reviewer`**
```
path:line: <emoji> <severity>: <problem>. <fix>.
totals: N🔴 N🟡 N🔵 N❓
```
Or `No issues.` Findings sorted file → line ascending.

## Chaining patterns

**Locate → fix → verify** (most common):
1. `oncrew-investigator` returns site list.
2. Main thread picks 1-2 sites, hands paths to `oncrew-builder`.
3. `oncrew-reviewer` audits the diff.

**Parallel scout** (when investigation is broad):
Spawn 2-3 `oncrew-investigator` calls in one message (different angles: defs vs callers vs tests). Aggregate in main thread.

**Single-shot edit** (when site is already known):
Skip investigator. Hand exact path:line to `oncrew-builder` directly.

## What NOT to do

- Don't use `oncrew-builder` when you don't already know the file. Spawn investigator first or main thread will eat tokens passing context.
- Don't chain `oncrew-investigator → oncrew-builder` for a 5-file refactor. Builder will return `too-big.` and you'll have wasted a turn.
- Don't ask `oncrew-reviewer` for "general feedback" — it returns findings only, no architecture opinions. Use `Code Reviewer` for that.
- Don't expect prose. Oncrew output is structured, sometimes terse to the point of cryptic. If a human will read it directly, paraphrase.

## Auto-clarity (inherited)

Subagents drop onman → normal English for security warnings, irreversible-action confirmations, and any output where fragment ambiguity could be misread. Resume onman after.
