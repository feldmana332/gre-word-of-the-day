"""GRE Word of the Day — picks words, looks up definitions, emails subscribers."""

from __future__ import annotations

import argparse
import json
import os
import random
import smtplib
import sys
from datetime import date, datetime, timedelta
from email.message import EmailMessage
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

ROOT = Path(__file__).resolve().parent
CONFIG_PATH = ROOT / "config.json"
WORDS_PATH = ROOT / "words.txt"
STATE_PATH = ROOT / "state.json"

MW_URL = "https://www.merriam-webster.com/dictionary/{word}"
FREE_DICT_API = "https://api.dictionaryapi.dev/api/v2/entries/en/{word}"


def load_config() -> dict:
    with open(CONFIG_PATH) as f:
        return json.load(f)


def load_words() -> list[str]:
    with open(WORDS_PATH) as f:
        return [line.strip().lower() for line in f if line.strip()]


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


def lookup_definition(word: str) -> dict:
    """Return a dict with keys: word, phonetic, entries (list of {pos, definitions:[{def,example}], etymology}), source_url."""
    out = {
        "word": word,
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


def render_html(words_data: list[dict]) -> str:
    rows = []
    for w in words_data:
        sections = []
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
        sections.append(
            f'<div style="margin-top:16px;"><a href="{w["source_url"]}" style="color:#1a73e8;text-decoration:none;">View on Merriam-Webster &rarr;</a></div>'
        )
        rows.append(
            '<div style="background:#fff;padding:24px;border:1px solid #e1e4e8;border-radius:8px;margin-bottom:16px;">'
            + "\n".join(sections)
            + "</div>"
        )
    today_str = datetime.now(ZoneInfo("America/New_York")).strftime("%A, %B %d, %Y")
    return (
        '<div style="background:#f6f8fa;padding:24px;font-family:-apple-system,BlinkMacSystemFont,sans-serif;color:#24292e;">'
        f'<div style="max-width:600px;margin:0 auto;">'
        f'<div style="color:#666;font-size:13px;margin-bottom:16px;text-transform:uppercase;letter-spacing:1px;">GRE Word of the Day &middot; {today_str}</div>'
        + "".join(rows)
        + '<div style="color:#999;font-size:12px;margin-top:8px;text-align:center;">Sent by your GRE Word of the Day pipeline.</div>'
        "</div></div>"
    )


def render_text(words_data: list[dict]) -> str:
    lines = []
    today_str = datetime.now(ZoneInfo("America/New_York")).strftime("%A, %B %d, %Y")
    lines.append(f"GRE Word of the Day  -  {today_str}")
    lines.append("=" * 60)
    for w in words_data:
        lines.append("")
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
    msg = EmailMessage()
    msg["From"] = sender
    msg["To"] = ", ".join(recipients)
    msg["Subject"] = subject
    msg.set_content(text_body)
    msg.add_alternative(html_body, subtype="html")
    with smtplib.SMTP("smtp.gmail.com", 587) as smtp:
        smtp.starttls()
        smtp.login(sender, password.replace(" ", ""))
        smtp.send_message(msg)


def build_subject(words: list[str]) -> str:
    label = "Word" if len(words) == 1 else "Words"
    return f"GRE {label} of the Day: " + ", ".join(words)


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

    words_list = load_words()
    avoid = recent_words(state, int(config["recent_window_days"]))
    chosen = pick_words(words_list, avoid, word_count)
    print(f"[pick] {chosen}")

    words_data = [lookup_definition(w) for w in chosen]
    for w in words_data:
        if not w["lookup_ok"]:
            print(f"[warn] Definition lookup failed for: {w['word']}")

    html = render_html(words_data)
    text = render_text(words_data)
    subject = build_subject(chosen)

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
        recipients = list(config["recipients"])

    print(f"[send] To: {recipients}  Subject: {subject}")
    send_email(sender, password, recipients, subject, html, text)
    print("[ok] Sent.")

    state.setdefault("history", []).append(
        {"date": now_local.date().isoformat(), "words": chosen}
    )
    state["last_sent_date"] = now_local.date().isoformat()
    cutoff = (now_local.date() - timedelta(days=int(config["recent_window_days"]) * 2)).isoformat()
    state["history"] = [h for h in state["history"] if h.get("date", "") >= cutoff]
    save_state(state)
    return 0


if __name__ == "__main__":
    sys.exit(main())
