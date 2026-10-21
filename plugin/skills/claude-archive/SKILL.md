---
name: claude-archive
description: Saves this thread's deliverables to the user's Nextcloud, records the day's work in their journal and keeps a handoff doc. Use when the Claude Archive Stop hook asks for it, or when the user says "archive this", "save to Nextcloud", "add to journal", or asks what was done on a past date.
---

# Claude Archive

The user's Nextcloud holds an archive folder (`root_folder` in config.json, normally `claude`):
- `<root>/<thread folder>/` - one folder per thread, holding its deliverables, its handoff doc and an `older-versions` subfolder.
- `<root>/.state/journal-days.json` - the journal record: per day, per thread, the topic, time spent, folder and deliverable lines. The Claude Archive viewer (a small PHP page on the user's web host) shows it as the journal and project list; the user never reads Nextcloud itself.

All access goes through `${CLAUDE_PLUGIN_ROOT}/scripts/archive.py` (dates in the configured timezone).

## Thread folder naming (strict, enforced)

`<product>-<component>-<mm-dd-yyyy>-ver<X.Y.Z>-<what-was-done>` - all lowercase, no spaces, hyphens only.

Examples: `recipe-app-desktop-10-17-2026-ver2.6.9-search-feature`, `claude-archive-plugin-10-17-2026-ver0.5.0-nextcloud-setup`

- Be descriptive and exact: name the specific product and component (if a product has a desktop app AND browser extensions, say which). Never write a bare version like "2-6-9".
- Version = the version of the thread's main deliverable. When it changes later in the thread, pass the new folder name; the script renames the folder and fixes its journal links.
- Check a name with `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/archive.py" checkfolder <name>`.

## File naming (strict, enforced)

Every file or folder sent to Nextcloud (each top-level item in the outputs folder) must be named:

`<project>-<mm-dd-yyyy>-ver<X.Y.Z>-<type>[.ext]` - all lowercase, no spaces.

Examples: `recipe-app-desktop-10-28-2026-ver2.8.9-source.zip`, `recipe-app-desktop-10-28-2026-ver2.8.9-executables`, `recipe-app-desktop-10-28-2026-ver2.8.9-documentation.zip`

- Date = the day the file was made. Version = the real version of what's inside; never invent or reuse a number - bump it for every new build.
- Type must be one of: source, executables, documentation, installer, plugin, assets, images, design, data, config, report, backup (`file_types` in config.json).
- Name deliverables this way when creating them, not just before upload. Check names with `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/archive.py" checkname <name> [...]`.
- The upload skips (and lists) wrongly named items and never re-uploads files already on the server. For each skipped item: rename it if it is a current deliverable and run upload again; if it is an old or superseded version, run `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/archive.py" ignore --session <session id> <name> [...]` so it is never archived. Never rename an old version just to get it uploaded.

## Everything you make gets archived

The user wants a copy of everything Claude creates or changes - code, plugins, docs, md files, graphics - including things installed straight onto their sites. Build work under `scan_root` (not the scratchpad). The Stop hook lists changed items not yet archived; zip a project folder or copy a file into the outputs folder with a rule-compliant name (e.g. `shop-visitors-plugin-10-18-2026-ver0.17.3-source.zip`), then `mark` the listed paths. Scratch/test/downloaded items only need `mark`.

## Handoff doc and continuing in a new thread

Each thread folder keeps one handoff doc (thread links, then your notes): goal, what was done (decisions, not steps), current state and versions, where code/files live, open issues, next steps. Write it to a temp .md and run the `handoff` command the hook gives; it replaces the old one. When the user sends `continue <folder>` as the only text in a new thread, the hook loads the doc and the thread adopts that folder.

Journal lines label links "files" (the thread folder), "live page" (a published URL), "claude thread" and "handoff". Uploads move older versions of a file (same project, type and extension, lower version) into the folder's `older-versions` subfolder; `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/archive.py" tidy --all` does it for every folder.

## When the Stop hook asks

Run the commands it lists, filling in:
- `--folder`: the thread folder name (rule above). Reuse the existing one unless the main version changed.
- `--topic`: what the thread is about, max 8 words (e.g. "Shop blog rewrites").
- `--highlight` (0-3, re-send the full set): only when a lot was done today - the main things the user asked for, phrased as their goals, max 6 words, no commas. Never Claude's own steps (reviews, research, prep, forms, setup).
- `--deliverable` (0-10): a finished result the user can use, max 10 words. The script only accepts it if this thread saved new files to Nextcloud since its last deliverable, or if it contains the URL of something published/changed live (e.g. "Updated blog article https://example.com/..."). Most threads have no deliverables. Never include passwords, tokens, keys or code.

Run them silently. Do not narrate the archiving unless a command fails; if it fails, say so in one sentence.

## Manual use

- The user typing `journal: <text>` adds "- 10:25pm <text>" under today in the journal, word for word, via a hook (no reply needed). If the hook did not handle it, run: `echo '{"prompt":"journal: <text>"}' | python3 "${CLAUDE_PLUGIN_ROOT}/scripts/archive.py" prompt`
- Save extra files outside the outputs folder: `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/archive.py" upload --session <session id> --folder <thread folder> <file> [...]`
- Look up past work: `.state/journal-days.json` holds every day; the user can also search in the viewer. Never print, echo or reveal the password or tokens in config.json.
