"""Build the real GitHub Issues benchmark set from the Go project (github.com/golang/go).

Why Go: its maintainers close duplicate issues with an exact "Duplicate of #N"
comment, which gives a real answer key for de-duplication, and its labels
(FeatureRequest, Documentation, NeedsFix, release-blocker) give one for triage.
Kaggle's GitHub Issues dumps carry titles and bodies but no duplicate links, so
they cannot score de-duplication; `evaluate_github_issues.py` also accepts a
Kaggle-style CSV for the triage and clustering parts.

Uses GitHub's public REST API without a login (60 requests/hour, 10 searches per
minute). Progress is saved after every pair, and the script waits for the rate
limit to reset, so it can run in the background or be stopped and resumed.

  python -m scripts.fetch_github_issues --pairs 60
"""
from __future__ import annotations

import argparse
import json
import os
import re
import time
import urllib.error
import urllib.request
from collections import Counter

REPO = "golang/go"
API = "https://api.github.com"
OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "github_issues_golang.json")
DUP_RE = re.compile(r"(?i)\bduplicate of (?:golang/go)?#(\d+)")
TRIAGE_QUERIES = {          # label -> what the PM agent's triage should say
    "FeatureRequest": "feature",
    "Documentation": "docs",
    "NeedsFix": "bug",
}


def _get(url: str) -> dict | list:
    """GET a GitHub API URL, waiting for the rate limit to reset when it runs out."""
    while True:
        req = urllib.request.Request(url, headers={"Accept": "application/vnd.github+json",
                                                   "User-Agent": "projecute-benchmark"})
        try:
            with urllib.request.urlopen(req, timeout=60) as res:
                return json.load(res)
        except urllib.error.HTTPError as err:
            if err.code in (403, 429):
                reset = int(err.headers.get("X-RateLimit-Reset") or time.time() + 60)
                wait = max(5, reset - int(time.time()) + 3)
                print(f"  rate limit reached; waiting {wait // 60} min {wait % 60} s", flush=True)
                time.sleep(wait)
                continue
            raise


def _issue(raw: dict) -> dict:
    """Keep only what the benchmark needs from a GitHub issue."""
    return {"number": raw["number"], "url": raw["html_url"], "title": raw["title"],
            "body": (raw.get("body") or "")[:2000], "labels": [lbl["name"] for lbl in raw.get("labels", [])],
            "created_at": raw.get("created_at")}


def _search(query: str, pages: int = 1) -> list[dict]:
    """Issues matching a search query, newest first (100 per page)."""
    out: list[dict] = []
    for page in range(1, pages + 1):
        q = urllib.request.quote(f"repo:{REPO} is:issue {query}")
        data = _get(f"{API}/search/issues?q={q}&sort=created&order=desc&per_page=100&page={page}")
        out += [_issue(i) for i in data.get("items", []) if "pull_request" not in i]
        time.sleep(7)                     # stay under 10 searches per minute
    return out


def _load() -> dict:
    """The data saved so far, or an empty set."""
    if os.path.exists(OUT):
        with open(OUT, encoding="utf-8") as fh:
            return json.load(fh)
    return {"source": f"https://github.com/{REPO}/issues", "pairs": [], "triage": [], "checked": []}


def _save(data: dict) -> None:
    """Write the benchmark file."""
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=1, ensure_ascii=False)


def _collect_triage(data: dict) -> None:
    """Add triage examples for any category still missing (search API).

    GitHub search can return an empty page under load, so an empty result is
    retried. Issues carrying labels for two categories are skipped so the
    answer key is unambiguous.
    """
    have = Counter(t["expected_category"] for t in data["triage"])
    numbers = {t["number"] for t in data["triage"]}
    for label, category in TRIAGE_QUERIES.items():
        if have[category]:
            continue
        print(f"Collecting '{label}' examples (search API)…", flush=True)
        for _attempt in range(3):
            found = _search(f'label:"{label}"')
            if found:
                break
            time.sleep(20)
        for issue in found:
            categories = {c for lbl, c in TRIAGE_QUERIES.items() if lbl in issue["labels"]}
            if len(categories) == 1 and issue["number"] not in numbers:
                numbers.add(issue["number"])
                data["triage"].append({**issue, "expected_category": category})
    # Drop earlier examples whose labels point at two categories.
    data["triage"] = [t for t in data["triage"]
                      if len({c for lbl, c in TRIAGE_QUERIES.items() if lbl in t["labels"]}) == 1]
    if not data.get("blockers_checked"):
        blockers = {i["number"] for i in _search('label:"release-blocker"')}
        data["blockers_checked"] = True
    else:
        blockers = set()
    for item in data["triage"]:
        item["expected_priority_high"] = (item.get("expected_priority_high") or item["number"] in blockers
                                          or "release-blocker" in item["labels"])
    _save(data)
    print(f"  triage examples: {dict(Counter(t['expected_category'] for t in data['triage']))}", flush=True)


def main() -> None:
    """Collect triage examples, then duplicate pairs until `--pairs` is reached."""
    ap = argparse.ArgumentParser()
    ap.add_argument("--pairs", type=int, default=60, help="duplicate pairs to collect")
    args = ap.parse_args()
    data = _load()

    _collect_triage(data)

    candidates = _search('is:closed "Duplicate of" in:comments', pages=3)
    print(f"{len(candidates)} closed issues mention a duplicate; collecting pairs…", flush=True)
    done = {p["duplicate"]["number"] for p in data["pairs"]} | set(data["checked"])
    for dup in candidates:
        if len(data["pairs"]) >= args.pairs:
            break
        if dup["number"] in done:
            continue
        comments = _get(f"{API}/repos/{REPO}/issues/{dup['number']}/comments?per_page=50")
        target = next((int(m.group(1)) for c in comments for m in [DUP_RE.search(c.get("body") or "")] if m), None)
        data["checked"].append(dup["number"])
        if not target or target == dup["number"]:
            _save(data)
            continue
        try:
            original = _issue(_get(f"{API}/repos/{REPO}/issues/{target}"))
        except urllib.error.HTTPError:
            _save(data)
            continue
        data["pairs"].append({"duplicate": dup, "original": original})
        _save(data)
        print(f"  {len(data['pairs'])}/{args.pairs}: #{dup['number']} duplicates #{target}", flush=True)
    print(f"Done: {len(data['pairs'])} duplicate pairs, {len(data['triage'])} triage examples -> {OUT}")


if __name__ == "__main__":
    main()
