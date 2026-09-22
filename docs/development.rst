.. Copyright (C) 2026 Maxime P. DEMENTYEV
.. SPDX-License-Identifier: GPL-3.0-only
.. Field evidence and the feedback loop — check_rst project

##################################
check_rst development and review
##################################

This page records how evidence from real documentation work feeds back into
``check_rst``: what users and reviewers should report, and which concrete
catches justify the project's rules.  It is not the Python implementation or
build-integration manual; repository development practice lives in
``AGENTS.md``, while packaging, installation, and documentation-build
boundaries live in :doc:`integration`.

*****************************************************
The feedback loop: you are also the tool's reviewer
*****************************************************

``check_rst`` is young (July 2026) and still adapting.  The contract is
therefore two-way: you are not a passive consumer of the oracle — you
know reStructuredText, docutils, and Sphinx semantics, you know what
other documentation linters do, and you know what is and is not
automatable.  That makes you qualified to notice when the tool is wrong,
incomplete, or awkward — and expected to say so.

Report to the user, at the moment you notice it — five distinct report
categories, each its own subsection rather than a bullet list for the
same reason as :doc:`example`'s commentary: each is
independently meaningful, and section visibility in ``outline`` is
this page's own argument, not just its subject.

================================
A finding you believe is wrong
================================

The tool models docutils; the model can drift from the reality.  When
``check_rst`` and an actual docutils/Sphinx parse disagree, that
disagreement *is* the bug report — state both sides with evidence.

========================================
A question the oracle could not answer
========================================

If you needed something from a document that ``outline``/
``context``/``--verbose`` do not surface (a directive inventory or a
directive's resolved options), name the gap — that is a feature request
with a concrete use-case attached.  Section and leaf-entry extents and
cross-reference targets are no longer examples of this gap: ranges,
``refs``, and ``context`` answer them directly.

===================================
A workaround you had to hand-roll
===================================

Shelling around the tool is a signal, not a solution —
``--recursive`` itself was born from a ``find | mapfile`` workaround
that kept being repeated.  If you write the same auxiliary command
twice, propose absorbing it.

=================================
Anything surprising ``fix`` did
=================================

A fix that changed more than expected, or output the verifier then
rejected, is top-priority feedback — never shrug and re-edit around
it.

=====================
Ecosystem knowledge
=====================

Capabilities of docutils/Sphinx the tool could leverage, or ideas from
comparable tools (``doc8``, ``rstcheck``, ``sphinx-lint``) worth
borrowing — offer them when relevant, with the trade-offs.

Two rules make the feedback useful.  *Never silently work around a
deficiency* — the workaround hides exactly the signal the tool's
evolution runs on.  And *verify before claiming*: probe the actual
behavior with a minimal reproduction the way any bug report deserves.
Several of the tool's core features — Phase 0 byte hygiene,
display-width measurement, the check/fix rule unification — began as
an AI's critical review of the previous version; :doc:`roadmap`
records this same kind of verified observation, with its evidence,
for every feature born the same way.

A worked case of the loop (2026-07-20, found in a downstream project's
``coding-standards.rst``): step 3 of the validation loop failed right
after step 2 — bare ``--fix`` had remapped the document's hierarchy
characters document-wide but left the pre-existing adornment widths
untouched, and only a *second* ``--fix`` converged.  The observation
("surprising ``--fix``, step 3 not clean") was reported with a minimal
reproduction instead of silently re-running, and the fix landed the
same day: the remap and the adornment pass now compose into a single
converging computation (every line the remap rewrites joins the fix
scope — git would report it as changed after the write anyway), and
``diff`` previews that composed result rather than the remap-only
intermediate.

A second worked case, the same day: Max noticed the footer's "top prose
words"/"rare prose words" lines had simply stopped appearing, with zero
trace of why — the observation itself ("I don't see word frequency at
the end of the output. Why?") was the whole bug report.  Root cause,
found by direct probing rather than guessing: Sphinx renamed the
per-language stopword constant, and did so *differently* on this
project's two dev hosts — lowercase ``english_stopwords`` on one
Sphinx version, uppercase ``ENGLISH_STOPWORDS`` re-exported from a
private ``sphinx.search._stopwords`` package on the other — and the
lookup only recognized one spelling, so it silently fell back to
"unavailable" and every caller treated that as "omit this line
entirely."  The fix has two parts, matching the two things that were
wrong: the lookup now tries every known spelling (so it survives
Sphinx renaming this again, which it has already done at least twice),
and — since a stat silently vanishing is precisely the failure mode the
whole tool exists to prevent elsewhere — the "unavailable" case is no
longer a silent return value at all.  It raises a dedicated exception
that surfaces as an explicit, *counted* WARNING in both the footer and
``--json``, so the next time this breaks, the run says so instead of
just going quiet.

**************************************
Real catches: evidence over argument
**************************************

A short, growing, dated list — proof outperforms argument, and this is
where the proof lives instead of sitting scattered as asides inside
unrelated entries below.

* **A single-colon directive typo, invisible for eight months**
  (calendar note, 2025-11-13) — ``.. code: bash`` is valid RST (a
  comment, not a directive), so the C++ listing it should have
  rendered silently vanished from the built HTML.  No phase flagged it
  until the mistyped-directive lint shipped; its first whole-corpus run
  found exactly this one true positive, zero false ones.
* **A confessed, habitual typo, caught by frequency asymmetry**
  (calendar note, 2025-06-25) — ``померял`` (1 occurrence) against
  ``померил`` (146) in the author's own Russian, one substitution
  apart.  Missed by an earlier 0.87 similarity cutoff (scored 0.857);
  caught once the one-edit-apart criterion replaced it.
* **A filename-propagated typo** (same 2025-06-25 note) —
  ``fameworks``/``frameworks``, the mistake living in a linked
  filename too, not just the prose referencing it.
* **Adjacent-line typo pair in real project docs** (a downstream project's
  ``hardware.rst``) — ``eclbs``/``eslbs``, one edit apart, on
  consecutive lines.
* **A hierarchy-scan blind spot, found writing the original guide**
  (2026-07-21) — a short (3-char), never-yet-promoted underline-only
  title was invisible to the first-appearance scan, silently colliding
  two headings onto the same adornment character.  See
  "``_first_appearance_adornments`` blind to short underline-only
  titles" in :doc:`roadmap` for the full account; recorded here
  because it is exactly this section's kind of evidence, not because
  it needs repeating twice.
* **An upstream content inconsistency, surfaced by a WARNING** (a downstream project's
  ``git-workflow.rst``, an independent Claude Code session,
  2026-07-21) — the same enumerated-step pattern was a real ``####``
  heading in one section and a bold-opener WARNING in another.  The
  catch itself was a heuristic the reviewing agents converged on
  (cross-checking the original Markdown for the same structural
  pattern rendered as a real header elsewhere) — not something
  check_rst detects directly — but the WARNING is what put the
  inconsistent instance in front of a reviewer at all.
* **An invalid explicit file kept two phases running on nothing**
  (calendar note, 2026-07-24) — ``check_rst --fix --verbose --outline``
  on a nonexistent path reported ``file not found`` correctly, but
  Phase 2 and Phase 3 still ran and printed their own banners before
  the run exited 1 — real work spent on a selection already known to
  be empty.  Fixed by the atomic preflight validator: every explicit
  input is confirmed a regular file before any phase starts, so an
  invalid selection is rejected once, immediately, not discovered by a
  phase that had nothing left to check.
* **``--refs`` blind to a toctree-only reference** (calendar note,
  2026-07-24) — ``check_rst --refs organs/index.rst`` reported empty
  outgoing and incoming lists for a file that is in fact both an
  aggregation hub (five ``toctree`` children) and itself included in
  the root index's own ``toctree`` — real edges ``find_references``
  simply had no node kind to see yet, since it only read
  ``pending_xref`` (role-based) references.  Fixed 2026-07-25 by
  reading ``toctree`` nodes' resolved ``includefiles`` too; re-run
  live against the same file after the fix confirms both directions
  now report correctly.
* **A table nested inside a list item printed at the wrong depth**
  (real output evaluation, 2026-07-26, the original guide) — a list-table
  added inside a bullet item ("A black-box subprocess test against a
  standing, combined Sphinx fixture" in :doc:`roadmap`) printed at the
  SAME indentation as its enclosing
  bullet list, sandwiched between two sibling items, because
  ``find_tables`` (and, it turned out, every other block finder except
  ``ListEntry``) computed depth by counting only enclosing ``section``
  ancestors — a fact that was harmless before ``ListEntry`` existed,
  since nothing else tracked "inside a list item" as its own depth
  level.  Fixed by generalizing ``_block_depth`` (originally
  list-only) into the one depth computation every block finder shares;
  reduces to the exact old behavior whenever there is no enclosing
  list, so every pre-existing depth test stayed green unchanged.  One
  case deliberately NOT fixed the same way:
  ``find_code_blocks_heuristic`` never touches the doctree at all (no
  ``--sphinx-src``, pure text scan), so it has no ancestors to walk —
  logged as this function's third KNOWN, ACCEPTED limitation, the same
  kind already documented for its other two.

****************************************************
Cross-review diagnostics: the output-boundary case
****************************************************

A Codex and Claude Code review exchange on 2026-09-22 began with one failing
``diff --fast`` regression and ended with a CLI-wide output contract.  Neither
reviewer's first account was complete.  The useful result came from treating
each claim as a hypothesis to reproduce, tracing the real control flow, and
letting counter-evidence change the proposed solution.  The implemented policy
and product contract live under "Surrogate-safe console and JSON path output"
in :doc:`roadmap`; this section records the reusable diagnostic method.

The durable findings were:

The capture stream is part of the test environment
  Pytest's default ``capfd`` text wrapper uses ``errors="replace"``.  A low
  filesystem surrogate is therefore silently substituted instead of raising
  as it does on an ordinary language locale's strict standard output.  An
  in-process passing test was not evidence about the installed command.  This
  finding is specific to fd capture: ``capsys`` uses a different text wrapper,
  so neither fixture's behavior should be generalized to all pytest capture.

The child encoder and parent decoder are separate boundaries
  ``PYTHONIOENCODING`` deterministically selects the child interpreter's
  standard-output error handler.  A parent using ``subprocess.run(text=True)``
  then decodes the captured bytes independently and can raise its own
  ``UnicodeDecodeError`` after the child succeeded.  The black-box helper pins
  the child policy and uses ``errors="surrogateescape"`` for capture, so the
  assertion observes the child's complete output rather than a parent-side
  decoding accident.

Version parity is not environment parity
  The Ubuntu host's ``fr_FR.UTF-8`` default selected strict standard output;
  Gentoo host ``gl63`` used ``C.utf8`` and PEP 540's ``surrogateescape``.  The
  same command therefore failed on one host and passed on the other despite
  running the same code.  Cross-host evidence must record locale and effective
  stream encoding/error policy as well as Python and dependency versions; the
  regression itself uses ``PYTHONIOENCODING`` instead of depending on either
  host default.

Assert the required result, not merely the absence of one failure signature
  ``"Traceback" not in stderr`` would also pass if a broad
  exception handler silently omitted the preview.  The strengthened regression
  requires the expected exit status, empty standard error, exact byte-named
  diff headers and body, and the authoritative final status line.  JSON
  coverage additionally requires valid UTF-8, successful parsing, and recovery
  of the original filename byte.

One crashing print call may expose an output-boundary defect
  Probing ``check``, ``outline``, ``list-table``, and JSON found independent
  failures; enumerating individual ``print`` sites would not protect the next
  one.  Moving the invariant to CLI startup fixed the shared boundary, while
  focused black-box tests retained evidence for the semantically distinct
  diff, human report, and JSON paths.

Output channels do not necessarily share one encoding contract
  Human reports and unified-diff headers need Unix filename bytes to
  round-trip, so a strict standard output becomes ``surrogateescape``.  JSON
  promises UTF-8 text, so the same low surrogate must instead become a
  reversible JSON escape.  Standard error already uses Python's defensive
  ``backslashreplace`` policy and did not need modification.

Presence is not positive evidence in a value-bearing mapping
  ``Counter[key] += 0`` still materializes ``key``.  An earlier
  ``--skip-fixable`` defect treated the resulting key set as proof that a
  fixable finding had been suppressed and could consequently hide an unrelated
  Sphinx error.  When values carry the event count, downstream logic must test
  the positive value rather than container truthiness or key presence.

A modeled coordinate is not yet an editable source range
  Docutils line metadata identifies where a semantic observation arose; it
  does not by itself prove the physical bytes safe to replace.  The
  ``list-table`` investigation became actionable only after source recovery
  required an enclosing grid/simple-table range and gave an unlocated model
  position its own refusal.  Before mutation, join parser evidence back to the
  current source geometry and fail closed when that physical predicate is not
  proven.

Trace reachability before using a hypothetical as proof
  A direct ``sys.stdout.buffer`` write would bypass text adapters and was
  rightly rejected, but one supporting example claimed ``diff --fast`` could
  encounter an ``OutputBudgetSink`` under ``--max-output-lines``.  The parser
  rejects that option for ``diff`` before its handler runs.  The architectural
  conclusion survived; the stated execution path did not.  Rejected
  invocations, startup adapters, and command handlers are different
  control-flow regions.

A last-resort exception catch is not automatically defense in depth
  A blanket ``UnicodeEncodeError`` catch can append a clean-looking diagnostic
  after partial patch or JSON output and conceal the implementation defect that
  produced it.  Clean diagnostics are required for anticipated external
  failures; complete-output assertions are the stronger protection for an
  internal output invariant.

The cross-review was productive because corrections were symmetric: one pass
widened the symptom beyond ``diff`` and exposed the capture-fixture blind spot;
another separated JSON from byte-preserving text output and rejected a
vacuous-pass assertion; follow-up tracing corrected an unreachable
``OutputBudgetSink`` example.  Earlier dogfooding supplied the zero-count and
modeled-position parallels.  Independent agreement mattered only after those
claims survived direct probes, source tracing, and executable tests.
