# GRE Word of the Day

Sends a GRE-level vocabulary word (or a few) to a list of email recipients every
morning at 6 AM US Eastern, with definitions and a link back to Merriam-Webster.
Runs entirely on GitHub Actions — no machine of yours needs to be on.

## How it works

- **Schedule.** GitHub Actions fires daily at both 10:00 and 11:00 UTC. The script
  checks the current time in `America/New_York` and only sends when the local
  hour matches `send_hour_local` (default `6`). This handles EST/EDT transitions
  automatically.
- **Word selection.** A word is picked at random from [`words.txt`](words.txt)
  (GRE list) or [`difficult_words.txt`](difficult_words.txt) (more obscure
  vocabulary), excluding any used in the last `recent_window_days` (default
  `30`). When more than one word is sent, the script mixes sources:
    - 1 word: 1 GRE
    - 2 words: 1 GRE + 1 Difficult
    - 3+ words: (count − 1) GRE + 1 Difficult
  The email shows a small badge above each word marking its source.
- **Definition lookup.** Pulled from the free dictionaryapi.dev. If lookup fails,
  the email still goes out with the Merriam-Webster link as the source of truth.
- **State.** Recently-sent words are tracked in `state.json`, which the workflow
  commits back to the repo after each run.

## Changing settings

Most settings live in [`config.json`](config.json) — recipients, default word
count, the morning send hour, and the no-repeat window. Edit it directly on
github.com (pencil icon), commit the change on the main branch, and the next run
picks it up. No code changes required.

Sensitive values live in repository **Secrets**
(Settings &rarr; Secrets and variables &rarr; Actions):

- `GMAIL_SENDER` — the Gmail address used as the From: line
- `GMAIL_APP_PASSWORD` — a Gmail app password (16 chars, spaces optional)
- `RECIPIENTS` — comma-separated email addresses (the people who get the
  daily word). Kept in secrets so the public repo doesn't leak addresses.

## Manual trigger (any device)

Go to the [**Actions tab**](../../actions/workflows/daily.yml), click
**"Run workflow"**, optionally enter a `word_count` between 1 and 5, and hit
Run. Works on mobile browsers too.

There's also a small **control panel** page hosted on GitHub Pages —
see [`docs/index.html`](docs/index.html). Once Pages is enabled for this repo,
the panel lives at `https://<your-username>.github.io/gre-word-of-the-day/`.

## Local testing

```bash
pip install -r requirements.txt
GMAIL_SENDER='you@gmail.com' GMAIL_APP_PASSWORD='abcd efgh ijkl mnop' \
  python word_of_the_day.py --trigger manual --count 1
```

Add `--dry-run` to see the rendered email without sending it.

## Word lists

Both lists are one-word-per-line plain text:

- [`words.txt`](words.txt) — ~400 standard GRE-prep words
- [`difficult_words.txt`](difficult_words.txt) — ~800 more obscure entries
  (archaic, scientific, legal Latin, literary). Used only when more than one
  word is sent in a single email.

Edit either file on github.com to add or remove entries. Matching against
`state.json` is case-insensitive.
