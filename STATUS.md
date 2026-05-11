# gmail-cleaner-ai status

Last updated: 2026-05-11

## TL;DR

Build is done. Phase 9 shipped 7 commits, 33 tests green, working tree clean. The thing that's blocking a real-inbox run is on your side: drop your Gmail App Password into `.env` and you can drive the four-card flow end-to-end.

---

## Finished

### Phase 9 setup (9ffc88a)

Set up the test infrastructure that was missing. `tests/` folder, `conftest.py`, `requirements-dev.txt`, baseline tests for pure helpers.

### Phase 9a, apply correctness (7575b5f)

The four bugs that could have damaged real mail.

- IMAP search now uses `X-GM-RAW "from:exact@addr"`. The old plain `FROM` is substring-match, so `info@example.com` would have also matched `info@example.com.attacker`. On the Trash path that's a real footgun.
- Scope filter uses `__NONE__` sentinel for "user unchecked every box". The old code sent `""`, which `triage.py` was reading as "no filter, process everything", so unchecking all boxes silently ran on every sender.
- `STORE` and `MOVE` return codes are now checked per sender. Failures get an `ERR` line in the log and a count in the final summary, instead of being silently swallowed.
- `export-filters` reads from the edited `allowed.txt` / `disallowed.txt` instead of the stale `proposed_categories.json` that's never regenerated after a user edits the lists in the UI.

### Phase 9b, robustness (10ae7bc)

- `classify_batch` retries three times with exponential backoff. One transient 429 used to drop a 50-sender batch silently.
- `imap_connect` sets a 60s socket timeout. No more infinite hang on a flaky network.
- Apply log opens in append mode and flushes per sender. Ctrl-C mid-loop now preserves an accurate log on disk.
- Mode 3 body excerpts skip senders that match security patterns: `noreply`, `security`, `verify`, `verification`, `auth`, `2fa`, `otp`, `mfa`, `password`, `accounts.google.com`. Means OTPs and reset codes never reach the LLM.

### Phase 9c, UX polish (14bcd30)

- `CONTEXT.md` aligned with the LiteLLM stack and the mode-3 privacy notes.
- Reset expander caption now mentions that `categories.json` is preserved.
- Cost preview caption above the classify button. Uses `litellm.token_counter` + `model_cost`. Falls back to "input tokens only, cost unavailable" for local or unknown models.
- New `undo` command. Reads the last apply session from `applied.log` and moves trashed senders back from Trash to All Mail. Wired up as a CLI subcommand and a Card 4 expander.
- `README.md` and `demos/README.md` rewritten so a fresh user knows the screenshot is intentionally absent and how to drop one.
- `triage.py` module docstring + the `analyze` subcommand help text caught up with the LiteLLM swap.

### Phase 9d, docs alignment (c14b698)

The audit caught a pile of stale references from the LiteLLM swap.

- README "Add a custom provider" section replaced. The old recipe told users to subclass `Classifier` and register in a `PROVIDERS` dict that doesn't exist anymore. The new version shows the real path: set `LLM_MODEL` to any LiteLLM-supported model name.
- README quick-start says `LLM_MODEL`, not the dead `LLM_PROVIDER`.
- README CLI example output matches what `triage.py` actually prints.
- README pipeline diagram dropped the 4-provider enumeration.
- `install.sh` next-steps lists more providers and points at `.env.example` / LiteLLM docs for the full list.
- `specs/2026-05-08-design.md` got a v3 status note documenting the swap.

### Phase 9e, user surface finalized (be7ad72)

- `.env.example` rewritten end-to-end for the LiteLLM stack: `LLM_MODEL` with prefix examples, `LLM_BASE_URL` for local servers, all seven cloud-provider key URLs inline, `GEMINI_API_KEY` (fixed a mismatch with the UI's PRESETS dict).
- README CLI walkthrough now shows `apply --dry-run`, `apply`, `undo`, and `export-filters`. Previously it stopped at `analyze`.
- New "Running tests" section in README.
- Removed local `data/demo@example.com/` and `data/test@example.com/` scaffolds (gitignored, leftover from development).

### History feature (7a03ccd)

Snapshot the decision files and the filter export per run.

- Snapshots land at `data/<account>/history/<YYYY-MM-DD_HHMMSS>/`. Plain files, no manifest, no metadata schema, the directory name is the id.
- Contains: `allowed.txt`, `disallowed.txt`, `proposed_categories.json`, `filters.xml` (if present at save time), plus optional `label.txt` for a one-line note.
- Inventory is not snapshotted because it's reproducible by re-scanning and would balloon the snapshot size.
- 4 CLI subcommands: `history-save`, `history-list`, `history-restore`, `history-delete`.
- Card 5 in the UI, below Card 4. Save form + list + restore-and-delete behind expanders. Restore overwrites the current files; delete is permanent. Both gated by the same confirm-checkbox pattern Card 4's "Apply LIVE" uses.

---

## Open / next

### What's blocking a real-inbox run

**Just one thing:** your `.env` doesn't have `GMAIL_ACCOUNT_1=you@gmail.com` + `GMAIL_APPPASS_1=...`. Two ways to fix:

- UI path: Card 1 → "gmail accounts" form. Writes to `.env` for you.
- Manual path: open `~/development/gmail-cleaner-ai/.env`, add the two lines.

Once that's done, the flow is:
1. Card 2 → Scan inbox (re-runs inventory with the current schema; the old `inventory.json` predates phase 3 and is missing fields).
2. Card 2 → Classify (the LLM call; ~$0.10–0.20 on Opus for ~200 senders).
3. Card 3 → review the two tables, edit anything the model got wrong.
4. Card 5 → save a snapshot before going destructive.
5. Card 4 → Dry-run, check the print log, then check "I understand" and click Apply LIVE.
6. Card 4 → optional: generate `filters.xml` and import once in Gmail Settings → Filters → Import filters.
7. Card 4 → if something looks wrong: open the "undo last apply" expander.

### Deferred during phase 9 (won't block the real-inbox run)

- Resume support for inventory (saved batch progress so a 50k-inbox interrupt doesn't restart from zero).
- `CHANGELOG.md` + a first version tag (`v0.1.0`).
- GitHub Actions CI (`pytest` + `ruff` on push).
- Issue and PR templates.
- IMAP body-fetch parallelism in mode 3 (currently sequential, hundreds of round trips at scale).
- Consolidate `parse_list_file` between `app.py` and `triage.py`. They've already drifted apart slightly.
- Sample data in `demos/` after the first sanitized run.
- Demo screenshot (`demos/screenshot-streamlit.png`).

### Possible future features (not in scope unless you ask)

- Auto-snapshot before destructive apply. Right now you have to remember to save first.
- Diff view between two snapshots.
- Cost-preview accuracy: current output-token estimate is a conservative upper bound.
- Per-account default category schema so you don't re-classify the schema every run.

---

## Where things live

- `triage.py` — single-file CLI (~890 lines). All commands.
- `app.py` — Streamlit UI (~1280 lines). Five cards.
- `lib/classifier.py` — LiteLLM wrapper with retry/backoff.
- `tests/` — 33 pytest tests across 6 files.
- `data/<account>/` — per-account working files. Gitignored.
- `data/<account>/history/<stamp>/` — snapshots from the history feature.
- `data/<account>/applied.log` — per-session apply + undo audit log.
- `.env` — credentials, gitignored.
- `.env.example` — template, committed.
- `specs/2026-05-08-design.md` — design doc with v3 status note.
- `STATUS.md` — this file.

---

## How to pick up from cold start

```bash
cd ~/development/gmail-cleaner-ai

# 1. Streamlit UI (preferred):
.venv/bin/streamlit run app.py --server.headless true --server.port 8501
# Open http://localhost:8501

# 2. Or CLI, one account end-to-end:
python3 triage.py inventory you@gmail.com
python3 triage.py analyze you@gmail.com
python3 triage.py apply you@gmail.com --dry-run
python3 triage.py apply you@gmail.com
python3 triage.py history-save you@gmail.com --label "first real run"

# 3. Tests:
python3 -m pytest tests/
```

---

## Commit log for phase 9

```
7a03ccd add history: snapshot decision files and filter export per run
be7ad72 phase 9e: finalize user-facing surface
c14b698 phase 9d: align user-facing docs with the litellm stack
14bcd30 phase 9c: ux polish
10ae7bc phase 9b: robustness fixes
7575b5f phase 9a: apply correctness fixes
9ffc88a phase 9: set up pytest and baseline helper tests
```

7 commits ahead of `origin/master`. Not pushed yet; do that when the real-inbox run confirms nothing's broken.
