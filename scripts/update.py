#!/usr/bin/env python3
"""Daily digest of new arXiv papers in medical AI.

Fetches recent papers from the arXiv API, tags them by topic,
writes a daily digest, a weekly recap and refreshes README.md.
Standard library only (no pip install needed).
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import sys
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_FILE = ROOT / "data" / "papers.json"
DIGEST_DIR = ROOT / "digests"
README = ROOT / "README.md"
CONFIG_FILE = ROOT / "config.json"

ATOM = "{http://www.w3.org/2005/Atom}"
ARXIV = "{http://arxiv.org/schemas/atom}"
API_URL = "https://export.arxiv.org/api/query"


def load_config() -> dict:
    return json.loads(CONFIG_FILE.read_text(encoding="utf-8"))


def build_query(cfg: dict) -> str:
    cats = " OR ".join(f"cat:{c}" for c in cfg["categories"])
    terms = " OR ".join(
        f'abs:"{t}"' if " " in t else f"abs:{t}" for t in cfg["medical_terms"]
    )
    return f"({cats}) AND ({terms})"


def fetch(cfg: dict, xml_path: str | None = None) -> bytes:
    if xml_path:  # offline testing
        return Path(xml_path).read_bytes()
    params = {
        "search_query": build_query(cfg),
        "sortBy": "submittedDate",
        "sortOrder": "descending",
        "start": 0,
        "max_results": cfg.get("max_results", 200),
    }
    url = API_URL + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(
        url, headers={"User-Agent": "medai-arxiv-daily (GitHub Actions)"}
    )
    last_err = None
    for attempt in range(4):
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                return r.read()
        except Exception as e:  # network hiccup: retry politely
            last_err = e
            time.sleep(5 * (attempt + 1))
    raise RuntimeError(f"arXiv API unreachable: {last_err}")


def clean(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "")).strip()


def parse(xml_bytes: bytes) -> list[dict]:
    root = ET.fromstring(xml_bytes)
    papers = []
    for e in root.findall(f"{ATOM}entry"):
        raw_id = e.findtext(f"{ATOM}id", "")
        arxiv_id = re.sub(r"v\d+$", "", raw_id.rsplit("/abs/", 1)[-1])
        if not arxiv_id:
            continue
        primary = e.find(f"{ARXIV}primary_category")
        papers.append(
            {
                "id": arxiv_id,
                "title": clean(e.findtext(f"{ATOM}title")),
                "authors": [
                    clean(a.findtext(f"{ATOM}name"))
                    for a in e.findall(f"{ATOM}author")
                ],
                "summary": clean(e.findtext(f"{ATOM}summary")),
                "published": e.findtext(f"{ATOM}published", "")[:10],
                "category": primary.get("term") if primary is not None else "",
                "url": f"https://arxiv.org/abs/{arxiv_id}",
            }
        )
    return papers


def tag(paper: dict, topics: dict) -> list[str]:
    text = f" {paper['title']} {paper['summary']} ".lower()
    tags = [
        name
        for name, kws in topics.items()
        if any(re.search(r"\b" + re.escape(k.lower()) + r"\b", text) for k in kws)
    ]
    return tags or ["Other"]


def short(text: str, n: int = 280) -> str:
    return text if len(text) <= n else text[:n].rsplit(" ", 1)[0] + "…"


def authors_str(authors: list[str]) -> str:
    return ", ".join(authors[:3]) + (" et al." if len(authors) > 3 else "")


def md_escape(s: str) -> str:
    return s.replace("|", "\\|")


def write_digest(day: str, papers: list[dict], topic_order: list[str]) -> Path:
    by_topic = defaultdict(list)
    for p in papers:
        for t in p["tags"]:
            by_topic[t].append(p)
    lines = [
        f"# Medical AI on arXiv — {day}",
        "",
        f"**{len(papers)} new papers.** "
        + " · ".join(f"{t}: {len(by_topic[t])}" for t in topic_order if by_topic[t]),
        "",
    ]
    for t in topic_order:
        if not by_topic[t]:
            continue
        lines += [f"## {t} ({len(by_topic[t])})", ""]
        for p in by_topic[t]:
            lines += [
                f"### [{p['title']}]({p['url']})",
                f"*{authors_str(p['authors'])}* — `{p['category']}`",
                "",
                f"> {short(p['summary'])}",
                "",
            ]
    y, m, _ = day.split("-")
    path = DIGEST_DIR / y / m / f"{day}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def write_weekly(db: dict, today: dt.date, topic_order: list[str]) -> Path:
    year, week, _ = today.isocalendar()
    start = today - dt.timedelta(days=today.weekday())
    week_papers = [
        p for p in db.values()
        if start.isoformat() <= p["added"] <= today.isoformat()
    ]
    counts = Counter(t for p in week_papers for t in p["tags"])
    lines = [
        f"# Weekly recap — {year}-W{week:02d}",
        "",
        f"From {start.isoformat()} to {today.isoformat()}: "
        f"**{len(week_papers)} papers** tracked.",
        "",
        "| Topic | Papers |",
        "|---|---|",
    ]
    lines += [f"| {t} | {counts[t]} |" for t in topic_order if counts[t]]
    lines += ["", "## Highlights (one per topic)", ""]
    used = set()
    for t in topic_order:
        pick = next((p for p in week_papers if t in p["tags"] and p["id"] not in used), None)
        if pick:
            used.add(pick["id"])
            lines.append(f"- **{t}** — [{pick['title']}]({pick['url']})")
    path = DIGEST_DIR / "weekly" / f"{year}-W{week:02d}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def write_readme(db: dict, today: dt.date, topic_order: list[str], latest_day: str | None):
    total = len(db)
    last30 = (today - dt.timedelta(days=30)).isoformat()
    recent = [p for p in db.values() if p["added"] >= last30]
    counts = Counter(t for p in recent for t in p["tags"])
    latest = sorted(
        (p for p in db.values() if p["added"] == latest_day),
        key=lambda p: p["published"], reverse=True,
    )

    lines = [
        "# 🩺 Medical AI — arXiv Daily",
        "",
        "Automated daily digest of new arXiv papers on **AI for medicine**: "
        "medical image segmentation, radiology, digital pathology, clinical LLMs "
        "and fairness. Updated every day by GitHub Actions.",
        "",
        f"![papers](https://img.shields.io/badge/papers_tracked-{total}-blue) "
        f"![updated](https://img.shields.io/badge/updated-{today.isoformat().replace('-', '--')}-green)",
        "",
        "## Last 30 days by topic",
        "",
        "| Topic | Papers |",
        "|---|---|",
    ]
    lines += [f"| {t} | {counts[t]} |" for t in topic_order if counts[t]]
    if latest:
        lines += ["", f"## Latest papers ({latest_day})", "", "| Paper | Topics |", "|---|---|"]
        for p in latest[:25]:
            lines.append(
                f"| [{md_escape(p['title'])}]({p['url']})<br><sub>{md_escape(authors_str(p['authors']))}</sub> "
                f"| {', '.join(p['tags'])} |"
            )
        if len(latest) > 25:
            y, m, _ = latest_day.split("-")
            lines.append(f"\n➡️ [All {len(latest)} papers of the day](digests/{y}/{m}/{latest_day}.md)")
    lines += [
        "",
        "## Archive",
        "",
        "- Daily digests: [`digests/`](digests/)",
        "- Weekly recaps: [`digests/weekly/`](digests/weekly/)",
        "- Raw data (JSON): [`data/papers.json`](data/papers.json)",
        "",
        "## How it works",
        "",
        "`scripts/update.py` queries the [arXiv API](https://info.arxiv.org/help/api/), "
        "tags each paper with keyword rules from `config.json`, and writes the digests. "
        "A scheduled GitHub Actions workflow runs it daily. No dependencies beyond the "
        "Python standard library.",
        "",
        "<sub>Paper metadata from arXiv. Thank you to arXiv for use of its open access interoperability.</sub>",
        "",
    ]
    README.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--xml", help="read arXiv response from a local file (testing)")
    ap.add_argument("--date", help="override today's date (YYYY-MM-DD)")
    args = ap.parse_args()

    cfg = load_config()
    topics = cfg["topics"]
    topic_order = list(topics) + ["Other"]
    today = dt.date.fromisoformat(args.date) if args.date else dt.datetime.now(dt.timezone.utc).date()

    db = json.loads(DATA_FILE.read_text(encoding="utf-8")) if DATA_FILE.exists() else {}
    new = []
    for p in parse(fetch(cfg, args.xml)):
        if p["id"] in db:
            continue
        p["tags"] = tag(p, topics)
        p["added"] = today.isoformat()
        db[p["id"]] = p
        new.append(p)

    print(f"{len(new)} new papers (total {len(db)})")
    if new:
        print("digest:", write_digest(today.isoformat(), new, topic_order).relative_to(ROOT))
    if today.weekday() == 5 or (new and today.weekday() == 4):  # Fri (if new) & Sat
        print("weekly:", write_weekly(db, today, topic_order).relative_to(ROOT))

    added_days = sorted({p["added"] for p in db.values()})
    write_readme(db, today, topic_order, added_days[-1] if added_days else None)

    DATA_FILE.parent.mkdir(parents=True, exist_ok=True)
    DATA_FILE.write_text(
        json.dumps(dict(sorted(db.items())), ensure_ascii=False, indent=1), encoding="utf-8"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
