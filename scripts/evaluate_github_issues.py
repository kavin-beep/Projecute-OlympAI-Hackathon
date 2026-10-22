"""Benchmark the agents on real GitHub issues: de-duplicate, cluster and triage.

Data: `data/github_issues_golang.json`, built by `fetch_github_issues.py` from
github.com/golang/go. The answer key is the Go maintainers' own work:
"Duplicate of #N" comments for duplicates, and issue labels for triage.

  python -m scripts.evaluate_github_issues                 # rules + retrieval (no key needed)
  python -m scripts.evaluate_github_issues --live 40       # also the live LLM agents on 40 pairs/issues

What is measured
  De-duplication  each real duplicate pair vs a hard negative: the same duplicate
                  paired with the original of another issue from the same Go
                  component (e.g. two "cmd/compile:" issues). Scored for the
                  retrieval search alone and for the Architect agent.
  Search          recall@1 / recall@5: is the true original among the closest
                  issues when a duplicate is compared with every original?
  Clustering      issues grouped by similarity vs the maintainers' duplicate
                  groups, as pairwise precision / recall.
  Triage          the PM agent's category (bug / feature / docs) vs the labels
                  FeatureRequest, Documentation and NeedsFix, and whether it
                  marks release-blockers High.
"""
from __future__ import annotations

import argparse
import json
import os
import random
import sys
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import agents, retrieval  # noqa: E402
from app.llm import llm  # noqa: E402

DATA = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "github_issues_golang.json")
RESULTS = DATA.replace(".json", "_results.json")


def text_of(issue: dict) -> str:
    """What the agents see for an issue: its title and the start of its body."""
    return f"{issue['title']}. {issue['body'][:600]}".strip()


def component(issue: dict) -> str:
    """The Go component prefix of a title, e.g. 'cmd/compile' from 'cmd/compile: crash on …'."""
    return issue["title"].split(":", 1)[0].strip() if ":" in issue["title"] else ""


def prf(tp: int, fp: int, fn: int) -> dict:
    """Precision, recall and F1 from counts."""
    p = tp / (tp + fp) if tp + fp else 0.0
    r = tp / (tp + fn) if tp + fn else 0.0
    return {"precision": round(p, 3), "recall": round(r, 3), "f1": round(2 * p * r / (p + r), 3) if p + r else 0.0,
            "tp": tp, "fp": fp, "fn": fn}


def labelled_pairs(pairs: list[dict], seed: int = 7) -> list[tuple[dict, dict, int]]:
    """Every real duplicate pair (label 1) plus one hard negative per pair (label 0)."""
    rng = random.Random(seed)
    originals = [p["original"] for p in pairs]
    out: list[tuple[dict, dict, int]] = []
    for p in pairs:
        dup, orig = p["duplicate"], p["original"]
        out.append((dup, orig, 1))
        others = [o for o in originals if o["number"] != orig["number"]]
        same = [o for o in others if component(o) and component(o) == component(dup)]
        out.append((dup, rng.choice(same or others), 0))
    return out


def eval_dedup(pairs: list[tuple[dict, dict, int]], live_limit: int) -> dict:
    """De-duplication by the retrieval search alone and by the Architect agent."""
    sims = [(retrieval.similarity(text_of(a), text_of(b)), y) for a, b, y in pairs]
    sweep = {}
    for t in [x / 100 for x in range(20, 91, 5)]:
        tp = sum(1 for s, y in sims if s >= t and y)
        fp = sum(1 for s, y in sims if s >= t and not y)
        fn = sum(1 for s, y in sims if s < t and y)
        sweep[t] = prf(tp, fp, fn)
    best_t = max(sweep, key=lambda t: sweep[t]["f1"])
    fixed_t = 0.5 if retrieval.backend() == "embeddings" else 0.3

    def architect(subset):
        tp = fp = fn = 0
        for a, b, y in subset:
            verdict, _ = agents.architect_check(text_of(a), text_of(b))
            pred = verdict.kind == "duplicate"
            tp += pred and y
            fp += pred and not y
            fn += (not pred) and y
        return prf(tp, fp, fn)

    out = {"pairs": len(pairs), "positives": sum(y for *_, y in pairs),
           "search_fixed_threshold": {"threshold": fixed_t, **sweep[min(sweep, key=lambda t: abs(t - fixed_t))]},
           "search_best_threshold": {"threshold": best_t, **sweep[best_t]},
           "architect_rules": None, "architect_live": None}
    mode = llm.mode
    if mode == "live":
        llm._client, saved = None, llm._client            # rules first, without the model
        out["architect_rules"] = architect(pairs)
        llm._client = saved
        if live_limit:
            subset = pairs[: live_limit * 2]
            out["architect_live"] = {"pairs": len(subset), "model": llm.model, **architect(subset)}
    else:
        out["architect_rules"] = architect(pairs)
    return out


def eval_search(pair_list: list[dict]) -> dict:
    """recall@1 and recall@5 when each duplicate is matched against every original."""
    originals = {p["original"]["number"]: p["original"] for p in pair_list}
    corpus = [(str(n), text_of(o)) for n, o in originals.items()]
    at1 = at5 = 0
    for p in pair_list:
        ranked = [cid for cid, _ in retrieval.related(text_of(p["duplicate"]), corpus, k=5, min_score=-1)]
        at1 += ranked[:1] == [str(p["original"]["number"])]
        at5 += str(p["original"]["number"]) in ranked
    n = len(pair_list)
    return {"queries": n, "candidates": len(corpus), "recall_at_1": round(at1 / n, 3), "recall_at_5": round(at5 / n, 3)}


def _root(parent: dict[int, int], x: int) -> int:
    """Union-find root of x."""
    while parent.get(x, x) != x:
        x = parent[x]
    return x


def eval_clusters(pair_list: list[dict], fixed: float) -> dict:
    """Group issues by similarity and compare with the maintainers' duplicate groups.

    Each issue joins its single most similar issue when that similarity reaches
    the threshold (nearest-neighbour linking), which avoids long chains of
    loosely related issues collapsing into one group.
    """
    issues: dict[int, dict] = {}
    truth_parent: dict[int, int] = {}
    for p in pair_list:
        d, o = p["duplicate"], p["original"]
        issues[d["number"]], issues[o["number"]] = d, o
        truth_parent[d["number"]] = o["number"]
    truth = {n: _root(truth_parent, n) for n in issues}
    nums = list(issues)
    corpus = [(str(n), text_of(issues[n])) for n in nums]
    nearest: dict[int, tuple[int, float]] = {}
    for n in nums:
        others = [(cid, t) for cid, t in corpus if cid != str(n)]
        best = retrieval.related(text_of(issues[n]), others, k=1, min_score=-1)
        if best:
            nearest[n] = (int(best[0][0]), best[0][1])

    def score_at(t: float) -> dict:
        parent: dict[int, int] = {}
        for n, (m, s) in nearest.items():
            if s >= t:
                ra, rb = _root(parent, n), _root(parent, m)
                if ra != rb:
                    parent[ra] = rb
        pred = {n: _root(parent, n) for n in nums}
        tp = fp = fn = 0
        for i in range(len(nums)):
            for j in range(i + 1, len(nums)):
                same_t = truth[nums[i]] == truth[nums[j]]
                same_p = pred[nums[i]] == pred[nums[j]]
                tp += same_t and same_p
                fp += same_p and not same_t
                fn += same_t and not same_p
        return {"threshold": t, "found_groups": len(set(pred.values())), **prf(tp, fp, fn)}

    sweep = [score_at(x / 100) for x in range(30, 96, 5)]
    best = max(sweep, key=lambda r: r["f1"])
    return {"issues": len(nums), "true_groups": len(set(truth.values())),
            "fixed": score_at(fixed), "best": best}


def eval_triage(items: list[dict], limit: int) -> dict:
    """PM agent triage vs the Go labels: category accuracy and release-blocker priority."""
    items = items[:limit] if limit else items
    correct, confusion = 0, Counter()
    blockers = blockers_high = others_high = others = 0
    for it in items:
        result, _ = agents.triage_issue(it["title"], it["body"])
        confusion[(it["expected_category"], result.category)] += 1
        correct += result.category == it["expected_category"]
        if it.get("expected_priority_high"):
            blockers += 1
            blockers_high += result.priority == "High"
        else:
            others += 1
            others_high += result.priority == "High"
    by_label = {}
    for expected in sorted({e for e, _ in confusion}):
        total = sum(n for (e, _), n in confusion.items() if e == expected)
        by_label[expected] = {"n": total, "correct": confusion[(expected, expected)]}
    return {"issues": len(items), "category_accuracy": round(correct / len(items), 3) if items else 0.0,
            "by_label": by_label,
            "release_blockers": blockers, "release_blockers_marked_high": blockers_high,
            "non_blockers_marked_high": others_high, "non_blockers": others}


def main() -> None:
    """Run the benchmark and print a report."""
    ap = argparse.ArgumentParser()
    ap.add_argument("--live", type=int, default=0, help="also run the live LLM on this many pairs / issues")
    ap.add_argument("--triage-limit", type=int, default=0, help="rules triage on at most this many issues")
    args = ap.parse_args()
    if not os.path.exists(DATA):
        sys.exit("No data yet. Run: python -m scripts.fetch_github_issues")
    with open(DATA, encoding="utf-8") as fh:
        data = json.load(fh)
    pair_list = data["pairs"]
    labelled = labelled_pairs(pair_list)

    print("Real GitHub issues benchmark (github.com/golang/go)")
    print(f"  Duplicate pairs:  {len(pair_list)} (answer key: maintainers' 'Duplicate of #N' comments)")
    print(f"  Triage issues:    {len(data['triage'])} (answer key: FeatureRequest / Documentation / NeedsFix labels)")
    print(f"  Search backend:   {retrieval.backend_label()}")
    print(f"  AI mode:          {llm.status()['label']}\n")

    report = {"source": data["source"], "backend": retrieval.backend_label(),
              "dedup": eval_dedup(labelled, args.live), "search": eval_search(pair_list)}
    report["clusters"] = eval_clusters(pair_list, report["dedup"]["search_fixed_threshold"]["threshold"])

    saved = llm._client
    llm._client = None                       # rules triage over the full set
    report["triage_rules"] = eval_triage(data["triage"], args.triage_limit)
    llm._client = saved
    if args.live and llm.mode == "live":
        random.Random(3).shuffle(data["triage"])
        report["triage_live"] = {"model": llm.model, **eval_triage(data["triage"], args.live)}

    d = report["dedup"]
    print("De-duplication (real duplicates vs same-component hard negatives)")
    print(f"  {d['pairs']} pairs, {d['positives']} real duplicates")
    for name, key in [("Search, fixed threshold", "search_fixed_threshold"),
                      ("Search, best (tuned here)", "search_best_threshold")]:
        r = d[key]
        print(f"  {name:<26} t={r['threshold']:.2f}  P {r['precision']:.3f}  R {r['recall']:.3f}  F1 {r['f1']:.3f}")
    for name, key in [("Architect agent, rules", "architect_rules"), ("Architect agent, live LLM", "architect_live")]:
        r = d[key]
        if r:
            print(f"  {name:<26} {r.get('pairs', d['pairs'])} pairs  P {r['precision']:.3f}  R {r['recall']:.3f}  F1 {r['f1']:.3f}")
    s = report["search"]
    print(f"\nSearch: each duplicate vs all {s['candidates']} originals")
    print(f"  recall@1 {s['recall_at_1']:.3f}   recall@5 {s['recall_at_5']:.3f}")
    c = report["clusters"]
    print(f"\nClustering ({c['issues']} issues into {c['true_groups']} true duplicate groups; nearest-neighbour linking)")
    for name, key in [("fixed threshold", "fixed"), ("best threshold (tuned here)", "best")]:
        r = c[key]
        print(f"  {name:<28} t={r['threshold']:.2f}  {r['found_groups']} groups  "
              f"pairwise P {r['precision']:.3f}  R {r['recall']:.3f}  F1 {r['f1']:.3f}")
    for name, key in [("rules", "triage_rules"), ("live LLM", "triage_live")]:
        t = report.get(key)
        if not t:
            continue
        print(f"\nTriage, PM agent ({name}, {t['issues']} issues)")
        print(f"  category accuracy {t['category_accuracy']:.3f}  "
              + "  ".join(f"{k}: {v['correct']}/{v['n']}" for k, v in t["by_label"].items()))
        print(f"  release-blockers marked High: {t['release_blockers_marked_high']}/{t['release_blockers']}   "
              f"other issues marked High: {t['non_blockers_marked_high']}/{t['non_blockers']}")
    with open(RESULTS, "w", encoding="utf-8") as fh:
        json.dump(report, fh, indent=1)
    print(f"\nSaved: {RESULTS}")
    print("NOTE: a small real sample; treat these as prototype measurements, not a general accuracy claim.")


if __name__ == "__main__":
    main()
