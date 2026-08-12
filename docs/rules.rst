.. Copyright (C) 2026 Maxime P. DEMENTYEV
.. SPDX-License-Identifier: GPL-3.0-only
.. Semantic WARNINGs left to human judgment — check_rst project

##########################
check_rst semantic rules
##########################

******************************************
What the tool deliberately leaves to you
******************************************

WARNINGs are the tool's refusal to guess at semantics:

* a standalone ``**bold**`` line or a bold paragraph opener may be a
  heading in disguise (a known AI writing habit carried over from
  Markdown) — or a legitimate label, reference ID, or field name;
* ``.. rubric::`` may deserve promotion to a real, ToC-visible section —
  or be an intentional recurring label;
* nested inline markup definitely loses one role in rendered RST, but the tool
  cannot decide whether the outer role, the inner role, or the literal marker
  text expresses the author's intent;
* a valid-but-non-preferred adornment character is a style note, common
  in content imported from other projects.

These require reasoning about *meaning*, which is your half of the
contract.  Review them in step 1 of the loop; never suppress them with
``--no-warnings`` in the validation loop (a pure structure query is a
different activity — ``outline`` exists precisely for it), and
never skip the pre-fix pass.  When promoting a
bold line to a section, strip the markers and use the placeholder
workflow — the judgment is yours, the adornment mechanics still are not.

A bold paragraph opener inside a *list item* used to be silently
exempt from this WARNING — reversed the same day (Max: "check_rst must
warn about those bold texts... it's up to the AI - accept or not").
The five lists the original single-page guide converted to real subsections
(2026-07-20 — the worked demonstration's commentary, the feedback loop's report
categories, how-to-treat-the-two-modes, the per-repo config
conditions, and this project's integration notes) were judged and
converted *before* the reversal, on ``outline``-visibility grounds
alone — ``check_rst`` never flagged any of them at the time.  The old
exemption could not tell a short ``* **term**: definition`` label
apart from a full ``* **Heading-ish sentence.**  More prose…`` opener
using tree shape alone — both are "bold first child, more children
follow" — so it silenced both, and in doing so silenced exactly the
signal that would have nudged toward restructuring sooner.  Now
neither shape is exempt: every list-item bold opener gets the same
WARNING a non-list one would, judged the same way.

The remaining WARNINGs this reversal surfaced — the numbered items in
:doc:`roadmap`'s "Agreed direction", and every entry in its
"Accepted, deferred" and "Declined, with reasons" sections — are a
deliberate exception to that
judgment, not an oversight: they are a chronological register, read
together as a log, not individually navigated the way the five
converted lists' points are.  Restructuring each into its own
subsection would be heading-inflation for entries meant to be skimmed
as a timeline, and would cost the register its own shape.  Reviewed,
and declined to restructure — step 1 of the loop reaching a considered
"leave it" is as valid an outcome as "promote it".

Stated as a general rule, not just this one reversal: **a stricter
WARNING rule never retroactively reaches into files you have not
re-checked.**  ``0 error(s), 0 warning(s)`` describes the last time
that file ran through the loop, under whatever ruleset existed then —
never "clean under the current rules," and never "reviewed since the
rules last changed."  Confirmed by real, external evidence the same
day this exemption reversed: an independent Claude Code session using
check_rst on a downstream project's documentation watched one file,
``coding-standards.rst``, jump from 74 to 95 WARNINGs from this
reversal alone — a silent backlog nobody had looked at yet, in a
repository not otherwise touched by the change.  After any rule
tightens, ``--recursive --skip-fixable`` across the repos you care
about is the manual audit that surfaces it; the tool will not do it
for you, on its own, after the fact.

*********************************************************
Judge structure for cold consumers, not the warm author
*********************************************************

A document can look adequately structured to the person or model that just
wrote it while failing the next consumer completely.  The author remembers
why a bold phrase matters; an in-context AI may already have read every line.
That remembered context compensates for weak markup, so their present
comprehension is not evidence that the document itself encodes the structure.

============================================
The role, instance, and context-state gate
============================================

The BDD analysis behind this rule separates three axes.  Do not collapse them:

.. list-table::
   :header-rows: 1
   :widths: 19 34 47

   * - Axis
     - Values
     - Why it changes the judgment
   * - Role
     - Creator, reader, reviewer/auditor, modifier, renderer/indexer
     - The same representation can be cheap to create but expensive to review
       or target safely in a later edit.
   * - Instance family
     - Human, AI, automation
     - A human scans visual geometry, an AI may request a structural briefing,
       and automation sees only grammar represented in its model.
   * - Context state
     - Warm or cold
     - The author and current-session AI can rely on memory; an unfamiliar
       human, fresh-context AI, or one-shot tool cannot.

An instance is therefore not just “an AI” or “a human.”  A current-session AI
and a fresh-context AI are materially different readers; so are the original
human author and the same person returning six months later.  The acceptance
gate is the cold consumer: a competent reader with no authoring-session memory,
not a supposedly less intelligent reader.

When the audience is unspecified, test at least these three consumers:

* an unfamiliar human reviewer scanning source or rendered navigation;
* a fresh-context AI beginning with ``outline --sections-only`` and
  ``context``;
* automation that can act only on the document grammar it parsed.

=======================
Cold-reader scenarios
=======================

Use these scenarios before choosing a bold opener, list item, or real section:

.. code-block:: gherkin

   Scenario: An independently meaningful concept survives a cold read
     Given a concept may be reviewed or modified independently
     And the next consumer may be an unfamiliar human or a fresh-context AI
     When that consumer starts with a visual scan, the section view, or context
     Then the concept is discoverable as a named section with its own range
     And no complete linear read or raw-markup grep is required

.. code-block:: gherkin

   Scenario: Co-equal entries remain a sequence
     Given several short entries derive their meaning from being read together
     When they form a checklist, legend, register, or classification
     Then retain them as a list
     And accept any bold-opener warning with that semantic reason

.. code-block:: gherkin

   Scenario: Emphasis carries no structural meaning
     Given bold text is neither an independently navigable concept
     Nor a meaningful label within a sequence
     Then rewrite it as ordinary prose
     Or integrate it into the surrounding sentence

These are judgment gates, not promises that more headings are always better.
One-clause sections can drown both a human contents view and an AI outline in
noise.  The shared objective is explicit semantic structure for cold
consumers, not maximum section count.  The source-compactness cost and the
project's deliberately strong RST geometry are documented in
:doc:`guide`.

=================================================
Structural retrieval before and after promotion
=================================================

Consider a standalone bold opener:

.. code-block:: rst

   **Author filter.** Keep only commits made by the configured author.

``outline --sections-only`` has no ``Author filter`` entry, and
``context 'Author filter'`` has no structural entry to resolve.  A
full-text reader may understand the sentence, but the document model cannot
return it as an independently named range.

Encode the same intent as a section:

.. code-block:: rst

   Author filter
   *********

   Keep only commits made by the configured author.

After the placeholder workflow materializes the adornment,
``outline --sections-only`` lists ``Author filter``, and
``context 'Author filter'`` returns its section kind, verified range,
parent path, siblings, children, findings, and — when Sphinx verification is
active — references.

A bold-led list item is a useful intermediate case: the complete outline and
``context`` can expose it as a list item, while
``outline --sections-only`` correctly omits it and it has no stable,
title-based section identity.  That visibility supplies evidence for the
semantic decision; it neither forces
promotion nor makes a pseudo-section harmless.

*******************************************************
Bold pseudo-headings create their own outline failure
*******************************************************

A WARNING is a request for semantic judgment, not background noise.  Its
exit status of 0 means that the tool refuses to guess, not that the warning
has been semantically cleared or that a run containing unreviewed warnings
is "clean".  A particularly self-reinforcing AI failure starts when that
distinction is lost:

#. The model writes navigable concepts as list items with bold paragraph
   openers instead of real sections — a familiar Markdown-shaped habit.
#. ``--sections-only`` then omits those concepts, correctly: the document
   did not encode them as sections.
#. The complete outline exposes every list item, but a document with many
   pseudo-headings produces so much output that the useful structure is
   difficult to isolate.
#. The model concludes that the structural query is unhelpful and falls
   back to raw ``grep`` over titles, list markers, or adornment characters.
#. That fallback hides the structural defect, so the same authoring habit
   survives the next edit and the cycle repeats.

The mismatch is diagnostic evidence about the SOURCE, not proof that the
outline failed.  Repeated warnings do not become harmless merely because
neighboring items use the same style; local consistency can mean a
systematic pseudo-heading convention.  Judge whether each bold opener
names an independently navigable concept.  If it does, promote it to a
real section using the placeholder workflow.  If it is genuinely one item
in a register, definition list, checklist, or other sequence whose meaning
depends on being read together, retain it deliberately — the roadmap's
chronological registers above are the concrete counterexample.

Give every warning in the changed scope an explicit disposition:

* ``promote`` — it names an independently navigable concept, so convert it
  to a real section with a placeholder adornment.
* ``retain`` — it is a meaningful label, identifier, field name, or one
  member of a sequence whose meaning depends on remaining a list; state that
  semantic reason even though the WARNING remains.
* ``rewrite`` — the emphasis has no structural job; remove it or fold the
  text into ordinary prose instead of preserving a warning that has no
  semantic justification.

"Matches the neighboring style" is not a sufficient retain reason by
itself: the neighboring style may be the systematic defect the warning is
revealing.  Only after each warning has one of these dispositions is it
accurate to call the semantic review complete.

.. important::

   Apply the cold-reader future-outline test BEFORE writing a standalone bold
   line or a list item that begins with bold text: “Would an unfamiliar human
   reviewer want this concept to stand out while scanning, and would a
   fresh-context AI want to request it as a named section through
   ``outline --sections-only`` and ``context``, with its own verified
   range?”
   If yes, create a real section with the placeholder workflow now.  If no
   because its meaning depends on membership in a sequence, retain that shape
   deliberately.  If the emphasis has no semantic job, rewrite it as prose.
   These alternatives prevent the test from turning every label into a
   heading.

``ListEntry`` makes list items visible, as described in `Finding one item
among many: the two-level list contract`_ below; visibility alone does not
make a full outline a good targeted query.  Use the implemented
``context <entry>`` briefing to resolve one section or leaf entry and
obtain its range, parent path, siblings, children, findings, and references
when Sphinx verification is active.
If exact text is ambiguous, choose one of the generated selectors rather than
guessing.  Do not infer structure by grepping ``^====``, ``^----``,
``^\*``, or similar markup.

******************************************************
Nested inline markup means one role is silently lost
******************************************************

Markdown permits combinations such as bold text containing an inline code
span.  RST does not nest inline markup in either direction.  For example::

    Use **``XGrabServer()``** to lock the server.

Docutils creates one outer ``strong`` node whose visible text still contains
the double-backtick characters.  It does not create a literal child.  The
inverse shape has the same failure::

    ``code **bold** code``

Here docutils creates one outer ``literal`` node and keeps the asterisks as
literal content.  A successful parse and a clean Sphinx build therefore do not
prove that both requested styles survived.

``check_rst`` detects this without copying docutils' delimiter grammar into a
regular expression.  For every outer strong, emphasis, or inline-literal node,
it feeds the node's leftover text through a fresh
``docutils.parsers.rst.states.Inliner``.  A successful explicit inline node in
that second parse proves that the source asked for nested markup.  The fresh
probe document is an isolation predicate: discovering a reference or target
cannot mutate the real doctree used by later checks.

Three results deliberately do not count:

* plain ``Text`` means docutils recognized no inner construct, as with the C++
  spelling ``int** ptr`` or the non-boundary text ``x**y``;
* ``problematic`` means an incomplete or invalid start string, not a complete
  inner role;
* an implicit URL or email ``reference`` contains no nested delimiter or
  explicit role.  A literal URL is ordinary code-like content, not proof of a
  link-inside-code request.

The WARNING names the outer kind, its bounded source preview, and the inner
kind.  Its shared explanation is printed once per run::

    (nested inline markup: reStructuredText renders only the outer inline role;
    choose which one should survive)
    note.rst:8: WARNING: nested inline markup in bold span
    '**``XGrabServer()``**' (contains inline literal)

This is not auto-fixable.  RST has no syntax that preserves both roles over the
same characters, so the author must choose a disposition:

* keep the inner role and remove the outer markers — the usual repair for a
  Markdown export whose bold merely surrounds code;
* keep the outer role and remove or escape the inner markers when they were
  unintended syntax;
* retain the outer literal span unchanged when its markers are deliberately
  shown as data, such as an RST example or a glob.  Record that semantic reason
  when reviewing the WARNING.

The specific warning supersedes the heading-substitute warning for the same
strong node.  A leading nested span used to be reported as a standalone bold
line or bold paragraph opener, advice that could send the author toward a
section promotion without repairing the lost role.  Mid-sentence spans were
silent.  Both positions now receive the same syntax diagnosis.  Blockquotes
remain in scope because quoted/imported markup still renders incorrectly;
literal blocks remain out of scope because their contents are captured source,
not parsed inline structure.

The first implemented whole-corpus scan (2026-08-02) found 403 warnings in 109
files: 355 outer bold spans, 36 outer inline literals, and 12 outer emphasis
spans.  The original roadmap evidence from 2026-07-26 was 175 occurrences in
49 files; preserving both numbers distinguishes corpus growth from a detector
change.

***************************************************
The one WARNING that isn't really a judgment call
***************************************************

``.. code: bash`` is valid RST.  A single colon after a word docutils
recognizes as a directive name doesn't produce a directive at all — it
produces a *comment*, and comments are silently dropped from every
rendered output.  The intended ``.. code:: bash`` (a genuine directive,
two colons) never got written; the content between the comment markers
— the code listing, the note, whatever it was — simply never appears
anywhere, and nothing in the ordinary write-render-review loop says so:
docutils doesn't complain (a comment is perfectly legal), the build
doesn't warn, the rendered page just has a gap where content should be.

This is a different kind of WARNING from bold-as-heading or
``.. rubric::``: those are genuine ambiguity — a bold line opening a
paragraph might be a heading in disguise, or a deliberate label, and
reasonable authors disagree.  A single missing colon is not ambiguous
in the same way; there is essentially no legitimate reason to *want*
this pattern.  It is WARNING severity because a comment is syntactically
valid RST, not because the call is close — review here is closer to a
formality than a judgment.

The check: a comment whose first line matches ``word:`` (single colon,
not ``word::``) where ``word`` is a directive name docutils itself
knows (its own English directive-name registry, plus a small curated
Sphinx supplement — ``toctree``, ``code-block``, ``seealso``, and
similar) is flagged.  ``todo`` is deliberately excluded from that
supplement: ``.. TODO: fix this`` is too common a genuine-comment idiom
on its own to flag without drowning the real signal in noise.

The real catch this shipped for: a calendar note (2025-11-13) contained
exactly ``.. code: bash`` — a C++ listing that had been silently
invisible in the rendered HTML for eight months before this lint's
first whole-corpus run found it, the one true positive, zero false
ones.

This WARNING is a net, not a guarantee (Max, 2026-07-22: "we cannot
cover all cases... they could be more complex cases") — it only fires
for a name in ``outline``'s own known-directive registry, matched on
the comment's first line.  A typo of a name outside that registry, or
one buried past the first line, produces no WARNING at all and stays
just as silently dropped as before.  That is why every comment, not
only the ones this heuristic recognizes, is its own entry kind in
``outline`` (see "Block previews" in :doc:`guide`):
``comment "code: bash"
[suspicious — looks like a mistyped directive]`` when the heuristic
matches, a plain ``comment "..."`` preview when it doesn't — general
visibility closes the blind spot the regex alone cannot, without
pretending the regex is exhaustive.

*********************************************************
A second top-level title is legal RST and a real defect
*********************************************************

A document may have only one level-1 title — it is the document's own
title, the thing search results and browser tabs show, the thing a
toctree entry links to as a single unit.  A second top-level section
is completely valid RST; docutils and Sphinx accept it without
complaint, at any verbosity — confirmed live, 2026-07-26: a real
``sphinx-build -vv -n`` (maximum verbosity, nitpicky mode) on a file
with two full ``#`` sections said nothing about it at all.

What actually happens instead: neither section gets promoted to the
document's own ``<title>`` — docutils only promotes a top-level
section to that role when it is the SOLE one.  The consequence is
visible one level up, not in the file itself: built a real HTML page
from such a file and inspected the *referring* document's toctree, and
the entry that should have linked to one section title instead listed
both sections as separate top-level entries in the navigation tree — a
real, silent structural defect, discovered only by looking at a
different page than the one with the problem.

This is a non-fixable ERROR.  Severity and repairability answer different
questions: the effective document structure is proven invalid, so the finding
affects exit status; deciding the page title remains an author judgment, so
``fix`` must not choose one.  ``--skip-fixable`` suppresses only findings
explicitly owned by deterministic mutation and therefore retains this ERROR.

The diagnostic gives a bounded repair *shape*, not a semantic answer: choose
the page title, insert it before the existing sections with a nine-character
underline using an adornment symbol unused anywhere in the effective document,
then run ``check_rst fix``.  The new symbol establishes a new outer level;
``fix`` materializes the canonical overline, underline width, and hierarchy.

The rule consumes the parsed section tree rather than guessing from the root
file's first adornment character.  Standard ``include`` content therefore
counts at its effective depth and a diagnostic points to the included physical
source.  Verified mode uses the Sphinx parse, including extension
``source-read``/``include-read`` changes, synthetic ``rst_prolog`` and
``rst_epilog`` content, and the ``only``/``ifconfig`` branches active for the
same HTML builder used by Phase 3.  Inexact transformed or synthetic sources
remain visible at line 0 instead of receiving a fabricated editable location.

A corpus-wide run against this Journal's full calendar (1415 files) found zero
instances when the original source-only WARNING shipped; that absence remains
recorded honestly rather than replaced with an invented catch.

*****************************************************************************
A relocated subtree's old character can silently land it at the wrong depth
*****************************************************************************

The roadmap's "Accepted, deferred" entry for
``_first_appearance_adornments`` already found and named half of this,
in a different trigger: docutils' own title-style inference is
asymmetric.  Reusing an already-established *shallower* character
deeper in the tree is silently tolerated — it pops cleanly to that
shallower, already-known level, no error, no WARNING.  Reusing an
already-established *deeper* character shallower is the opposite: real,
loud, "Inconsistent title style," caught by any ordinary Sphinx build
before ``check_rst`` even runs its own logic. That fix (2026-07-21)
taught the scanner to see short, previously-invisible titles that were
triggering the *silent* half by accident. It did not, because nothing
about it could, close off the silent half itself — the asymmetry is
docutils' own inference rule, not a check_rst scanning gap, and it has
a second, independent trigger the roadmap entry never considered:
moving content between documents on purpose.

Splitting an oversized page or relocating a section (:doc:`guide`,
"The same principle scales to whole subtrees") pastes a subtree's *old*
headings into a place that never assigned them a character at all. If
the pasted content's own former character happens to already mean a
*shallower* depth in the host — pure accident, since the two documents'
character histories have nothing to do with each other — the silent
half of the same asymmetry fires: the pasted section pops to that
shallower level instead of nesting where it visually sits, and
``check_hierarchy`` never sees anything wrong, because from a
structural point of view nothing *is* wrong — the resulting tree is
completely self-consistent, just not the tree the author placed on the
page.  No WARNING fires for the same reason the top-level-title WARNING
above needs one at all and this does not get one yet: that WARNING has
a recognizable signature to trigger on (this document's own
first-appearing character, reused with nothing between the two uses).
A relocated subtree colliding with a host's unrelated character has no
comparable signature — a legitimately-authored document that happens to
use the same characters in the same arrangement is indistinguishable
from this defect from inside the file alone.  Recorded honestly as a
known blind spot rather than a shipped WARNING, the same as the
top-level-title rule's own "no real catch yet" — except this one may
not be catchable at all without knowing the author's intent, which
lives nowhere in the file.

The only mitigation available today lives in the workflow, not the
tool: neutralize a subtree's headings back to bare placeholders before
splicing it into a host that already has its own established
characters (:doc:`guide`, "Insert a subtree into an *existing*,
already-populated document") — placeholders cannot collide with
anything, because they have not yet been assigned a character to
collide with.  Diffing ``outline`` before and after any subtree
splice is the only way to notice a silent misplacement after the fact;
nothing in a clean ``check_rst`` run distinguishes it from a correctly
nested document.

***************************************************
A confusable letter is a keyboard slip, not noise
***************************************************

This Journal is deliberately trilingual — Russian, French, and English
coexist constantly, so Cyrillic and Latin sit on nearly every line.
"Does this line mix scripts" would fire almost everywhere and mean
nothing.  The real signal lives one level down: does a single
**word** — no space or punctuation inside it — mix scripts where one
of them is visually a perfect twin of the other, the shape a keyboard-
layout slip actually produces (Max, 2026-07-24: "when letters look
similar, but only one letter is from another alphabet").

The precise rule, arrived at by scanning this Journal's own corpus for
every mixed-script word that exists (14 total, across years of daily
notes) rather than guessing: split a word's letters into majority
script and minority script; flag it only if *every* minority-script
letter is a known visual twin of a majority-script one (``а``/``a``,
``е``/``e``, ``о``/``o``, ``р``/``p``, ``с``/``c``, ``у``/``y``,
``х``/``x``, and their capitals — the confusables table is hand-
curated, since no library on this system provides one; see
``_CYRILLIC_LATIN_CONFUSABLES`` for why).  A tied split is skipped as
genuinely ambiguous, never guessed at.

That one condition is what separates real typos from legitimate
constructions, confirmed against the real 14 — no hand-tuned exception
list needed.  Verbatim, so the illustration itself is not mistaken for
fresh prose (a literal block is exactly what this check skips —
captured output, not authored text, the same reasoning below)::

    flagged (every minority letter is a confusables-table entry):
      Аuthor        -- Cyrillic capital А, Latin "uthor"
      Сalibration   -- Cyrillic capital С, Latin "alibration" (recurring
                        habitual typo, twice, different dates -- the same
                        shape as the frequency-asymmetry catch above)
      вcе           -- Latin c substituted for Cyrillic с, amid Cyrillic в/е
      коробочкаp    -- a trailing Latin p, confusable with Cyrillic р

    NOT flagged, by construction, no carve-out needed:
      VPNом         -- Cyrillic case ending on a Latin acronym, no
                        separator (normal informal Russian) -- the м
                        has no Latin twin
      кодbase       -- Russian word glued to English, missing its space
                        -- neither к nor д has a Latin twin
      сWebSocket    -- Russian preposition glued on, missing its space --
                        its ONE minority letter IS a table entry, so this
                        one DOES get flagged: a soft, acceptable false
                        positive (one-glance dismissal, not a wrong-fix
                        risk, since nothing here is auto-fixed)
      jьmati        -- genuine Proto-Slavic etymological notation -- the
                        soft sign ь has no Latin twin at all

Scans the same author-facing prose Text nodes as top/rare prose words
(code, comments, raw passthrough, generated topics excluded) —
content inside a literal block is captured tool output or an example,
never something to flag as a fresh typo; confirmed live on a real
corpus hit: a captured Sphinx warning log quoting a past lexer-name
typo (Cyrillic ``с`` where ``.cpp`` needed a Latin ``c``) stays silent,
correctly, because it is a historical record, not fresh prose.  Unlike
the bold/rubric checks, block quotes are NOT exempt — a garbled word
inside quoted material is still garbled regardless of who typed it
first.  WARNING, not ERROR: mixed script is evidence of a likely typo, not
proof that the structure is invalid.  Choosing which script was intended is
also non-fixable, but repairability does not determine severity — the proven
single-top-level defect above is the counterexample.

The real catch: a corpus-wide run found 6 real occurrences against 14
candidate mixed-script words total, zero of the 8 legitimate
constructions misflagged.

*********************************************************
A missing reference is the mirror image of a broken one
*********************************************************

"Did you mean" (documented in :doc:`guide`) fixes a cross-reference that exists but points
nowhere.  ``check_bare_filenames`` catches the opposite case: prose
mentions a real project document by its bare filename — plain text or
wrapped in double backticks as the author's own emphasis — and never
turns it into an actual ``:doc:``/``:ref:`` at all (Max, 2026-07-23,
evidence from a downstream project: ``docs/product-gui/client-interface.rst`` says
"documented in ``coding-standards.rst`` under *VanJS Reactive Model*"
as plain text, and ``testing.rst`` says "the guarantee stated in
coding-standards.rst..." with no markup at all — neither is a live
link).

Matched by basename, not full path — confirmed by direct probe against
that downstream project: the docname Sphinx actually resolves is
``product-gui/coding-standards``, but neither real prose mention
spells out that path, only the filename.  Needs the live Sphinx
environment (``env.found_docs``), same as ``refs`` and "did you
mean" — verified mode only.

Silence has to be as deliberate as the WARNING itself, or the feature
is just noise:

* **No known doc shares the basename** — nothing confident to
  suggest, stay silent rather than guess.
* **The only match is the mentioning document's own docname** —
  mentioning your own filename is not a missing cross-reference.
* **More than 5 documents share the basename** — confirmed by real
  evidence: this Journal's own corpus has 1072 files named
  ``Notes.rst``.  A bare "Notes.rst" mention (this project talks about
  its own file-naming convention constantly) is not a specific,
  actionable target; dumping all 1072 candidates would be exactly the
  kind of noise this whole project exists to avoid.  The threshold is
  not tuned per corpus — 5 is a deliberately generous cutoff, not a
  guess calibrated to this one number.

Scans the same author-facing prose Text nodes as ``check_homoglyphs``
— deliberately including inline literal spans (unlike a
``literal_block``): the real evidence is a filename wrapped in double
backticks precisely because that is how the author chose to typeset
it, not captured code output.  WARNING, not ERROR: converting to a
real cross-reference is a content decision (which role, which target
syntax) no deterministic pass can make.

The real catch: both downstream-project mentions above are flagged live,
unchanged, by the shipped checker.  A corpus-wide run against this
Journal's own aggregation pages (``projects/``, ``techs/``,
``organs/``) found one more, verbatim (a literal block, so this very
illustration is not itself mistaken for a fresh mention — the same
reasoning as the homoglyph section above)::

    projects/journal/std.rst:125: WARNING: header.rst mentioned as
    plain text — did you mean a :doc:/:ref: cross-reference? possible
    target(s): '.journal/header'

Genuinely ambiguous in a different way than the threshold catches: the
matching document uses ``:orphan:`` specifically because it is a
template snippet copied into other files, not a page anyone navigates
to — left as evidence that WARNING severity is doing its job, the tool
reports the mechanical fact, the AI decides whether a link actually
belongs there.

===========================================================
Local assets need Sphinx integration, not only a filename
===========================================================

A non-RST file can have the same missing-integration defect without being a
Sphinx document.  The real 2026-08-12 evidence was a roadmap calling a local
Markdown task brief "required reading" while spelling its path inside an
inline literal.  The rendered page offered no way to retrieve it.

An ordinary RST hyperlink does not solve that case reliably.  Sphinx emits the
relative URL but does not copy an arbitrary source asset into the HTML output;
the resulting deployed link can therefore return 404.  Choose the mechanism
that states what the file means to the reader:

* ``:download:`` copies an artifact and links to the generated copy.
* ``include`` or ``literalinclude`` incorporates text or source content.
* ``image`` or ``figure`` renders a supported image.
* ``:file:`` deliberately marks a filename when reader access is unnecessary;
  it is semantic text, not a download.

This rule diagnoses inert prose, including an inline literal; it does not yet
audit an existing ordinary hyperlink's deployment.  Proving that such a target
is copied through ``html_extra_path``, a static path, or an extension is a
separate builder-delivery check rather than a reason to guess here.

The checker cannot choose among those meanings, so this remains a non-fixable
WARNING.  Its confidence boundary is intentionally narrower than the document
rule: the exact mentioned path must resolve, relative to its physical RST owner,
the Sphinx source root, or the configured project root, to a regular file still
inside the Sphinx source tree.  A project-wide basename match would turn common
source and build-file discussion into noise.  A configured Sphinx source suffix
is also excluded because that path names a document, not an asset.

The supported text/document protocol is ``.cfg``, ``.conf``, ``.csv``,
``.diff``, ``.ini``, ``.json``, ``.jsonl``, ``.log``, ``.markdown``, ``.md``,
``.patch``, ``.toml``, ``.tsv``, ``.txt``, ``.xml``, ``.yaml``, and ``.yml``.
The image protocol is ``.gif``, ``.jpeg``, ``.jpg``, ``.png``, ``.svg``, and
``.webp``.  These sets are explicit compatibility policy, not an attempt to
recognize every filename-shaped token.  Unknown, missing, unsupported,
outside-source, and merely same-basename files stay silent.  Files that happen
to exist beside documentation but are never mentioned are a separate orphan-
asset question and are outside this rule.

**********************************************************
Finding one item among many: the two-level list contract
**********************************************************

The friction that motivated this (Max, 2026-07-22): hunting for one
specific item inside what were then :doc:`roadmap`'s numbered
"Agreed direction" and bulleted "Accepted, deferred" lists, ``outline``
answered nothing — it reported the enclosing section's line range and stopped,
telling you a ~400-line list existed somewhere inside without saying
what was in it, so the fallback was a raw ``grep`` against the file's
own markup for ``^\* ``/``^\d+\.`` — exactly the fragile
"scanning raw markup" pattern ``outline`` exists to replace for
every other block kind.  The roadmap has since promoted those items to
sections; this remains the historical motivation and the contract for lists
that are semantically appropriate.

A bullet or enumerated list gets TWO levels, not one, deliberately
different from every other block-preview kind above: a CONTAINER entry
for the whole list (``bullet list ('*', 22 items)``, at the enclosing
section's own child depth) and one entry per ITEM, nested one level
deeper, each with its own line range and its own collapsed/truncated
preview.  This is not a bigger version of a table row (a table's rows
are chained into one preview, never their own entries) — the point of
this feature specifically was to let ``--outline-depth`` hide a long
list's individual items while keeping the list's own existence and
item count visible, the same "depth trims display, never information"
contract sections already use for subsections.  A definition list is
flatter by design (Max: "one entry per item") — every
``definition_list_item`` stands alone with no container entry at all,
marker is the item's own term text, because every item has a
genuinely distinct term (unlike a bullet list's one shared bullet
character) — the same title+body shape as ``AdmonitionEntry``
(term=title, definition=body).

Depth for a nested sub-list is not simply "one more than its outer
container" — a real bug caught before shipping, 2026-07-26: a bullet
item containing its own nested bullet list produced a sub-list at the
SAME depth as the outer container, because the depth walk skipped the
intervening item node entirely.  The fix counts ``list_item`` as an
ancestor too, so a sub-list nested inside an item lands one level
deeper than that item, not merely level with the list it is actually
inside — confirmed by direct probe on exactly this shape before and
after the fix.  Enumerated markers (``1.``, ``#.``, ``a)``, roman
numerals) are never stored in the doctree at all — docutils renders
enumerated-list numbering at write time only — so every marker shown
is computed here from ``enumtype``/``prefix``/``suffix``/``start``,
confirmed against a real corpus scan that only arabic digits and
``#.`` auto-numbering are ever actually used in this project; alpha
and roman support exists for completeness, not local demand.

The two-level representation also makes ``context`` the escape hatch from
the feedback loop that motivated list entries in the first place.  Use an
exact item preview when it is unique; when repeated text is ambiguous, use
the candidate's generated ``docname:enumerated-item@line`` or
``docname:bullet-item@line`` selector.  The resulting briefing returns the
item's enclosing sections and list container plus its adjacent siblings, so
neither ``--sections-only`` blindness nor a long complete outline justifies
falling back to raw-markup grep.  The compact shared slug, occurrence-suffix,
and section-alias contract is defined under "Entry selectors" in
:doc:`guide` rather than repeated per entry kind here.
