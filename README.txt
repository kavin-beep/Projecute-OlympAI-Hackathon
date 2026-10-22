PROJECUTE
From team discussion to approved project work

OlympAI Hackathon - Stage 1 prototype - Category 9-12 Advanced Coders
Team Monarch Core: Kavin K (team leader), Adrian Rohith, Sritharan N S

GitHub repository: https://github.com/kavin-beep/Projecute-OlympAI-Hackathon
Live demo (live AI): https://projecute.onrender.com

This is a plain-text copy of README.md. The formatted version, with the
animated images and diagrams, is on the GitHub page above.

==============================================================================
QUICK START FOR JUDGES
==============================================================================

Try it live, with live AI: https://projecute.onrender.com
---------------------------------------------------------

Nothing to install and no key needed: the hosted prototype runs the PM,
Architect and QA agents on a live language model for every visitor. Open the
link in two browser tabs, sign in as Kavin K (the host) in one and Sritharan N
S in the other, and follow the two-minute demo.

About the hosted version:

- It runs on Render's free plan with the team's Groq key stored as a server
  secret. Visitors use the AI through the server and never see the key.
- A GitHub Action (.github/workflows/keep-alive.yml) pings it every 10
  minutes, so it is awake when you click.
- To fit the free plan's memory, related-claim search uses the TF-IDF
  fallback. The live Architect agent still makes every conflict decision. The
  local versions below use the full Sentence Transformers + FAISS search.
- The data resets to the staged demo when the server restarts.

Or run it yourself
------------------

Without a key these run in labelled demo mode; with a free Groq key they use
live AI too. Pick whichever is easiest:

  * A. Windows
      Steps: Install Python 3.11+ (https://www.python.org/downloads/) (tick
        Add python.exe to PATH), unzip, double-click run.bat
      Time: ~5 min the first time
  * B. macOS / Linux
      Steps: Unzip, then run bash run.sh in a terminal
      Time: ~5 min the first time

Then open the app in two browser tabs. Sign in as Kavin K (the host) in one
and Sritharan N S in the other, and follow the two-minute demo.

  | Want the live AI agents? Get a free key at console.groq.com/keys
  | (https://console.groq.com/keys) (about a minute, no payment) and put
  | it in the .env file the run script creates. The header shows Live AI
  | or Demo mode, so you always know which you're seeing.

==============================================================================
REQUIREMENTS CHECKLIST
==============================================================================

Every requirement from the challenge brief, the submission rules and our Stage
1 deck, with where to see it.

Challenge brief: Multiplayer AI Sprint & Architecture Manager

  * Collaborative multi-agent sprint dashboard
      Where it is met: Group workspace with live WebSocket updates in every
        member's window
  * Multiple team members assign tasks
      Where it is met: PM agent proposes owners; any member submits tasks
        with a suggested owner (Tasks → New task); the host approves and
        reassigns
  * Agents cross-check PRDs, bug tickets and meeting summaries
      Where it is met: Sources: each statement is checked against the chat,
        other sources and tasks (pipeline.add_document, source-review graph)
  * Detect blockers
      Where it is met: PM agent flags blockers in sources as high-severity
        alerts with the affected tasks
  * Resolve architectural conflicts
      Where it is met: Contradiction / assumption alerts with exact
        evidence; host resolves, decision recorded, QA writes criteria
  * 1. Simultaneous multi-user sessions with role-based agents (PM, QA,
    Architect)
      Where it is met: Separate sessions per window; PM, Architect and QA
        agents in LangGraph; tests: test_live_updates.py, test_privacy.py
  * 2. Parse unstructured chat logs into structured tickets (Task, Priority,
    Estimated Hours)
      Where it is met: PM agent → Pydantic TicketProposal (title, detail,
        priority, estimated_hours, owner)
  * 3. Conflict-detection agent flags duplicate issues or contradicting
    requirements across team submissions
      Where it is met: Architect agent on chat messages, source documents
        and submitted tasks: duplicate / contradiction / assumption /
        unclear
  * Dataset: GitHub Issues, used to benchmark clustering, de-duplication and
    triage
      Where it is met: 45 real duplicate pairs and 260 labelled issues from
        github.com/golang/go, scored for de-duplication, search, clustering
        and triage: results (Kaggle's copy has no duplicate labels; see why
        there)
  * Target stack
      Where it is met: Python, FastAPI + WebSockets, LangGraph, FAISS; the
        web UI is HTML/CSS/JS as our deck specifies
  * Deliverable: live collaborative web dashboard
      Where it is met: https://projecute.onrender.com, plus local run
        scripts
  * Deliverable: multi-agent event stream logs
      Where it is met: Activity (live, timestamped) and Download event log
        (JSON)
  * Deliverable: automated ticket generator
      Where it is met: PM agent tickets from chat; fix tasks from bug
        tickets
  * Deliverable: simulated conflict-resolution tests
      Where it is met: scripts/simulate_conflict_resolution.py (18
        scenarios, end to end) and tests/

Submission rules

  * ZIP with all code files and assets
      Where it is met: projecute-submission.zip (no secrets, no local
        database)
  * Main file named main.py
      Where it is met: main.py in the root starts the app
  * README: setup and installation
      Where it is met: Setup and installation, Quick start
  * README: description of each file
      Where it is met: Every file and its purpose
  * README: how to run the main code
      Where it is met: Running the main code
  * README: dependencies
      Where it is met: Dependencies, requirements.txt
  * README: AI tools used
      Where it is met: AI tools used
  * Well-commented code
      Where it is met: Every module, class and function has a docstring or
        comment
  * Code standards
      Where it is met: ruff (pycodestyle, pyflakes, bugbear, pyupgrade,
        simplify, isort rules) passes with no findings
  * Original work, credited
      Where it is met: No code copied from other projects; AI tools,
        libraries, models, fonts, services and the GitHub data are all
        credited with their licences in Credits and licences

Our Stage 1 deck

  * 4
      Promise: Individual AI chat; reusable outputs; one shared brief and
        assigned tasks; expose conflicts before implementation
      Where it is met: Individual chat, individual workspace, Brief + Tasks,
        Alerts
  * 5
      Promise: Individual chat, group chat (public AI or private help with
        usage-only notices), individual workspace (content, emails, code as
        named items), group workspace; host approves assignments and group
        changes, including AI access
      Where it is met: All four areas; host-only approvals and AI switches,
        enforced server-side
  * 6
      Promise: HTML/CSS/JS; FastAPI + WebSockets; SQLite; Sentence
        Transformers + FAISS; LangGraph; free-tier LLM adapter + labelled
        mock mode; Pydantic, retries, cache, backoff; GitHub Issues subset +
        planted conflicts
      Where it is met: All used; see How it works and Data and evaluation
  * 7
      Promise: PM brief edited by team, approved by host; tickets with
        owner; embeddings + FAISS + Architect; flags with sources, dependent
        tickets, hours; host resolves; QA criteria; live dashboard
      Where it is met: The pipeline, step by step
  * 8
      Promise: Two-user dashboard, ticket generator, event stream; duplicate
        precision/recall on real issues; 15+ planted conflicts with
        detection and evidence; private/public access, host approvals, live
        updates verified
      Where it is met: Duplicate precision/recall on 45 real GitHub pairs;
        18 planted conflicts (rules and live AI); 32 tests
  * 10
      Promise: Decision impact; each affected ticket once with team-
        confirmed hours; Parallel Futures; Human Unit Test; exact messages
        on every flag; host approves
      Where it is met: Decisions list their tasks; impact line; Brief →
        Parallel Futures; task panel → Human Unit Test
  * 11
      Promise: Cache, batch, backoff, mock mode; evidence, "unclear", human
        review; separate storage and permission checks; one complete two-
        user workflow
      Where it is met: Answer cache, batched Architect calls, retry with
        backoff, labelled demo mode; "unclear" alerts and Dismiss;
        permission tests
  * 14
      Promise: Explicit sharing only; group AI reads only group messages;
        private AI use announced with no content; host approves settings;
        public or synthetic demo text; keys in environment files
      Where it is met: Privacy tests; .env and Render secrets
  * 17
      Promise: Find items by name in projects; items link to source chat;
        private until shared; team outputs beside decisions; editable text
        and code, never executed
      Where it is met: Individual workspace and Team outputs

==============================================================================
CONTENTS
==============================================================================

0. Requirements checklist
1. The problem
2. What Projecute does
3. Features
4. How it works
5. Data and evaluation
6. Setup and installation
7. Running the main code and troubleshooting
8. Two-minute demo script
9. Every file and its purpose
10. Dependencies
11. Privacy, ethics and security
12. AI tools used
13. What was verified, and what was not
14. Known limitations
15. Future scope: what Projecute doesn't do yet
16. Credits and licences
17. Team and acknowledgements

==============================================================================
THE PROBLEM
==============================================================================

- Separate AI chats leave teammates with different project assumptions.
- Long chat threads bury useful outputs and agreed decisions.
- Unclear goals cause duplicate tasks and conflicting technical plans.
- Teams need organised work, shared decisions and source evidence.

==============================================================================
WHAT PROJECUTE DOES
==============================================================================

Projecute is a multiplayer AI sprint and architecture manager. Each person can
use AI privately to explore and learn. The team works in a shared space where
AI agents turn the discussion into a brief and tasks, and flag conflicts
before anyone builds the wrong thing. The host approves every change to the
shared plan.

  * Use individual AI chat to explore ideas, ask questions and learn
      How the prototype delivers it: Private chats with streamed AI answers,
        history, rename, delete and search
  * Create and organise reusable outputs
      How the prototype delivers it: Individual workspace: named items
        (content, email, code, image, audio) in projects
  * Confirm one shared project brief and generate assigned tasks
      How the prototype delivers it: PM agent drafts the brief; the team
        edits it and the host approves; PM proposes tickets with owners
  * Expose conflicts and affected work before implementation
      How the prototype delivers it: Architect agent flags duplicates and
        contradictions, with source messages, affected tasks and hours
  * (challenge brief) Cross-check PRDs, bug tickets and meeting summaries to
    detect blockers and resolve architectural conflicts
      How the prototype delivers it: Sources: paste a PRD, bug ticket or
        meeting summary; the Architect checks every statement against the
        chat, the other sources and the tasks; the PM agent flags blockers
        and triages bugs into tasks

==============================================================================
FEATURES
==============================================================================

The four areas
--------------

  * 💬 Individual chat
      What you can do: Private AI answers, ideas, explanations and learning.
        Streamed Markdown replies, chats grouped by date, rename, delete and
        search. Nothing here reaches the group unless you share it.
  * 👥 Group chat
      What you can do: Channels, replies, reactions and a typing indicator.
        Choose public AI (the answer is posted for everyone) or private help
        (only you see it; the group sees just "Name used AI"). The host can
        switch either mode off.
  * 🗂️ Individual workspace
      What you can do: Generate named items: content, email drafts, code
        (stored as text, never executed), images and audio. Organise them in
        projects, search by name, edit them, follow a link back to the
        source chat, and share an item to the group or make it private
        again.
  * 🏢 Group workspace
      What you can do: Seven sections with live count badges: Brief (with
        Parallel Futures), Sources (PRDs, bug tickets, meeting summaries),
        Tasks (any member can submit one; the host approves), Decisions
        (each lists the tasks it changes), Alerts (resolve, or dismiss a
        false alert), Activity (the multi-agent event stream, downloadable
        as JSON) and Team outputs.

The AI agents
-------------

  * 🧭 PM agent
      Role: Reads the team chat, drafts the project brief, then proposes
        tickets: task, priority, estimated hours and a suggested owner.
        Finds blockers in meeting summaries and other sources, and triages
        bug tickets (category, priority, hours) into proposed fix tasks
  * 🏗️ Architect agent
      Role: Uses embeddings and FAISS to find claims related to each new
        chat message, source-document statement or submitted task, then
        decides: duplicate, contradiction, assumption mismatch, unclear or
        none
  * 🧪 QA agent
      Role: After the host resolves an alert, writes acceptance criteria for
        every affected task

The agents run as three LangGraph graphs: planning (pm_brief → pm_tickets),
chat review (retrieve → architect) and source review (split → retrieve →
architect → pm_blockers → pm_triage).

Innovations (deck slide 10)
---------------------------

- Decision impact. Approved decisions are linked to the tickets they affect.
  Each affected ticket is shown once, and the alert totals only the team-
  confirmed estimated hours (e.g. "Impact: 4 tasks, about 20 hours").
- Parallel Futures. Members answer the same concrete scenario independently.
  Comparing the answers reveals the hidden assumptions behind them.
- Human Unit Test. The task's creator and its assignee each describe the task
  in their own words. A mismatch is flagged before work starts.
- Evidence on every flag. Every alert quotes the exact source messages and who
  wrote them, or the exact line of the PRD, bug ticket or meeting summary. The
  host approves the resolution, or dismisses a false alert without recording a
  decision.

Host approvals
--------------

The host approves the brief, the task assignments (including tasks members
submit and fix tasks the PM agent proposes from bug tickets), every task edit,
alert resolutions and dismissals and who can use AI in the group. The server
enforces this, not just the interface, and tests cover it.

==============================================================================
HOW IT WORKS: THE AGENT PIPELINE
==============================================================================

The logic, step by step
-----------------------

1. Brief. The PM agent reads the busiest channel, so off-topic chatter in
   #general stays out, and drafts a structured brief: title, summary, goals,
   non-goals and assumptions. Any edit sends the brief back to draft until the
   host approves it again.
2. Tickets. After approval, the PM agent proposes 3–6 tickets. Near-duplicate
   proposals are dropped. Owners are matched to team members. The host
   approves the assignments.
3. Conflict review. Once a brief is approved, every new non-question message
   is compared with earlier messages:
   - Retrieval: all-MiniLM-L6-v2 sentence embeddings searched with a FAISS
     inner-product index. A TF-IDF fallback is used if the model can't load.
   - Meaning check: the Architect agent classifies each related pair and keeps
     the most serious issue (contradiction > assumption > duplicate >
     unclear).
   - Impact: related tickets are retrieved for both source messages, de-
     duplicated, and their confirmed hours summed.
4. Sources. Any member adds a PRD, bug ticket or meeting summary. It is split
   into statements, and each is retrieved against the chat, the other sources
   and (for bugs) existing bug reports and fix tasks:
   - Conflicts: the Architect keeps contradictions and assumption mismatches,
     one alert per statement, quoting every message or line it disagrees with.
     The chat review also checks new messages against these sources.
   - Blockers: the PM agent lists statements that stop or delay work ("blocked
     until…", "waiting on…") as high-severity alerts with the affected tasks.
   - Bugs: a bug ticket is triaged (category, priority, hours) into a proposed
     Fix task for the host to approve. A report that repeats an earlier bug is
     flagged as one duplicate alert instead. A bug in a feature is not treated
     as a duplicate of the feature.
   - Rate limits: at most 8 Architect checks run per document, strongest
     matches first, to stay inside free-tier limits.
5. Task submissions. Any member can submit a task. It waits for the host, and
   the Architect checks it against existing tasks so the same work isn't added
   twice.
6. Resolution. The host picks or writes a resolution. It is recorded as a
   decision listing the tasks it changes, and the QA agent writes acceptance
   criteria for each affected task. A false alert can be dismissed instead,
   with no decision and no task changes.
7. Live updates. Every step is broadcast over WebSockets to each member's open
   windows, and logged in Activity with a timestamp. Download event log saves
   the whole multi-agent event stream as JSON.

Reliable AI output
------------------

- Every AI JSON answer is validated with a Pydantic schema (app/schemas.py).
  If it doesn't validate, the error is sent back to the model for another try.
- Answers are cached. Architect checks are batched: the related pairs for one
  message or document go to the model in a single call, and any pair missing
  from the reply falls back to its own call. Rate limits and timeouts are
  retried with exponential backoff. Together, as slide 11 promises, these keep
  the free tier usable.
- Without an API key, or if the provider fails, the app switches to labelled
  demo mode. Text answers become fixed stand-ins, and the decisions come from
  transparent text rules. The header always says which mode is active.

Architecture
------------

==============================================================================
DATA AND EVALUATION
==============================================================================

  * Real GitHub issues from github.com/golang/go
    (https://github.com/golang/go/issues): 45 duplicate pairs (36 originals)
    and 260 labelled issues
      Where: data/github_issues_golang.json (built by
        scripts/fetch_github_issues.py)
      Used for: Benchmark: de-duplicate, search, cluster and triage
  * 18 planted conflict scenarios, each with 5 distractor claims
      Where: scripts/evaluate_conflicts.py
      Used for: Detection and evidence correctness (deck: 15+ planted
        conflicts)
  * The same 18 scenarios run end to end
      Where: scripts/simulate_conflict_resolution.py
      Used for: Simulated conflict-resolution tests
  * Demo team conversation (written by the team, synthetic)
      Where: scripts/seed_demo.py
      Used for: The staged demo: guest checkout, then a new login
        requirement
  * 16 labelled duplicate pairs (synthetic, marked SYNTHETIC)
      Where: data/sample_duplicates_SYNTHETIC.csv
      Used for: Smoke test for duplicate precision and recall

Real GitHub Issues benchmark
----------------------------

Why GitHub's own data rather than Kaggle's copy. The deck and the challenge
name the Kaggle GitHub Issues dataset. Its dumps carry issue titles and
bodies, but no record of which issues are duplicates, so they cannot score de-
duplication. We used the same kind of data, real GitHub issues, taken from the
Go project with its own answer key:
- Duplicates: the maintainers' "Duplicate of #N" comments.
- Triage: the FeatureRequest, Documentation, NeedsFix and release-blocker
  labels.

scripts/evaluate_duplicates.py still accepts any labelled CSV, including one
built from Kaggle.

How each part is scored:
- De-duplication: every real pair is matched with a hard negative, the same
  duplicate paired with another issue from the same Go component (e.g. two
  cmd/compile: issues).
- Search: each duplicate is ranked against all 36 originals.
- Clustering: groups found by similarity are compared with the maintainers'
  duplicate groups.
- Triage: compares the PM agent's category and priority with the labels.

Measured on 22 October 2026, with Sentence Transformers + FAISS search and the
live model openai/gpt-oss-120b on Groq:

    De-duplication (45 real duplicates + 45 same-component hard negatives)
      Search alone, fixed threshold 0.50     precision 0.750  recall 0.933  F1 0.832
      Architect agent, built-in rules        precision 0.808  recall 0.467  F1 0.592
      Architect agent, live LLM (80 pairs)   precision 1.000  recall 0.575  F1 0.730
    
    Search: each duplicate ranked against all 36 originals
      recall@1 0.600   recall@5 0.756
    
    Clustering (81 issues, 36 true duplicate groups)
      fixed threshold 0.50                   25 groups  pairwise precision 0.320  recall 0.859  F1 0.466
      best threshold 0.75 (tuned on this set) 43 groups  pairwise precision 0.565  recall 0.609  F1 0.586
    
    Triage by the PM agent (bug / feature / docs)
      built-in rules, 260 issues             accuracy 0.558   release-blockers marked High 4/8
      live LLM, 40 issues                    accuracy 0.800   release-blockers marked High 1/1, false High 6/39

What this shows:
- Search is the strong part. It surfaces 93% of real duplicates, and the true
  original is in the top 5 for three-quarters of them.
- The live Architect is careful. Every pair it called a duplicate really was
  one (precision 1.00), but it confirms only 58%, because Go duplicates are
  often worded very differently. In the app that's the right trade-off: a
  missed duplicate costs little, while a false alert wastes the host's time.
- Live AI triage is clearly better than the rules (80% vs 56%).
- Clustering whole issue sets is the weakest part, and the most obvious next
  improvement.

These are measurements on a small real sample, not a general accuracy claim.
As the deck says, Stage 1 makes no accuracy claims. Raw results are in
data/github_issues_golang_results.json. Re-run them with python -m
scripts.evaluate_github_issues --live 40.

Planted conflicts, simulation, tests
------------------------------------

    pytest                         32 passed
    
    evaluate_conflicts             18 scenarios, each with 5 distractors
      built-in rules               detection 18/18 · evidence 16/16
      live LLM (gpt-oss-120b)      detection 17/18 · evidence 15/16
                                   (the miss: an "unclear" pair the model called "no issue", so no false alarm)
    
    simulate_conflict_resolution   18 scenarios end to end (built-in rules)
                                   detect 18/18 · evidence 16/16 · impact 16/16 · resolve 16/16
                                   QA criteria 15/15 · closed stays closed 16/16
                                   flagged scenarios that completed every step: 16/16
    
    evaluate_duplicates            16 synthetic pairs · precision 1.000 · recall 1.000

  | Honest note. The planted scenarios and the synthetic pairs were
  | written by the team, so they show the pipeline works end to end; the
  | GitHub benchmark above is the real-world check. With the TF-IDF
  | fallback instead of embeddings (used on the free hosted demo), an
  | earlier run scored 17/18 on planted conflicts.

To score your own labelled pairs (for example, a Kaggle subset you have
labelled):

    python -m scripts.evaluate_duplicates path/to/labelled.csv --limit 500

The CSV needs one labelled pair per row: text_a,text_b,is_duplicate (or
title_a,title_b,label).

==============================================================================
SETUP AND INSTALLATION
==============================================================================

Requirements: Python 3.11 or newer, and about 2 GB of disk space for PyTorch
and the embedding model.

The easiest way is run.bat (Windows) or bash run.sh (macOS/Linux): each one
creates a virtual environment, installs everything once, creates .env, starts
the app and opens your browser. To do the same by hand:

    git clone https://github.com/kavin-beep/Projecute-OlympAI-Hackathon.git
    cd Projecute-OlympAI-Hackathon
    python -m venv .venv
    # Windows: .venv\Scripts\activate    macOS/Linux: source .venv/bin/activate
    pip install -r requirements.txt

Optional, for live AI: copy .env.example to .env and put your own Groq
(https://console.groq.com) key in GROQ_API_KEY. Without a key the app runs in
labelled demo mode, and the whole demo still works.

The first run downloads the all-MiniLM-L6-v2 embedding model (about 90 MB)
from Hugging Face. Offline, the app uses the TF-IDF fallback instead.

==============================================================================
RUNNING THE MAIN CODE
==============================================================================

    python main.py

Open http://127.0.0.1:8000 in two browser windows. Sign in as Kavin K (the
host) in one and Sritharan N S in the other. Each window keeps its own
session. On a fresh database the demo team and project are created
automatically.

  * python main.py
      What it does: Start the web app (the main entry point)
  * python -m scripts.seed_demo
      What it does: Reset to the staged demo (stops just before the
        conflict)
  * python -m scripts.seed_demo --full
      What it does: Reset and also run the conflict and its resolution
  * python -m pytest
      What it does: Run the tests
  * python -m scripts.evaluate_conflicts
      What it does: Planted-conflict evaluation
  * python -m scripts.evaluate_duplicates data/sample_duplicates_SYNTHETIC.csv
      What it does: Duplicate evaluation (synthetic smoke test)
  * python -m scripts.simulate_conflict_resolution
      What it does: Simulated conflict-resolution tests, end to end
  * python -m scripts.evaluate_github_issues
      What it does: Real GitHub Issues benchmark: de-duplicate, cluster,
        triage (add --live 40 for the live LLM)
  * python -m scripts.fetch_github_issues
      What it does: Re-download the GitHub Issues benchmark data (already
        included)

Settings (environment variables or .env):

  * GROQ_API_KEY
      Default: (empty)
      Purpose: Enables live AI; empty means demo mode
  * GROQ_MODEL
      Default: llama-3.3-70b-versatile
      Purpose: Groq model; tested with openai/gpt-oss-120b
  * HOST / PORT
      Default: 127.0.0.1 / 8000
      Purpose: Where the server listens
  * DEMO_PASSCODE
      Default: (empty)
      Purpose: When set, Load demo asks for it before resetting
  * PROJECUTE_DB
      Default: data/projecute.db
      Purpose: SQLite database file

Run with Docker (optional)
--------------------------

The same app runs unchanged in a container on any Docker host, and live
updates over WebSockets keep working. Pass the API key as an environment
variable or a host secret, never in the files. deploy/huggingface/README.md
holds the page settings for a Hugging Face Docker Space, which needs a paid
Hugging Face plan.

    docker build -t projecute .
    docker run -p 7860:7860 -e GROQ_API_KEY=your-key -e DEMO_PASSCODE=choose-one projecute

==============================================================================
TROUBLESHOOTING
==============================================================================

  * python is not recognised (Windows)
      Fix: Reinstall Python 3.11+ and tick Add python.exe to PATH, then open
        a new terminal
  * The page doesn't load right away
      Fix: The first start downloads and loads the AI embedding model; wait
        about a minute. run.bat / bash run.sh open the browser when it's
        ready
  * Address already in use / port 8000 busy
      Fix: Start on another port: PORT=8010 python main.py (Windows: set
        PORT=8010 then python main.py)
  * Header says Demo mode
      Fix: No Groq key is set. Add one to .env and restart; see Quick start
  * No internet on first run
      Fix: The app still starts and uses the TF-IDF search fallback;
        Settings → Advanced shows which search is active
  * Want a clean demo again
      Fix: Press Load demo on the sign-in screen, or run python -m
        scripts.seed_demo

==============================================================================
TWO-MINUTE DEMO SCRIPT
==============================================================================

1. The problem (10s). Two windows side by side: Kavin the host and Sritharan a
   member. "Two people, one project, and no shared idea of what was agreed."
2. Shared workspace → Brief (20s). The PM agent wrote the brief from the
   team's own chat, and the host approved it. Tasks shows the tasks with
   owners, priorities and estimates the team confirmed.
3. The scope change (25s). In Sritharan's window, post in #checkout:
  | Update from the client: every customer must log in before they can
  | pay, so checkout now requires an account.
4. The alert (35s). In Kavin's window, open Alerts. The card says the
   statements disagree about checkout and quotes both source messages with
   their authors. It states the impact, for example "Impact: 4 tasks, about 20
   hours" (the exact tasks depend on what the PM agent proposed).
5. The host decides (20s). Pick a resolution and press Approve this
   resolution. Sritharan's window updates on its own: the alert is resolved, a
   decision is recorded, and the QA agent's acceptance criteria appear.
6. Privacy (20s). In Sritharan's window, switch to Private help and ask
   anything. Kavin's window shows only "Sritharan N S used AI", with no
   prompt, answer or topic. Finish on Activity: every agent action,
   timestamped.

Extra (60s): PRDs, bug tickets and meeting summaries. Open Sources → Add a
source and paste any of these:

  * PRD
      Title: Checkout PRD v2
      Text to paste: - Every customer must create an account and log in
        before checkout.; - The checkout summary screen shows the cart total
        before payment.
      What happens: Contradiction alert quoting the PRD line and the chat
        messages that said no login
  * Meeting summary
      Title: Sprint sync
      Text to paste: - Payment step is blocked until the payment provider
        approves our sandbox account.; - QA is waiting on test cards from
        finance.
      What happens: Two blocker alerts with the affected tasks
  * Bug ticket
      Title: Wrong total on summary
      Text to paste: The summary screen before payment shows the cart total
        without shipping, so the total is wrong.
      What happens: Triaged into a proposed Fix task; paste a reworded copy
        as a second bug ticket to see it flagged as a duplicate

==============================================================================
EVERY FILE AND ITS PURPOSE
==============================================================================

  * main.py
      Purpose: Main entry point. Starts the web server (python main.py);
        reads HOST, PORT and OPEN_BROWSER
  * run.bat
      Purpose: One-command start for Windows: virtual environment, one-time
        install, .env, start, open browser
  * run.sh
      Purpose: The same one-command start for macOS and Linux
  * render.yaml
      Purpose: Render Blueprint for the hosted live demo (free plan); the
        Groq key is entered in Render as a secret
  * requirements-render.txt
      Purpose: Lighter dependency list for the hosted demo (no PyTorch, so
        it fits in 512 MB)
  * .github/workflows/keep-alive.yml
      Purpose: Pings the hosted demo every 10 minutes so it never sleeps
  * app/
      Purpose: Backend (Python)
  * app/__init__.py
      Purpose: Marks app as a Python package
  * app/main.py
      Purpose: FastAPI application: every HTTP endpoint for the four areas,
        sign-in, permission checks (member, host, same group), server-sent
        events for streamed chat, the WebSocket endpoint and the static
        frontend
  * app/pipeline.py
      Purpose: The group pipeline as plain functions over the database:
        brief → tickets → conflict review → decision → QA. Returns the live
        events to broadcast
  * app/agents.py
      Purpose: The PM, Architect and QA agents, Parallel Futures and Human
        Unit Test comparisons, the two LangGraph graphs (planning and
        review), and the rule-based demo-mode logic
  * app/llm.py
      Purpose: Groq adapter: JSON validation with retries, answer cache,
        exponential backoff, streaming, and labelled demo mode. Never logs
        or returns the key
  * app/retrieval.py
      Purpose: Related-claim search with Sentence Transformers + FAISS, and
        the TF-IDF fallback
  * app/schemas.py
      Purpose: Pydantic schemas that every AI JSON answer is validated
        against
  * app/db.py
      Purpose: SQLite schema, query helpers, membership and host checks,
        activity log
  * app/ws.py
      Purpose: WebSocket hub: tracks open windows per user and pushes live
        events
  * app/media.py
      Purpose: Image and audio adapter; labelled placeholder mode when no
        provider key is set
  * static/
      Purpose: Frontend (HTML, CSS, JavaScript, no build step)
  * static/index.html
      Purpose: Page layout: sign-in screen, navigation rail, the four areas,
        side panel
  * static/styles.css
      Purpose: Visual design, light and dark themes, mobile layout
  * static/logo.svg
      Purpose: Projecute logo (original)
  * static/js/app.js
      Purpose: App start-up, sign-in, navigation between areas, theme, Load
        demo
  * static/js/api.js
      Purpose: API calls, streamed responses, the live WebSocket connection
        and event bus
  * static/js/ui.js
      Purpose: Shared UI helpers: elements, icons, dialogs, toasts, safe
        Markdown, time formatting
  * static/js/chat.js
      Purpose: Individual chat
  * static/js/group.js
      Purpose: Group chat: channels, messages, reactions, replies, AI modes,
        host controls
  * static/js/workspace.js
      Purpose: Individual workspace: projects, named items, sharing
  * static/js/board.js
      Purpose: Group workspace: Brief, Tasks, Decisions, Alerts, Activity,
        Team outputs, Parallel Futures, Human Unit Test
  * scripts/
      Purpose: Command-line tools
  * scripts/seed_demo.py
      Purpose: Resets the database and stages the demo team, chat, approved
        brief and tasks
  * scripts/evaluate_conflicts.py
      Purpose: Scores the 18 planted conflict scenarios
  * scripts/evaluate_duplicates.py
      Purpose: Scores duplicate detection on any labelled CSV of pairs
  * scripts/simulate_conflict_resolution.py
      Purpose: Runs every planted scenario through the full pipeline:
        detect, evidence, impact, host resolution, decision, QA, closed
  * scripts/fetch_github_issues.py
      Purpose: Downloads the real GitHub Issues benchmark set from
        github.com/golang/go (public API, resumable)
  * scripts/evaluate_github_issues.py
      Purpose: Benchmarks de-duplication, search, clustering and triage on
        that set
  * scripts/__init__.py
      Purpose: Marks scripts as a package so the tools run with python -m
  * tests/
      Purpose: Automated tests (pytest)
  * tests/conftest.py
      Purpose: Test setup: a separate temporary database and a seeded demo
  * tests/test_privacy.py
      Purpose: Private chats, items, private AI help, group isolation, no
        cross-group access
  * tests/test_approvals.py
      Purpose: Host-only approvals: brief, assignments, task edits, AI
        access, resolutions
  * tests/test_live_updates.py
      Purpose: WebSocket updates reach the other member's window
  * tests/test_llm_recovery.py
      Purpose: Live AI comes back by itself after a provider error
  * tests/test_sources.py
      Purpose: PRD conflicts, meeting-summary blockers, bug triage and
        duplicate bugs, member task submissions, dismissing false alerts,
        decision impact, the event-log download
  * tests/__init__.py
      Purpose: Marks tests as a package
  [data/]
  * data/sample_duplicates_SYNTHETIC.csv
      Purpose: 16 synthetic labelled pairs for the duplicate smoke test
  * data/projecute.db
      Purpose: SQLite database, created at run time (git-ignored)
  * data/github_issues_golang.json
      Purpose: Real public issues from github.com/golang/go: duplicate pairs
        (with the maintainers' "Duplicate of #N" links) and labelled triage
        examples
  * data/github_issues_golang_results.json
      Purpose: The latest benchmark results, as JSON
  [assets/]
  * assets/banner.svg, assets/pipeline.svg
      Purpose: Animated images used in this README (original)
  * assets/source-review.svg, assets/architecture.svg
      Purpose: Source-review and architecture diagrams used in this README
        (original)
  [Project files]
  * requirements.txt
      Purpose: Python dependencies
  * .env.example
      Purpose: Template for .env (no real keys)
  * .gitignore
      Purpose: Keeps .env, the database and caches out of git
  * .gitattributes
      Purpose: Keeps Windows line endings in run.bat and Unix line endings
        in run.sh
  * Dockerfile
      Purpose: Container image for Hugging Face Spaces or any Docker host
  * .dockerignore
      Purpose: Keeps .env and local data out of the image
  * deploy/huggingface/README.md
      Purpose: Page settings for an optional Hugging Face Docker Space
        (needs a paid Hugging Face plan)
  * README.md
      Purpose: This document
  * README.txt
      Purpose: The same document as plain text, for reading without a
        Markdown viewer

==============================================================================
DEPENDENCIES
==============================================================================

All listed in requirements.txt. Install with pip install -r requirements.txt.

  * fastapi
      Used for: Web framework for the HTTP API and WebSockets
  * uvicorn[standard]
      Used for: Server that runs the FastAPI app
  * websockets
      Used for: WebSocket support for live updates
  * pydantic
      Used for: Validating every AI JSON answer against a schema
  * python-multipart
      Used for: Form and request-body parsing for FastAPI
  * groq
      Used for: Client for the Groq free-tier LLM API
  * langgraph
      Used for: Orchestrating the agent graphs
  * sentence-transformers
      Used for: Local sentence embeddings (all-MiniLM-L6-v2)
  * faiss-cpu
      Used for: Fast similarity search over embeddings
  * numpy
      Used for: Vector maths and the TF-IDF fallback
  * pytest, httpx
      Used for: Automated tests

No frontend framework or build step: the browser loads plain JavaScript
modules. Fonts (Sora, IBM Plex Sans, IBM Plex Mono) come from Google Fonts
under the SIL Open Font License.

==============================================================================
PRIVACY, ETHICS AND SECURITY
==============================================================================

Following deck slide 14, these rules are enforced by the server, not just
hidden in the interface:

- Individual chats enter the group only through explicit sharing.
- The group AI reads only that group's messages. Private prompts and replies
  stay isolated.
- Private AI use is announced, but the prompt, answer and topic stay hidden.
- The host approves settings, permissions, roles and changes to the shared
  plan.
- Groups are isolated. Channels, messages and scenarios must belong to the
  group named in each request.
- Public or synthetic demo text only, and API keys live in .env or Space
  secrets, never in the code.
- Code is never executed: generated code is stored and edited as text only.

==============================================================================
AI TOOLS USED
==============================================================================

The competition rules require naming every AI tool used. We used:

  * OpenAI ChatGPT / Codex
      What it was used for: Generated most of the application code under the
        team's direction, and helped with brainstorming, project guidance
        and presentation preparation
  * Claude Code (Anthropic, Claude Opus 5.5)
      What it was used for: Reviewed the prototype against the deck, the
        challenge brief and the submission rules; fixed cross-group access
        bugs; made task edits host-only; added the source cross-checks
        (PRDs, bug tickets, meeting summaries), blocker detection, bug
        triage, member task submissions, false-alert dismissal, decision
        impact and the event-log download; built the GitHub Issues benchmark
        and the simulated conflict-resolution tests; added code comments and
        lint fixes, the hosting and run scripts, and this README

The team chose the problem, designed the concept, the deck and the demo story,
and directed the AI tools.

AI models inside the app (runtime, not used to write code):

  * Groq-hosted LLM (openai/gpt-oss-120b, configurable)
      Purpose: PM, Architect and QA agents; chat answers; workspace
        generation
  * sentence-transformers/all-MiniLM-L6-v2
      Purpose: Embeddings for related-claim retrieval

==============================================================================
WHAT WAS VERIFIED, AND WHAT WAS NOT
==============================================================================

Verified:

- 32 automated tests: privacy, host approvals, group isolation, the demo
  passcode, live-AI recovery, live updates, and source cross-checks (PRD
  conflicts, blockers, bug triage, duplicate bugs, task submissions,
  dismissals, decision impact, event-log download).
- In the browser: adding a PRD raised a contradiction quoting the PRD line and
  both chat messages; approving it recorded a decision listing T-1 to T-4; the
  event log downloaded as JSON; no console errors.
- ruff lint passes with no findings.
- The full demo flow: brief → host approval → tasks → new login requirement →
  alert with sources, affected tasks and hours → host resolution → QA
  criteria.
- Sentence Transformers + FAISS retrieval and both evaluations (results
  above).
- The demo flow on live AI (openai/gpt-oss-120b) with the hosted build's
  dependencies: the PM agent wrote the brief and 5 tasks, and the new login
  requirement raised a contradiction alert quoting Adrian's and Sritharan's
  messages, with "3 tasks, about 15 hours" of impact. The server used about
  100 MB of memory.
- Earlier browser testing with two users at once: all four areas, both themes,
  and the 390 px mobile layout.

Not yet verified:

- Host resolution and QA criteria on live AI in the browser (covered in demo
  mode and by the tests).
- Very large documents and many simultaneous judges on the shared free-tier
  key.
- More than three users, more than one group per person, and long sessions.

==============================================================================
KNOWN LIMITATIONS
==============================================================================

- No passwords. Picking a name signs you in. This is a prototype, not an
  authentication system, but the permission rules behind it are real and
  tested.
- Demo mode text is a fixed stand-in. It is clearly labelled. The conflict
  decisions in demo mode come from transparent text rules.
- The TF-IDF fallback matches wording, not meaning, so it is used only when
  the embedding model can't load.
- Conflict review runs on new messages after the brief is approved, and skips
  questions. Alerts → Check the chat again re-scans everything.
- Images and audio are placeholders without a media provider key, labelled in
  the interface.
- SQLite, single process. Fine for a demo, not for many concurrent teams. In a
  Docker container the data resets when the container is recreated.
- After a provider error the app answers in demo mode for 30 seconds, then
  returns to live AI by itself. The header shows which mode is active.
- The hosted demo shares one Groq free-tier key, so many judges at the same
  moment can hit its rate limit. Requests are retried with backoff first.

==============================================================================
FUTURE SCOPE: WHAT PROJECUTE DOESN'T DO YET
==============================================================================

Projecute is a Stage 1 prototype. This is an honest list of what it and its AI
can't do yet, and what we plan to add. Projecute AI gives the same list when
asked what will be improved.

Planned in our Stage 1 deck (slide 13)

- Connect GitHub issues, document tools and meeting-summary sources
  automatically. In the prototype, sources are pasted in by hand.
- Support larger teams and more detailed permission policies.
- Add multilingual evaluation and improved dependency visualisation.
- Expand beyond the prototype after measured user feedback.

Not in the prototype yet: the app

- Teams: only the demo team exists. Creating groups, inviting members and
  changing the host can't be done from the app yet.
- Sign-in: you pick a name. There are no passwords, accounts or password
  reset.
- Sources: text is pasted in. Uploading PDF or Word files isn't supported.
- Tasks: tasks are proposed and approved, but there's no board for moving them
  through in progress and done, no due dates, and no reminders.
- Notifications: updates appear live in open windows only. There are no email
  or phone notifications.
- Dependencies: each alert lists the tasks it affects, but there's no
  dependency graph.
- Image and audio: these are labelled placeholders. Images are drawn patterns,
  and audio is the browser reading a script aloud. Real image and audio
  generation will be added in future development.
- Hosting: the free hosted demo runs on one server with a SQLite database, so
  its data resets when it restarts. It also uses the lighter word-matching
  search instead of embeddings.

Not in the prototype yet: the AI

- Autonomy: the PM, Architect and QA agents work in a pipeline that the host
  approves. They don't discuss with each other or act on their own.
- Memory: the chat assistant remembers the last 20 messages of a conversation,
  and nothing across separate chats.
- Reach: the AI can't browse the web, read uploaded files or run code.
- Accuracy: on real GitHub issues, duplicate detection is careful (no false
  alarms in our test) but misses about 4 in 10 real duplicates, and grouping
  whole sets of similar issues is the weakest part. Improving both is the next
  technical step.
- Languages: tested in English only.
- Availability: live AI depends on the Groq free tier. If it errors or hits
  its rate limit, answers fall back to labelled demo mode for 30 seconds.

==============================================================================
CREDITS AND LICENCES
==============================================================================

Projecute's own code, interface, logo, icons, banner and diagrams were made
for this project, with the AI tools listed under AI tools used. Everything
else it uses is listed here with its source and licence. No code from other
projects was copied into this repository. Third-party libraries are installed
from requirements.txt and are not bundled in it.

Libraries (installed with pip install -r requirements.txt)

  * FastAPI (https://fastapi.tiangolo.com)
      Used for: Web framework, HTTP API
      Licence: MIT
  * Uvicorn (https://www.uvicorn.org)
      Used for: Web server
      Licence: BSD-3-Clause
  * websockets (https://websockets.readthedocs.io)
      Used for: Live updates
      Licence: BSD-3-Clause
  * Pydantic (https://docs.pydantic.dev)
      Used for: Validating AI output
      Licence: MIT
  * python-multipart (https://github.com/Kludex/python-multipart)
      Used for: Request parsing
      Licence: Apache-2.0
  * Groq Python SDK (https://github.com/groq/groq-python)
      Used for: Calling the language model
      Licence: Apache-2.0
  * LangGraph (https://github.com/langchain-ai/langgraph)
      Used for: Agent graphs
      Licence: MIT
  * Sentence Transformers (https://www.sbert.net)
      Used for: Text embeddings
      Licence: Apache-2.0
  * FAISS (https://github.com/facebookresearch/faiss) (faiss-cpu)
      Used for: Similarity search
      Licence: MIT
  * NumPy (https://numpy.org)
      Used for: Vector maths, TF-IDF fallback
      Licence: BSD-3-Clause
  * PyTorch (https://pytorch.org)
      Used for: Runs the embedding model (installed by Sentence
        Transformers)
      Licence: PyTorch's open-source licence
  * pytest (https://pytest.org), HTTPX (https://www.python-httpx.org)
      Used for: Tests
      Licence: MIT, BSD-3-Clause
  * Ruff (https://docs.astral.sh/ruff/)
      Used for: Lint checks during development (not shipped)
      Licence: MIT

AI models used by the running app

  * sentence-transformers/all-MiniLM-L6-v2 (https://huggingface.co/sentence-
    transformers/all-MiniLM-L6-v2)
      Used for: Embeddings for related-claim search
      Licence / terms: Apache-2.0
  * openai/gpt-oss-120b (https://huggingface.co/openai/gpt-oss-120b), served
    by Groq (https://groq.com)
      Used for: PM, Architect and QA agents in live mode
      Licence / terms: Apache-2.0 model; Groq API terms
  * llama-3.3-70b-versatile (Groq, only if GROQ_MODEL is not set)
      Used for: Default model
      Licence / terms: Llama 3.3 Community License; Groq API terms

Fonts, images and services

  * Sora, IBM Plex Sans, IBM Plex Mono fonts
      Source: Google Fonts (https://fonts.google.com)
      Licence / terms: SIL Open Font License 1.1
  * README badges
      Source: shields.io (https://shields.io)
      Licence / terms: Badge images generated by the shields.io service
  * Hosting of the live demo
      Source: Render (https://render.com) free plan
      Licence / terms: Render terms of service
  * Keep-alive job
      Source: GitHub Actions
      Licence / terms: GitHub terms of service

Data

- GitHub Issues benchmark (data/github_issues_golang.json): issue titles,
  bodies, labels and links from the public github.com/golang/go issue tracker
  (https://github.com/golang/go/issues), collected through GitHub's public
  API. The text belongs to the people who wrote those issues. It is used here
  only to evaluate the prototype; each entry keeps its original issue number
  and link. The duplicate answer key is the Go maintainers' own "Duplicate of
  #N" comments.
- Demo conversation, planted conflict scenarios and the duplicate smoke-test
  sample were written by the team for this prototype and are marked as
  synthetic.
- The challenge brief names the Kaggle GitHub Issues dataset. No Kaggle data
  is included; see Data and evaluation for why.

==============================================================================
TEAM AND ACKNOWLEDGEMENTS
==============================================================================

  * Kavin K (team leader)
      Contribution: Backend, permissions and live collaboration
  * Adrian Rohith
      Contribution: Chat interface and connected workspace
  * Sritharan N S
      Contribution: AI workflow, evaluation and demo preparation

Thanks to the OlympAI Hackathon organisers and MethodAI, to our mentor for her
guidance and support, and to the open-source projects listed under
Dependencies.

Projecute — from team discussion to approved project work.
