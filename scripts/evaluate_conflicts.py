"""Planted-conflict evaluation.

    python -m scripts.evaluate_conflicts [--verbose]

Each scenario plants one claim that relates to an earlier claim, surrounded by
unrelated distractor claims. The same retrieval + Architect pipeline the app
uses is run over it, and two things are measured:

  detection  — did the pipeline return the expected kind
               (contradiction / duplicate / assumption / none)?
  evidence   — did it point at the planted source claim rather than a distractor?

Every number printed is measured on these scenarios. Nothing is estimated, and
the set is small and hand-written: it is a regression check, not a benchmark.
"""
from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import agents, retrieval  # noqa: E402
from app.llm import llm  # noqa: E402

# Unrelated statements placed around every planted claim, so the search has to pick
# the right one.
DISTRACTORS = [
    "The marketing site needs new screenshots before launch.",
    "We should translate the help centre into Spanish next quarter.",
    "The nightly backup job finished late again yesterday.",
    "Let's move the weekly sync to Thursday mornings.",
    "The logo on the invoice PDF is the old one.",
]

# id, planted earlier claim, new claim, expected kind
SCENARIOS: list[tuple[str, str, str, str]] = [
    ("login-vs-guest",
     "Agreed, no login for checkout. We just collect an email address so we can send the receipt.",
     "Update from the client: every customer must log in before they can pay, so checkout requires an account.",
     "contradiction"),
    ("payment-optional-vs-required",
     "Saving a payment card is optional for shoppers.",
     "Shoppers must save a payment card before the order is placed.",
     "contradiction"),
    ("anonymous-reviews",
     "Reviews can be posted anonymously, we do not need the reviewer's name.",
     "Every review must show the reviewer's verified name.",
     "contradiction"),
    ("email-verification",
     "We will not verify the email address at sign-up, it slows people down.",
     "Email addresses must be verified before the account is created.",
     "contradiction"),
    ("offline-mode",
     "The app does not need to work offline for this release.",
     "The app must keep working offline when the connection drops.",
     "contradiction"),
    ("admin-delete",
     "Admins should never delete customer records, only hide them.",
     "Admins must be able to delete customer records permanently.",
     "contradiction"),
    ("guest-cart",
     "A guest cart does not need to survive a browser restart.",
     "The guest cart must survive a browser restart.",
     "contradiction"),

    ("retention-days",
     "We keep order history for 30 days.",
     "Order history is kept for 90 days before it is archived.",
     "assumption"),
    ("session-timeout",
     "The session times out after 15 minutes of inactivity.",
     "Sessions time out after 60 minutes of inactivity.",
     "assumption"),
    ("password-length",
     "Passwords need at least 8 characters.",
     "Passwords need at least 12 characters.",
     "assumption"),
    ("upload-limit",
     "Uploads are capped at 5 MB per file.",
     "Uploads are capped at 25 MB per file.",
     "assumption"),

    ("dup-checkout-page",
     "Build the checkout page with an address form and a payment step.",
     "Build the checkout page with a payment step and an address form.",
     "duplicate"),
    ("dup-order-storage",
     "Store each checkout order so support can look it up later.",
     "Store each checkout order so support can look it up later on.",
     "duplicate"),
    ("dup-receipt-email",
     "Send a receipt email after a successful payment.",
     "Send a receipt email once the payment succeeds.",
     "duplicate"),
    ("dup-dark-theme",
     "Add a dark theme to the settings screen.",
     "Add a dark theme option to the settings screen.",
     "duplicate"),

    ("clean-unrelated-a",
     "The checkout page needs an address form and a payment step.",
     "Rotate the API signing keys every quarter.",
     "none"),
    ("clean-unrelated-b",
     "Store each checkout order so support can look it up later.",
     "Add a keyboard shortcut that focuses the search box.",
     "none"),
    ("related-no-conflict",
     "The checkout page needs an address form.",
     "The checkout page should also show the delivery date.",
     "unclear"),
]


def run(verbose: bool) -> int:
    """Run every planted scenario through retrieval + Architect and score detection and evidence."""
    detected = 0
    evidence_ok = 0
    evidence_applicable = 0
    rows: list[tuple[str, str, str, bool, str]] = []

    for sid, planted, new_claim, expected in SCENARIOS:
        # Run the same review pipeline the app uses, then score kind and evidence.
        corpus = [("planted", planted)] + [(f"d{i}", d) for i, d in enumerate(DISTRACTORS)]
        state = agents.run_review_pipeline(new_claim, corpus)
        verdict = state.get("verdict") or {}
        got = verdict.get("kind", "none") or "none"
        hit = got == expected
        detected += hit

        ev_note = "—"
        if expected != "none":
            evidence_applicable += 1
            pointed = verdict.get("match_id")
            if pointed == "planted":
                evidence_ok += 1
                ev_note = "planted claim"
            else:
                ev_note = f"pointed at {pointed or 'nothing'}"
        rows.append((sid, expected, got, hit, ev_note))

    total = len(SCENARIOS)
    # ---------------------------------------------------------------- report
    print("Planted conflict scenarios")
    print(f"  Scenarios:      {total}  (each with {len(DISTRACTORS)} distractor claims)")
    print(f"  Judged by:      {'Groq (' + llm.model + ')' if llm.mode == 'live' else 'built-in rules (no AI provider key)'}")
    print(f"  Claim search:   {retrieval.backend_label()}")
    print()
    print(f"  Detection       {detected}/{total}  ({detected / total:.3f})")
    if evidence_applicable:
        print(f"  Evidence        {evidence_ok}/{evidence_applicable}  ({evidence_ok / evidence_applicable:.3f}) "
              "— flagged the planted claim, not a distractor")
    print()

    by_kind: dict[str, list[bool]] = {}
    for _sid, expected, _got, hit, _ev in rows:
        by_kind.setdefault(expected, []).append(hit)
    for kind, hits in by_kind.items():
        print(f"  {kind:<14} {sum(hits)}/{len(hits)}")

    misses = [r for r in rows if not r[3]]
    if misses:
        print()
        print("  Misses:")
        for sid, expected, got, _hit, _ev in misses:
            print(f"    {sid:<26} expected {expected}, got {got}")
    if verbose:
        print()
        print("  All scenarios:")
        for sid, expected, got, hit, ev in rows:
            print(f"    {'ok ' if hit else 'miss'} {sid:<26} expected {expected:<14} got {got:<14} evidence: {ev}")
    return 0


def main() -> int:
    """Print the conflict evaluation report."""
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--verbose", action="store_true", help="print every scenario")
    args = ap.parse_args()
    return run(args.verbose)


if __name__ == "__main__":
    raise SystemExit(main())
