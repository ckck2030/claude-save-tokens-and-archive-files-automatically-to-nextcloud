---
name: claude-archive
description: Nextcloud archive, journal and handoffs for the user's threads. Use when the user says archive, handoff or journal, or asks what was done on a date.
---

# Claude Archive

The hooks do the archiving on their own; never narrate it. Script: `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/archive.py"`.

## What gets saved
After every turn a background job uploads each file in the outputs folder, and each file sent with SendUserFile, whose name follows the rule:

`<product>-<mm-dd-yyyy>-ver<X.Y.Z>-<type>[.ext]`, all lowercase, no spaces, e.g. `recipe-app-desktop-10-28-2026-ver2.8.9-source.zip`. Type: source, executables, documentation, installer, plugin, assets, images, design, data, config, report, backup.

Files with other names are skipped. If a name looks like a failed try, the next prompt brings a one-line note: rename it inside a call you are making anyway, or run `ignore --session <id> <name>` for an old version. Bump the version for every build; never reuse a number. Check names with `checkname <name>`.

The folder is named for you: `<product>-<date>-ver<X.Y.Z>-<thread name>`, renamed when a newer version of the same product is uploaded. To fix it: `folder --session <id> <name>`. Older versions move to `older-versions/`. The journal (topic, time spent, file deliverables) is written by the hook.

## Handoff doc
Write one only when the prompt hook asks (thread passed 150K) or the user asks; do it while answering, never as a separate reply. Do it in ONE Bash call: heredoc to /tmp/handoff.md, then `handoff --session <id> --file /tmp/handoff.md` (add `--chain <short product name>` if the thread has no chain yet). Sections:
- `# <topic, max 8 words>`
- `## Goal`, `## Decisions`, `## Current state` (versions, file names, live URLs), `## Next steps`, `## Key numbers`
- `## Highlights`: 0-3 of the user's goals, max 6 words each, no commas
- `## Deliverables` (optional): live pages changed, with their URLs

Named handoffs ("handoff thread as x-v1", "handoff just the discussion about T as x-v1"): the prompt hook gives the exact command (`--as`, `--scope`).

## Thread names
Threads form chains `<chain>-v<N>`. The user continues with `continue <chain>-v<N>` as the only text in a new thread; the hook loads the handoff doc. Say the thread name in the first reply. From 150K on, the prompt hook gives the exact `152K continue x-vN` line to end replies with (`152K send handoff` while the thread has no name yet); never write a size or continue line otherwise.

## Other
- `journal: <text>` from the user adds a journal note through the hook, with no reply.
- Extra files outside the outputs folder: `upload --session <id> <file>...`
- Past work: `.state/journal-days.json` in the archive folder, or the viewer search.
- Never print the password or tokens in config.json.
