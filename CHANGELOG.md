# Changelog

## v1.1.1 (10-24-2026)

- New screenshots of the viewer, with made-up example data: Journal, file pane, Projects with a thread chain, and the new Tokens tab.
- README: describes thread chains and the Tokens tab next to the screenshots.
- No code changes: plugin 2.3.2 and viewer 1.15.0, same as v1.1.0.

## v1.1.0 (10-24-2026)

Plugin 2.3.2 and viewer 1.15.0.

- Thread chains: threads of one project are numbered (`recipe-app-v1`, `-v2`, ...). Paste `continue recipe-app-v3` as the only message in a new thread and Claude loads the handoff doc and continues the work. The viewer shows the chain name next to each thread and keeps a chain's threads together on the Projects tab.
- Size line: after each reply the plugin shows the thread size (for example `110K`). A thread that has no name yet shows `<size>K send handoff`.
- Tokens tab: tokens used per day, project and thread, split into starting context, archive plugin and your work. The plugin reads these numbers from the thread's transcript, with no extra Claude call.
- Example names in comments and docs are made up.
