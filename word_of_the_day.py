"""GRE Word of the Day — picks words, looks up definitions, emails subscribers."""

from __future__ import annotations

import argparse
import json
import os
import random
import smtplib
import sys
from datetime import date, datetime, timedelta, timezone
from email.message import EmailMessage
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

ROOT = Path(__file__).resolve().parent
CONFIG_PATH = ROOT / "config.json"
WORDS_PATH = ROOT / "words.txt"
DIFFICULT_PATH = ROOT / "difficult_words.txt"
STATE_PATH = ROOT / "state.json"

MW_URL = "https://www.merriam-webster.com/dictionary/{word}"
FREE_DICT_API = "https://api.dictionaryapi.dev/api/v2/entries/en/{word}"

LLM_MODEL = "claude-haiku-4-5"

# Sources used in word picks. Kept short so they fit neatly in email badges.
SOURCE_GRE = "gre"
SOURCE_DIFFICULT = "difficult"
SOURCE_LABELS = {SOURCE_GRE: "GRE", SOURCE_DIFFICULT: "Difficult"}


def load_config() -> dict:
    with open(CONFIG_PATH) as f:
        return json.load(f)


def load_word_file(path: Path) -> list[str]:
    """Load a one-word-per-line list, lowercased and stripped."""
    with open(path) as f:
        return [line.strip().lower() for line in f if line.strip()]


def load_words() -> list[str]:
    """Backward-compat wrapper that still loads the GRE list only."""
    return load_word_file(WORDS_PATH)


def load_state() -> dict:
    if not STATE_PATH.exists():
        return {"history": [], "last_sent_date": None}
    with open(STATE_PATH) as f:
        return json.load(f)


def save_state(state: dict) -> None:
    with open(STATE_PATH, "w") as f:
        json.dump(state, f, indent=2)
        f.write("\n")


def recent_words(state: dict, days: int) -> set[str]:
    cutoff = date.today() - timedelta(days=days)
    used: set[str] = set()
    for entry in state.get("history", []):
        try:
            entry_date = date.fromisoformat(entry["date"])
        except (KeyError, ValueError):
            continue
        if entry_date >= cutoff:
            used.update(entry.get("words", []))
    return used


def pick_words(all_words: list[str], avoid: set[str], count: int) -> list[str]:
    candidates = [w for w in all_words if w not in avoid]
    if len(candidates) < count:
        candidates = all_words[:]
    random.shuffle(candidates)
    return candidates[:count]


def pick_words_mixed(
    gre_pool: list[str],
    difficult_pool: list[str],
    avoid: set[str],
    count: int,
) -> list[tuple[str, str]]:
    """Pick `count` words split between the two lists.

    Rules:
      count == 1: 1 word, from the GRE list
      count == 2: 1 GRE + 1 Difficult
      count >= 3: (count - 1) GRE + 1 Difficult

    Returns a list of (word, source) tuples in the order they should appear
    in the email. Difficult word(s) come last so the harder material is read
    after the easier warm-up.
    """
    if count <= 1:
        return [(w, SOURCE_GRE) for w in pick_words(gre_pool, avoid, 1)]
    num_difficult = 1
    num_gre = max(1, count - num_difficult)
    gre = pick_words(gre_pool, avoid, num_gre)
    # Make sure a difficult word isn't accidentally the same as one of the
    # GRE picks (possible if the two lists overlap).
    diff = pick_words(difficult_pool, avoid | set(gre), num_difficult)
    return [(w, SOURCE_GRE) for w in gre] + [(w, SOURCE_DIFFICULT) for w in diff]


# ---------------------------------------------------------------------------
# LLM-generated example sentences (optional, controlled by config + api key)
# ---------------------------------------------------------------------------
# generate_example_sentence makes ONE Claude Haiku call per word. The result
# is cached in state.json under "examples", keyed by word, so each word costs
# at most one API call across the lifetime of the project. The wrapper
# get_or_generate_example handles the cache lookup; main() calls it.
#
# Designed to NEVER crash the email pipeline. Any error returns None and the
# email goes out with just the dictionary content.

def generate_example_sentence(
    word: str,
    definition: str,
    api_key: str,
    *,
    timeout_seconds: float = 15.0,
) -> str | None:
    """Generate one example sentence using `word`. Returns None on any failure."""
    if not (api_key and word):
        return None

    # Import locally so the script still runs when LLM examples are disabled
    # and the anthropic package isn't installed.
    try:
        import anthropic
    except ImportError:
        print("[warn] anthropic package not installed; skipping LLM example.")
        return None

    defn = (definition or "").strip()
    if len(defn) > 500:
        defn = defn[:500] + "..."

    client = anthropic.Anthropic(
        api_key=api_key,
        timeout=timeout_seconds,
        max_retries=2,  # SDK auto-retries 429 and 5xx with exponential backoff
    )

    try:
        msg = client.messages.create(
            model=LLM_MODEL,
            max_tokens=200,
            system=(
                "You write a single example sentence demonstrating a vocabulary word "
                "in natural context. Output ONLY the sentence itself — no quotes around "
                "it, no preamble like 'Here is an example:', no explanation. The sentence "
                "should be memorable, natural-sounding, and clearly convey the word's "
                "meaning through context. Aim for 15-25 words."
            ),
            messages=[
                {
                    "role": "user",
                    "content": (
                        f"Word: {word}\n"
                        f"Definition: {defn}\n\n"
                        f'Write one example sentence using "{word}".'
                    ),
                }
            ],
        )
    except anthropic.APIError as e:
        # Covers RateLimitError, AuthenticationError, BadRequestError, etc.
        print(f"[warn] LLM example failed for {word!r}: {type(e).__name__}: {e}")
        return None
    except Exception as e:
        # Defensive — never crash the pipeline.
        print(f"[warn] LLM example unexpected error for {word!r}: {type(e).__name__}: {e}")
        return None

    for block in msg.content:
        if getattr(block, "type", None) == "text":
            sentence = block.text.strip().strip('"“”').strip()
            return sentence or None
    return None


def get_or_generate_example(
    word: str,
    definition: str,
    state: dict,
    api_key: str | None,
) -> str | None:
    """Return a cached example if present, else generate and cache. Mutates `state`."""
    if not api_key:
        return None
    cache = state.setdefault("examples", {})
    cached = cache.get(word)
    if cached and cached.get("sentence"):
        return cached["sentence"]
    sentence = generate_example_sentence(word, definition, api_key)
    if sentence:
        cache[word] = {
            "sentence": sentence,
            "model": LLM_MODEL,
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }
    return sentence


def _best_definition_for_word(words_data_entry: dict) -> str:
    """Extract the first definition string for a word, for use in LLM prompts."""
    for entry in words_data_entry.get("entries", []):
        for d in entry.get("definitions", []):
            text = d.get("definition", "")
            if text:
                return text
    return ""


def lookup_definition(word: str, source: str = SOURCE_GRE) -> dict:
    """Return a dict with keys: word, source, phonetic, entries, source_url, lookup_ok."""
    out = {
        "word": word,
        "source": source,
        "phonetic": None,
        "entries": [],
        "source_url": MW_URL.format(word=word),
        "lookup_ok": False,
    }
    try:
        resp = requests.get(FREE_DICT_API.format(word=word), timeout=15)
        if resp.status_code != 200:
            return out
        data = resp.json()
        if not isinstance(data, list) or not data:
            return out
        first = data[0]
        out["phonetic"] = first.get("phonetic") or next(
            (p.get("text") for p in first.get("phonetics", []) if p.get("text")), None
        )
        for entry in data:
            for meaning in entry.get("meanings", []):
                pos = meaning.get("partOfSpeech", "")
                defs = []
                for d in meaning.get("definitions", []):
                    defs.append(
                        {
                            "definition": d.get("definition", ""),
                            "example": d.get("example"),
                        }
                    )
                out["entries"].append({"pos": pos, "definitions": defs})
        out["lookup_ok"] = bool(out["entries"])
    except (requests.RequestException, ValueError):
        pass
    return out


def _badge_html(source: str) -> str:
    """Small colored pill above each word indicating which list it came from."""
    if source == SOURCE_DIFFICULT:
        bg, fg = "#7d1f2c", "#fff5f6"   # deep crimson — visually distinct from GRE
        label = "Difficult Word"
    else:
        bg, fg = "#1a2a44", "#eaf0fb"   # navy
        label = "GRE Word"
    return (
        f'<span style="display:inline-block;background:{bg};color:{fg};'
        f'font-size:11px;font-weight:700;letter-spacing:1px;text-transform:uppercase;'
        f'padding:4px 10px;border-radius:12px;margin-bottom:8px;">{label}</span>'
    )


def render_html(words_data: list[dict]) -> str:
    rows = []
    for w in words_data:
        sections = []
        sections.append(_badge_html(w.get("source", SOURCE_GRE)))
        sections.append(
            f'<h2 style="margin-bottom:4px;color:#1a2a44;font-family:Georgia,serif;font-size:32px;">{w["word"]}</h2>'
        )
        if w.get("phonetic"):
            sections.append(
                f'<div style="color:#666;font-style:italic;margin-bottom:12px;">{w["phonetic"]}</div>'
            )
        if w["entries"]:
            for entry in w["entries"]:
                sections.append(
                    f'<div style="color:#1a2a44;font-weight:bold;margin-top:14px;text-transform:lowercase;font-variant:small-caps;">{entry["pos"]}</div>'
                )
                sections.append('<ol style="margin-top:4px;padding-left:24px;">')
                for d in entry["definitions"][:4]:
                    item = f'<li style="margin-bottom:6px;">{d["definition"]}'
                    if d.get("example"):
                        item += f'<div style="color:#555;font-style:italic;margin-top:2px;">&ldquo;{d["example"]}&rdquo;</div>'
                    item += "</li>"
                    sections.append(item)
                sections.append("</ol>")
        else:
            sections.append(
                '<div style="color:#a33;margin-top:8px;">Definition lookup unavailable — see source link below.</div>'
            )
        if w.get("llm_example"):
            sections.append(
                '<div style="margin-top:16px;padding:12px 16px;background:#f0f7ff;border-left:3px solid #1a73e8;border-radius:4px;">'
                '<div style="font-size:11px;font-weight:700;letter-spacing:1px;text-transform:uppercase;color:#1a73e8;margin-bottom:4px;">In context</div>'
                f'<div style="color:#24292e;font-style:italic;">{w["llm_example"]}</div>'
                "</div>"
            )
        sections.append(
            f'<div style="margin-top:16px;"><a href="{w["source_url"]}" style="color:#1a73e8;text-decoration:none;">View on Merriam-Webster &rarr;</a></div>'
        )
        rows.append(
            '<div style="background:#fff;padding:24px;border:1px solid #e1e4e8;border-radius:8px;margin-bottom:16px;">'
            + "\n".join(sections)
            + "</div>"
        )
    today_str = datetime.now(ZoneInfo("America/New_York")).strftime("%A, %B %d, %Y")
    # Header text adapts to whether we sent a mixed batch.
    has_difficult = any(w.get("source") == SOURCE_DIFFICULT for w in words_data)
    has_gre = any(w.get("source", SOURCE_GRE) == SOURCE_GRE for w in words_data)
    if has_difficult and has_gre:
        header_label = "GRE &amp; Difficult Words of the Day"
    elif has_difficult:
        header_label = "Difficult Word of the Day"
    else:
        header_label = "GRE Word of the Day"
    return (
        '<div style="background:#f6f8fa;padding:24px;font-family:-apple-system,BlinkMacSystemFont,sans-serif;color:#24292e;">'
        f'<div style="max-width:600px;margin:0 auto;">'
        f'<div style="color:#666;font-size:13px;margin-bottom:16px;text-transform:uppercase;letter-spacing:1px;">{header_label} &middot; {today_str}</div>'
        + "".join(rows)
        + '<div style="color:#999;font-size:12px;margin-top:8px;text-align:center;">Sent by your Word of the Day pipeline.</div>'
        "</div></div>"
    )


def render_text(words_data: list[dict]) -> str:
    lines = []
    today_str = datetime.now(ZoneInfo("America/New_York")).strftime("%A, %B %d, %Y")
    has_difficult = any(w.get("source") == SOURCE_DIFFICULT for w in words_data)
    has_gre = any(w.get("source", SOURCE_GRE) == SOURCE_GRE for w in words_data)
    if has_difficult and has_gre:
        title = "GRE & Difficult Words of the Day"
    elif has_difficult:
        title = "Difficult Word of the Day"
    else:
        title = "GRE Word of the Day"
    lines.append(f"{title}  -  {today_str}")
    lines.append("=" * 60)
    for w in words_data:
        lines.append("")
        label = SOURCE_LABELS.get(w.get("source", SOURCE_GRE), "Word")
        lines.append(f"[{label.upper()} WORD]")
        header = w["word"].upper()
        if w.get("phonetic"):
            header += f"  {w['phonetic']}"
        lines.append(header)
        lines.append("-" * len(header))
        if w["entries"]:
            for entry in w["entries"]:
                lines.append(f"\n[{entry['pos']}]")
                for i, d in enumerate(entry["definitions"][:4], 1):
                    lines.append(f"  {i}. {d['definition']}")
                    if d.get("example"):
                        lines.append(f'     "{d["example"]}"')
        else:
            lines.append("(Definition unavailable — see source link.)")
        if w.get("llm_example"):
            lines.append("")
            lines.append("In context:")
            lines.append(f"  {w['llm_example']}")
        lines.append(f"\nSource: {w['source_url']}")
        lines.append("")
    return "\n".join(lines)


def send_email(
    sender: str,
    password: str,
    recipients: list[str],
    subject: str,
    html_body: str,
    text_body: str,
) -> None:
    """Send one email per recipient (better deliverability than a single multi-To message)."""
    with smtplib.SMTP("smtp.gmail.com", 587) as smtp:
        smtp.starttls()
        smtp.login(sender, password.replace(" ", ""))
        for recipient in recipients:
            msg = EmailMessage()
            msg["From"] = sender
            msg["To"] = recipient
            msg["Subject"] = subject
            msg.set_content(text_body)
            msg.add_alternative(html_body, subtype="html")
            smtp.send_message(msg)


def build_subject(picks: list[tuple[str, str]]) -> str:
    """`picks` is a list of (word, source) tuples — same shape pick_words_mixed returns."""
    words = [w for w, _ in picks]
    has_difficult = any(s == SOURCE_DIFFICULT for _, s in picks)
    has_gre = any(s == SOURCE_GRE for _, s in picks)
    if has_difficult and has_gre:
        prefix = "GRE & Difficult Words of the Day"
    elif has_difficult:
        prefix = "Difficult Word of the Day"
    else:
        prefix = "GRE Word of the Day" if len(words) == 1 else "GRE Words of the Day"
    return f"{prefix}: " + ", ".join(words)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--count",
        type=int,
        default=None,
        help="Number of words to send (overrides config default).",
    )
    parser.add_argument(
        "--trigger",
        choices=["scheduled", "manual"],
        default="manual",
        help="Whether this run is scheduled (gated by hour-of-day) or manual.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Pick words and render the email but don't actually send.",
    )
    args = parser.parse_args()

    config = load_config()
    tz = ZoneInfo(config.get("timezone", "America/New_York"))
    now_local = datetime.now(tz)

    if args.trigger == "scheduled":
        if now_local.hour != int(config["send_hour_local"]):
            print(
                f"[skip] Scheduled run fired at {now_local.isoformat()} but send_hour_local={config['send_hour_local']}; not sending."
            )
            return 0

    state = load_state()

    if (
        args.trigger == "scheduled"
        and state.get("last_sent_date") == now_local.date().isoformat()
    ):
        print(f"[skip] Already sent today ({state['last_sent_date']}).")
        return 0

    word_count = args.count if args.count is not None else int(config["default_word_count"])
    word_count = max(1, min(word_count, 5))

    gre_pool = load_word_file(WORDS_PATH)
    difficult_pool = load_word_file(DIFFICULT_PATH) if DIFFICULT_PATH.exists() else []
    avoid = recent_words(state, int(config["recent_window_days"]))

    if difficult_pool:
        picks = pick_words_mixed(gre_pool, difficult_pool, avoid, word_count)
    else:
        # Fallback if the difficult list is missing — single-source GRE picks.
        picks = [(w, SOURCE_GRE) for w in pick_words(gre_pool, avoid, word_count)]
    print(f"[pick] {[(w, s) for w, s in picks]}")

    words_data = [lookup_definition(w, source=s) for w, s in picks]
    for w in words_data:
        if not w["lookup_ok"]:
            print(f"[warn] Definition lookup failed for: {w['word']}")

    # LLM-generated example sentences (optional). Cached per-word in state.json
    # so each word costs at most one Claude call ever.
    if config.get("enable_llm_examples"):
        anthropic_key = os.environ.get("ANTHROPIC_API_KEY")
        if anthropic_key:
            for w in words_data:
                defn = _best_definition_for_word(w)
                example = get_or_generate_example(w["word"], defn, state, anthropic_key)
                if example:
                    w["llm_example"] = example
                    print(f"[llm] {w['word']}: {example}")
                else:
                    print(f"[llm] {w['word']}: (no example available)")
        else:
            print("[llm] enable_llm_examples=true but ANTHROPIC_API_KEY not set; skipping.")

    html = render_html(words_data)
    text = render_text(words_data)
    subject = build_subject(picks)

    if args.dry_run:
        print("[dry-run] Subject:", subject)
        print("[dry-run] Text body:\n")
        print(text)
        return 0

    sender = os.environ.get("GMAIL_SENDER")
    password = os.environ.get("GMAIL_APP_PASSWORD")
    if not sender or not password:
        print("[error] GMAIL_SENDER and GMAIL_APP_PASSWORD env vars are required.", file=sys.stderr)
        return 2

    recipients_override = os.environ.get("RECIPIENTS")
    if recipients_override:
        recipients = [r.strip() for r in recipients_override.split(",") if r.strip()]
    else:
        recipients = list(config.get("recipients", []))
    if not recipients:
        print(
            "[error] No recipients configured. Set the RECIPIENTS secret (comma-separated emails) or populate recipients in config.json.",
            file=sys.stderr,
        )
        return 3

    print(f"[send] To: {recipients}  Subject: {subject}")
    send_email(sender, password, recipients, subject, html, text)
    print("[ok] Sent.")

    state.setdefault("history", []).append(
        {
            "date": now_local.date().isoformat(),
            "words": [w for w, _ in picks],
            "sources": [s for _, s in picks],
        }
    )
    state["last_sent_date"] = now_local.date().isoformat()
    cutoff = (now_local.date() - timedelta(days=int(config["recent_window_days"]) * 2)).isoformat()
    state["history"] = [h for h in state["history"] if h.get("date", "") >= cutoff]
    save_state(state)
    return 0


if __name__ == "__main__":
    sys.exit(main())
