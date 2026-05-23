# GRE Word of the Day

Python script that emails daily GRE + "difficult" vocabulary via Gmail SMTP, run on a GitHub Actions cron schedule. Recipients get an HTML email each morning with a word, definition, phonetics, and (optionally) an LLM-generated example sentence.

## How it actually runs

- **Schedule:** `.github/workflows/daily.yml` defines `cron: "13 10,11 * * *"` — fires at 10:13 UTC AND 11:13 UTC daily. The script's internal hour-check picks the one that matches `send_hour_local` (6 AM America/New_York) and skips the other. This handles DST automatically.
- **Why :13 not :00:** GitHub Actions scheduled jobs are best-effort and frequently delayed or silently dropped at top-of-hour (especially :00 UTC) due to high contention. Minute :13 is a low-contention slot and gets dropped much less often. Shifted from :00 to :13 on 2026-05-23 after a missed send.
- **State:** `state.json` (committed in repo) tracks `last_sent_date` and recent word history (used to avoid repeats inside a configurable window). After a successful send, the workflow commits the updated `state.json` back via the `github-actions[bot]` user.

## Configuration

- `config.json` (in repo): `send_hour_local`, `timezone`, `default_word_count`, `recent_window_days`, `enable_llm_examples`, `recipients`.
- GitHub Actions secrets (in repo Settings → Secrets and variables → Actions):
  - `GMAIL_SENDER` — sender Gmail address
  - `GMAIL_APP_PASSWORD` — 16-char Gmail App Password (NOT the normal Gmail password)
  - `RECIPIENTS` — comma-separated emails (overrides config.json if set)
  - `ANTHROPIC_API_KEY` — for LLM example sentences (`claude-haiku-4-5`)

## Local commands

```sh
# Dry run — pick words and render the email, but don't send
python word_of_the_day.py --dry-run

# Run tests
pytest

# Send N words manually (locally)
GMAIL_SENDER=... GMAIL_APP_PASSWORD=... RECIPIENTS=... python word_of_the_day.py --count 2
```

For one-off **manual triggers in production**, prefer the GitHub Actions UI: Actions tab → "Word of the Day" → "Run workflow" button. That uses the production secrets and updates state.json properly.

## Diagnostic playbook — "I didn't get an email today"

1. **Check `state.json` in the repo** — `last_sent_date` is the source of truth. If today isn't there, no email was sent.
2. **Look at the Actions tab on GitHub:**
   - A **15-second** "success" run = took the "wrong hour" or "already sent today" skip path. Not an error, but didn't send.
   - A **25-40 second** success run = actually sent (full pipeline: dictionary lookup + LLM call + SMTP).
   - **Red X** = failure; click into the log for the error.
   - **Missing run entirely for today** = GitHub dropped the scheduled trigger. Fix: manually trigger via "Run workflow".
3. **Common failure causes** (in roughly descending likelihood):
   - GitHub silently dropped the scheduled run (most common)
   - Gmail App Password revoked or expired
   - `ANTHROPIC_API_KEY` revoked or expired
   - Email landed in spam (especially for new recipients)
   - dictionaryapi.dev rate-limited or down (script falls back gracefully — entry shows "Definition lookup unavailable")

## Important gotchas

- **The script handles all skip conditions silently with exit code 0** — they show as "success" in GitHub's UI. Always check `state.json` to verify a real send.
- **`git push` from the action requires `permissions: contents: write` in the workflow** — it's already set, but if you fork the repo, you'll need to set this in Settings → Actions → General → Workflow permissions.
- **LLM examples are cached per-word in `state.json`** — costs ~one Claude Haiku call per *unique* word ever. Very cheap.
- **`pages-build-deployment` workflow runs on every push** — it builds the GitHub Pages site at https://feldmana332.github.io/gre-word-of-the-day/ (a control panel for the app).

## History notes

- **Moved from `~/Dropbox/Claude Output/gre-word-of-the-day/` to `~/projects/gre-word-of-the-day/` on 2026-05-23.** Reason: Dropbox + git repos is unsafe (Dropbox can corrupt the `.git/` folder mid-operation when multiple machines sync, leading to data loss). GitHub is now the canonical sync layer across machines. The old Dropbox copy may still exist; safe to delete after verifying the fresh clone works.
- **2026-05-23:** Cron shifted from `"0 10,11 * * *"` to `"13 10,11 * * *"` after a missed send.
- **2026-05-22:** Added LLM-generated example sentences (Claude Haiku 4.5).

## Multi-machine workflow

This project lives in `~/projects/gre-word-of-the-day/` on each machine, synced via this GitHub repo. `git pull` when you sit down, `git push` after changes. Notably, the code only runs in *production* on GitHub Actions — your local copy is just for editing.
