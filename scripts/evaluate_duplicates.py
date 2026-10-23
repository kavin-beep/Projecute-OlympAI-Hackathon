"""Duplicate-detection precision and recall on a labelled pair set.

    python -m scripts.evaluate_duplicates <csv_path> [--limit N]

The CSV must contain a labelled pair per row. Two shapes are accepted:
  text_a, text_b, is_duplicate            (1/0, true/false, yes/no)
  title_a, title_b, label                 (same meaning)
A labelled subset of the Kaggle GitHub Issues data in either shape works.

A tiny sample is included at data/sample_duplicates_SYNTHETIC.csv. It is
synthetic, written for smoke tests, and is NOT a benchmark — numbers from it
say nothing about real-world accuracy.

Every number printed is measured on the rows given. Nothing is estimated.
"""
from __future__ import annotations

import argparse
import csv
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import agents, retrieval  # noqa: E402
from app.llm import llm  # noqa: E402

# Accepted spellings of the label, and accepted column names for each side of a pair.
TRUE = {"1", "true", "yes", "y", "duplicate", "dup"}
FALSE = {"0", "false", "no", "n", "not_duplicate", "unique"}

A_KEYS = ("text_a", "title_a", "question1", "a", "issue_a", "text1", "title1")
B_KEYS = ("text_b", "title_b", "question2", "b", "issue_b", "text2", "title2")
L_KEYS = ("is_duplicate", "label", "duplicate", "is_dup", "target")


def _pick(row: dict, keys: tuple[str, ...]) -> str | None:
    """First column name from `names` that exists in the CSV header."""
    lowered = {k.strip().lower(): v for k, v in row.items() if k}
    for k in keys:
        if k in lowered and lowered[k] not in (None, ""):
            return lowered[k]
    return None


def load_pairs(path: str, limit: int | None = None) -> list[tuple[str, str, bool]]:
    """Read labelled (text_a, text_b, is_duplicate) pairs from a CSV."""
    pairs: list[tuple[str, str, bool]] = []
    with open(path, newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            a, b, label = _pick(row, A_KEYS), _pick(row, B_KEYS), _pick(row, L_KEYS)
            if a is None or b is None or label is None:
                continue
            norm = str(label).strip().lower()
            if norm in TRUE:
                is_dup = True
            elif norm in FALSE:
                is_dup = False
            else:
                continue
            pairs.append((a, b, is_dup))
            if limit and len(pairs) >= limit:
                break
    return pairs


def main() -> int:
    """Score duplicate detection (precision, recall, F1) on a labelled CSV."""
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("csv_path", help="labelled pair CSV")
    ap.add_argument("--limit", type=int, default=None, help="only evaluate the first N usable rows")
    args = ap.parse_args()

    if not os.path.exists(args.csv_path):
        print(f"No such file: {args.csv_path}")
        return 2

    pairs = load_pairs(args.csv_path)
    if not pairs:
        print("No usable rows. Expected columns like text_a,text_b,is_duplicate.")
        return 2
    evaluated = pairs[: args.limit] if args.limit else pairs

    # Ask the Architect about every pair and count right and wrong answers.
    tp = fp = fn = tn = 0
    mistakes: list[tuple[str, str, bool]] = []
    for a, b, truth in evaluated:
        verdict, _source = agents.architect_check(a, b)
        predicted = verdict.kind == "duplicate"
        if predicted and truth:
            tp += 1
        elif predicted and not truth:
            fp += 1
            mistakes.append((a, b, truth))
        elif not predicted and truth:
            fn += 1
            mistakes.append((a, b, truth))
        else:
            tn += 1

    # Precision: flagged pairs that really are duplicates. Recall: real duplicates found.
    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall = tp / (tp + fn) if (tp + fn) else 0.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0
    accuracy = (tp + tn) / len(evaluated)

    print("Duplicate detection")
    print(f"  Source file:    {args.csv_path}")
    print(f"  Rows usable:    {len(pairs)}   evaluated: {len(evaluated)}")
    print(f"  Judged by:      {'Groq (' + llm.model + ')' if llm.mode == 'live' else 'built-in rules (no AI provider key)'}")
    print(f"  Claim search:   {retrieval.backend_label()}")
    print()
    print(f"  True positives  {tp}")
    print(f"  False positives {fp}")
    print(f"  False negatives {fn}")
    print(f"  True negatives  {tn}")
    print()
    print(f"  Precision       {precision:.3f}")
    print(f"  Recall          {recall:.3f}")
    print(f"  F1              {f1:.3f}")
    print(f"  Accuracy        {accuracy:.3f}")
    if "SYNTHETIC" in os.path.basename(args.csv_path).upper():
        print()
        print("  NOTE: this is the synthetic smoke-test sample, not a benchmark.")
    if mistakes:
        print()
        print("  First few misses:")
        for a, b, truth in mistakes[:5]:
            print(f"    [{'should be duplicate' if truth else 'should not be duplicate'}]")
            print(f"      A: {a[:84]}")
            print(f"      B: {b[:84]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
