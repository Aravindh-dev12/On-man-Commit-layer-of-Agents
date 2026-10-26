---
description: Compress a markdown/text file into onman format to save tokens
---
Compress the file at: $ARGUMENTS

Run the `onman-compress` skill against the given filepath. The skill rewrites
prose into terse onman style — drops articles, filler, hedging — while
preserving code blocks, inline code, URLs, file paths, commands, and markdown
structure exactly. Original is backed up as `<file>.original.md` before
overwrite.

Only compress natural-language files (`.md`, `.txt`, `.typ`, `.tex`,
extensionless). Refuse source/config files (`.py`, `.js`, `.ts`, `.json`,
`.yaml`, `.toml`, `.sh`, etc.). Never compress an existing `*.original.md`
backup.
