# AGENTS.md

Working-style rules for agents in this repo.

## Communicating with the user

Niall is often using voice transcription, so his messages contain transcription
errors — mangled product/tool names and homophones especially. Read for intent,
not literal spelling, and silently map garbled terms to the obvious target (e.g.
"low century" → Sentry, "post-hoc"/"post hog" → PostHog, "clause.md" → CLAUDE.md).
If a garbled term is genuinely ambiguous and the choice matters, ask; otherwise
just infer it and carry on.

Keep replies short and plain. No walls of text. Lead with the answer or the action.
When the user needs to do something, give numbered steps in a few words each.
Skip background, caveats, and explanation unless asked. Pushed? Say "Yes, pushed."
Save deeper detail for when they explicitly ask "why".

## Don't re-verify what hasn't changed

Verify a thing **once**, then move on. Do NOT re-run the same build / type-check /
lint / smoke-test again when nothing has changed since it last passed — that's
wasted time, and it's infuriating. Re-check only after an actual code change that
could affect the result. One green run is enough.

## Git Workflow

**Commit and push your work by default — don't wait to be told, and DON'T ASK.** When you finish a change (and it builds), commit it with a clear message and `git push` — just do it, do not ask "want me to commit and push?". This is the expected default; only skip committing when explicitly told to in that moment. Don't leave finished work sitting uncommitted in the working tree.

**NEVER `git add -A`, `git add .`, `git add -u`, or `git commit -a`/`-am`.** This working tree may be shared with other concurrent sessions and git worktrees — a blanket add sweeps their untracked WIP (stray test files, scratch files, half-finished work) straight into your commit. Always stage **only the exact files you changed, by explicit path**: run `git status` first, then `git add path/to/file1 path/to/file2 …`. If you regenerated a file, add it by name too. Before every commit, eyeball `git status`/`git diff --cached` and confirm every staged path is one you actually touched — if you see a file you didn't write, do NOT commit it.

**If an audit/review turns up a real fix, just make it — don't ask "want me to fix it?".** When you find a concrete bug or improvement, apply it, verify it builds, commit, and push. Reporting a problem and then asking permission to fix it is the same as asking to commit — don't. Fix forward and ship. Only stop to ask when there's a genuine either/or decision that's actually Niall's to make (e.g. which of two incompatible behaviours he wants), not for permission to do the obviously-correct thing.

**Just commit and push — do NOT `git pull --rebase` preemptively.** Commit your work and run `git push` directly. Only if the push is *rejected* as non-fast-forward do you then `git pull --rebase` (or `git rebase origin/main`) and push again. Pulling/rebasing before a push has been rejected is a waste of time — don't do it.

**Integrating upstream changes uses rebase, never merge.** Bringing `main` (or any remote branch) *into* your branch is always `git rebase` — `git pull` must rebase, never `git merge`.

**Landing a PR is different — a merge commit is fine, but never squash.** Merging a feature branch's PR into `main` may use a merge commit (`gh pr merge --merge`). **Never squash** (`--squash` is forbidden) — keep every commit.

Never `git push -f` — ask first if a force push seems necessary (a rebase that rewrote already-pushed history needs `--force-with-lease`).

**Never `git revert` (and never any history-rewriting/undo git command without asking).** Other devs work in this repo and may have concurrent changes. To undo something, fix forward in the working tree — don't run `git revert`, `git reset --hard`, `git checkout -- <file>`, or restore old commits. If an undo genuinely needs a git command, ask first.

**Never `git reset` (any form).** Not `--hard`, not `--soft`, not to unstage. To unstage use `git restore --staged <file>`; to undo, fix forward. `git reset` is forbidden.

**If you stash, you MUST pop in the same command line — never leave a stash sitting.** A dangling stash (or a gap between stash and pop) corrupts concurrent sessions' working state. Always chain it atomically, e.g. `git stash && git pull --rebase && git push; git stash pop` on one line. Never run a bare `git stash` and pop "later" in a separate step.

### Sandboxed push failures

- Sandboxed `git push` may fail with GitHub credential errors such as:
  - `could not read Password for 'https://...': Device not configured`
  - invalid `gh auth` tokens
- When that happens, do not stop and complain about GitHub auth. Retry the push outside the sandbox (escalated, with the justification that the push needs the host Git credentials). The normal host environment can push successfully even when sandboxed GitHub auth fails.
- Only ask the user for help if the escalated push also fails.

## CLI / MCP / API / Docs parity

The REST API, both MCP servers (remote `magpie/mcp/server.py` + local stdio
`cli/src/mcp.ts`), both CLIs (Python `magpie/cli/main.py` server-ops + TS
`cli/src` user client), and the docs are one surface — keep them in lockstep.
Change a capability → update every surface it belongs on, and its docs, in the
same change. Business logic is single-sourced server-side (REST + the shared
`magpie/sync.py`/`bundle.py`/`export.py` helpers); clients stay thin. A
user-facing feature isn't done until it's documented. Public docs are Mintlify
under `docs/site/` — the content root must stay `docs/site/` so `docs/plans/`
(internal) never publishes. Full detail in `CLAUDE.md`; keep the two in sync.

## Autonomy

- Default to doing the work end-to-end. Do not pause to ask for confirmation when the next step is obvious from the user's goal.
- If implementation details are open, make a conservative choice that fits the existing codebase and keep going.
- Ask the user only when continuing would be destructive, security-sensitive, or genuinely blocked by missing information that cannot be discovered locally.
- For multi-step product work, take the next valuable slice, implement it, verify it, commit it, and push it.
