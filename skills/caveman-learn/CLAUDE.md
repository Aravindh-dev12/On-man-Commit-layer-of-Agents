# skills/onman-learn — the Onman Learn editing skill (Apache-2.0, public)

The consent-gated half of `onman learn`. The analyzer (the Go proxy) **measures**
where an agent's tokens go and writes a ranked plan; this skill is what an agent
loads to **act** on that plan — proposing each fix and applying it only with the
user's per-edit yes. It is the loop-closer the learn spec §10
describes, plus the new `onmem_offload` move.

## Layout
- `SKILL.md` — the canonical skill body (frontmatter `name: onman-learn` + a
  trigger-phrase `description`; body = the read-plan → per-class consent loop). This
  file is the source of truth.
- `tests/skill-file.test.mjs` — asserts the canonical file is well-formed and honest
  (frontmatter present; the net-token-negative gate, the never-make-the-agent-dumber
  guard, consent-per-edit, and reversibility are all stated; no imperative for
  behavioral findings; no placeholders).

## Install path
`onman tools skills install onman-learn` (in `../../cli/src/index.ts`) writes this file
into a repo's `.claude/skills/onman-learn/SKILL.md` (Claude Code) or
`~/.codex/skills/onman-learn/SKILL.md` (Codex). The CLI **embeds a byte-identical copy**
(`ONMAN_LEARN_SKILL_MD`) because the published CLI ships no sibling assets;
`../../cli/tests/skills.runtime.mjs` asserts the embedded copy equals this canonical
file (the drift guard). **Change this file and that constant together.**

## Boundary (binding)
The skill — using the agent's own file tools — is the ONLY thing that edits a user's
config. `onman learn apply` stays read-only (it materializes candidates), and
`onman mem *` are mechanical store ops. The offload move enforces a net-token-negative
gate and the never-make-the-agent-dumber guard before any trim.

See ../../mem/CLAUDE.md (onmem) · ../onman-explore/SKILL.md (the packaging precedent)
