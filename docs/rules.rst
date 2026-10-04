.. Copyright (C) 2026 Maxime P. DEMENTYEV
.. SPDX-License-Identifier: GPL-3.0-only
.. Semantic rules and the findings left to author judgment — check_rst project

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
* a comment whose first line looks like a directive with one colon may be
  silently hiding content — or be an ordinary comment;
* a word mixing look-alike Cyrillic and Latin letters is probably a keyboard
  slip — or a deliberate mixed-script name;
* a document filename or local asset path mentioned as plain text may deserve
  a real cross-reference or Sphinx integration — or be a deliberate literal
  mention;
* a valid-but-non-preferred adornment character is a style note, common
  in content imported from other projects.

One finding is an ERROR that still needs you: a second effective top-level
title is invalid structure, but choosing the page title is an author decision,
so ``fix`` cannot repair it and ``--skip-fixable`` keeps it visible.

These require reasoning about *meaning*, which is your half of the
contract.  Review them in step 1 of the loop; never suppress them with
``--no-warnings`` in the validation loop (a pure structure query is a
different activity — ``outline`` exists precisely for it), and
never skip the pre-fix pass.  When promoting a
bold line to a section, strip the markers and use the placeholder
workflow — the judgment is yours, the adornment mechanics still are not.

A stricter rule never retroactively reaches into files you have not
re-checked.  ``0 error(s), 0 warning(s)`` describes the last time a file ran
through the loop, under the ruleset of that time — never "clean under the
current rules".  After any rule tightens, ``check --recursive --skip-fixable``
across the repositories you care about is the audit that surfaces the new
backlog; the tool does not run it on its own.  The reversal that established
this is recorded under "Pseudo-headings" in :doc:`development`.

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

A standalone bold line, a bold paragraph opener, and a ``.. rubric::`` are
reported as WARNINGs (``pseudo-heading.standalone-bold``,
``pseudo-heading.bold-opener``, ``pseudo-heading.rubric``): each may be a
heading in disguise or a deliberate label, and only the author can tell.  They
never change the exit status and are not auto-fixed.  A WARNING is a request for semantic judgment, not background noise.  Its
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

===================================
Pseudo-headings: what is detected
===================================

* a paragraph whose only content is one bold span (standalone bold line);
* a paragraph that begins with a bold span followed by more text (bold
  paragraph opener) — inside a list item exactly as outside one, because tree
  shape cannot tell a short ``term:`` label from a heading-like opener;
* every ``.. rubric::`` directive, which is excluded from the table of contents
  and cannot be referenced.

``--verbose`` adds the bold or rubric text, a preview of the following prose,
and the enclosing section.

====================================================
Pseudo-headings: what is deliberately not detected
====================================================

* bold inside a title, term, or other non-paragraph element, and bold in the
  middle of a sentence;
* a bold span with nested markup, which the more specific nested-inline
  WARNING owns, because promoting it could not restore the lost role;
* block quotes and literal blocks: quoted material and captured output are not
  the author's own structure.  A merely mis-indented paragraph becomes a block
  quote too, and that exemption is a known, accepted limitation.

===============================
Pseudo-headings: dispositions
===============================

The mismatch between a full outline and ``--sections-only`` is diagnostic
evidence about the source, not proof that the outline failed.  Repeated
warnings do not become harmless merely because neighboring items use the same
style; local consistency can mean a systematic pseudo-heading convention.  Give
every warning in the changed scope an explicit disposition:

* ``promote`` — it names an independently navigable concept, so convert it
  to a real section with a placeholder adornment.
* ``retain`` — it is a meaningful label, identifier, field name, or one
  member of a register, checklist, or other sequence whose
  meaning depends on being read together; record that semantic reason in the
  project's ``.check_rst-retained.toml`` (see "Retained WARNINGs" in
  :doc:`guide`), so the reviewed WARNING no longer looks unreviewed.
* ``rewrite`` — the emphasis has no structural job; remove it or fold the
  text into ordinary prose instead of preserving a warning that has no
  semantic justification.
* ``restructure`` — it signals a real grouping problem that cannot be solved
  by promoting this one line; reorganize the surrounding sections or list so
  the intended hierarchy is explicit.

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

=======================================
Pseudo-headings: evidence and history
=======================================

The list-item exemption that once silenced these warnings, its reversal, and
the backlog it exposed downstream are recorded under "Pseudo-headings" in
:doc:`development`.

******************************************************
Nested inline markup means one role is silently lost
******************************************************

A bold or emphasis span whose text still contains another inline construct is
reported as a WARNING (``inline.nested-markup``).  Markdown permits bold text
around an inline code span; RST does not nest inline markup in either
direction, so it renders only the outer role and keeps the inner delimiters as
text::

    Use **``XGrabServer()``** to lock the server.

Docutils creates one outer ``strong`` node whose visible text still contains
the double backticks, and a clean Sphinx build does not reveal it.  The
finding names the outer kind, a bounded source preview, and the inner kind; it
never changes the exit status, and it is not auto-fixable, because RST has no
syntax that preserves both roles over the same characters.  It supersedes the
pseudo-heading warning for the same bold span, since promoting that span to a
section could not restore the lost role.

=================================
Nested markup: what is detected
=================================

``check_rst`` does not copy docutils' delimiter grammar into a regular
expression.  For every outer strong or emphasis node it feeds the leftover
text through a fresh ``docutils.parsers.rst.states.Inliner``.  A successful
explicit inline node in that second parse — an inline literal, emphasis,
strong, interpreted text, or explicit role — shows that the text *can* be
parsed as markup outside its outer role; it does not prove which role the
author intended, which is why the finding is a WARNING to judge.  Leading and
mid-sentence positions receive the same diagnosis, and block quotes stay in
scope because quoted or imported markup renders incorrectly too.  The fresh
probe document is an isolation predicate: discovering a reference or target
cannot mutate the real doctree used by later checks.

==================================================
Nested markup: what is deliberately not detected
==================================================

* An outer inline literal.  In ````code **bold** code```` docutils keeps the
  asterisks as literal content, but the literal is itself an explicit request
  to render its content as data (decided 2026-09-26).
* Plain ``Text`` from the second parse: docutils recognized no inner
  construct, as with the C++ spelling ``int** ptr`` or ``x**y``.
* A ``problematic`` result: an incomplete or invalid start string, not a
  complete inner role.
* An implicit URL or email ``reference``, which contains no nested delimiter
  or explicit role.
* Literal blocks, whose contents are captured source, not parsed inline
  structure.

=============================
Nested markup: dispositions
=============================

* keep the inner role and remove the outer markers — the usual repair for a
  Markdown export whose bold merely surrounds code;
* keep the outer role and remove or escape the inner markers when they were
  unintended syntax;
* ``retain`` the span unchanged when its markers are deliberately shown, such
  as an example of this very pattern, with the reason in
  ``.check_rst-retained.toml``.

=====================================
Nested markup: evidence and history
=====================================

The corpus scans behind the rule and the classification behind the literal
policy are recorded under "Nested inline markup" in :doc:`development`.

***************************************************
The one WARNING that isn't really a judgment call
***************************************************

A comment whose first line reads like a known directive written with one colon
— ``.. code: bash`` instead of ``.. code:: bash`` — is reported as a WARNING
(``directive.mistyped``).  One colon makes valid RST: a comment, dropped from
every rendered output, so the intended listing or note never appears and
neither docutils nor Sphinx says so.  Unlike a bold pseudo-heading this is not
genuine ambiguity; it is a WARNING only because the comment is syntactically
valid, and review is closer to a formality than a judgment.  It never changes
the exit status and is not auto-fixed.  The line is the comment's recovered
physical marker, inside table cells too.

=======================================
Mistyped directives: what is detected
=======================================

A comment is flagged when its first line matches ``word:`` — one colon, not
``word::`` — and ``word`` is a directive name docutils itself knows (its
English directive-name registry) or one of a small curated Sphinx supplement
such as ``toctree``, ``code-block``, and ``seealso``.

========================================================
Mistyped directives: what is deliberately not detected
========================================================

* ``todo``, excluded from the supplement: ``.. TODO: fix this`` is too common
  a genuine-comment idiom to flag without drowning the real signal.
* A name outside that registry, or a typo past the comment's first line.  The
  WARNING is a net, not a guarantee.  That is why every comment is its own
  ``outline`` entry (see "Block previews" in :doc:`guide`): ``comment "code:
  bash …" [suspicious — looks like a mistyped directive]`` when the heuristic
  matches, a plain ``comment "..."`` preview otherwise, and the preview carries
  the hidden body either way, so general visibility closes the blind spot the
  heuristic alone cannot.

===================================
Mistyped directives: dispositions
===================================

Add the missing colon when a directive was intended (``rewrite``).  An
ordinary comment whose text merely begins with a directive name can be
``retain``\ ed with its reason in ``.check_rst-retained.toml``.

===========================================
Mistyped directives: evidence and history
===========================================

The lint shipped for one real catch, a listing invisible for eight months; see
"Mistyped directives" under "Rule evidence and history" in :doc:`development`.

*********************************************************
A second top-level title is legal RST and a real defect
*********************************************************

A second effective top-level section is reported as a non-fixable ERROR
(``hierarchy.second-title``).  A document may have only one level-1 title — the
page's own title, the thing search results, browser tabs, and a toctree entry
treat as one unit.  A second top-level section is valid RST that docutils and
Sphinx accept silently, but neither section is then promoted to the document's
title, so a referring toctree lists both as separate top-level entries: a real
structural defect visible only on another page.  Severity and repairability
answer different questions.  The effective structure is proven invalid, so the
finding affects the exit status; choosing the page title is an author judgment,
so ``fix`` never chooses one and ``--skip-fixable`` keeps the ERROR visible.

=================================
Second titles: what is detected
=================================

The rule reads the parsed, composed section tree.  Standard ``include``
content counts at its effective depth, and the diagnostic points at the
included physical source.  Verified mode uses the Sphinx parse, including
extension ``source-read``/``include-read`` changes, synthetic ``rst_prolog``
and ``rst_epilog`` content, and the ``only``/``ifconfig`` branches active for
the HTML builder Phase 3 uses.  Inexact transformed or synthetic sources stay
visible at line 0 rather than receiving a fabricated editable location.

==================================================
Second titles: what is deliberately not detected
==================================================

The rule does not guess from the root file's first adornment character: a
character is style, not structure.  Branches that are inactive for the HTML
builder do not count.

=======================
Second titles: repair
=======================

The diagnostic gives a bounded repair *shape*, not a semantic answer.  Run
``check_rst outline --sections-only FILE`` and inspect the entry sources as
well as the ``levels:`` legend.  When the competing titles belong to one
self-contained physical source, choose the page title and preview
``check_rst entitle NAME FILE``; apply it only after reviewing the complete
diff.  ``entitle`` inserts a genuinely unused style before that file's body and
lets ``fix``'s machinery materialize the canonical geometry and hierarchy.
That local repair is intentionally not universal: a top-level ``include`` makes
``entitle`` fail closed without following it, emitting a diff, or writing
bytes.  If the effective titles come from included sources or Sphinx
transformations, restructure the host, the fragments, or the transformation at
the composition level and rerun ``outline``; the legend's free character then
proves only that the style is unassigned, not which physical source should own
the new parent.

=====================================
Second titles: evidence and history
=====================================

See "Second top-level titles" under "Rule evidence and history" in
:doc:`development` for the silent-build confirmation and the corpus result.

*****************************************************************************
A relocated subtree's old character can silently land it at the wrong depth
*****************************************************************************

Docutils' title-style inference is asymmetric.  Reusing an
already-established *shallower* character deeper in the tree is silently
tolerated — the title pops to that shallower, already-known level with no
error and no WARNING.  Reusing an already-established *deeper* character
shallower is loud: "Inconsistent title style", caught by any ordinary Sphinx
build.  The silent half is docutils' own inference rule, not a check_rst
scanning gap, and moving content between documents on purpose triggers it.

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
page.  Unlike the second-title rule above, no finding can fire here.  That
rule reads a proven fact from the parsed, composed section tree — two effective
top-level sections.  A relocated subtree colliding with a host's unrelated
character leaves no such fact: a legitimately-authored document that happens
to use the same characters in the same arrangement is indistinguishable from
this defect from inside the file alone.  It is recorded honestly as a known
blind spot rather than a shipped finding, and it may not be catchable at all
without knowing the author's intent, which lives nowhere in the file.

The only mitigation available today lives in the workflow, not the
tool: neutralize a subtree's headings back to bare placeholders before
splicing it into a host that already has its own established
characters (:doc:`guide`, "Insert a subtree into an *existing*,
already-populated document") — placeholders cannot collide with
anything, because they have not yet been assigned a character to
collide with.  Diffing ``outline`` before and after any subtree
splice is the only way to notice a silent misplacement after the fact;
nothing in a clean ``check_rst`` run distinguishes it from a correctly
nested document.  The scanner fix that first exposed the asymmetry is recorded
under "Relocated subtrees" in :doc:`development`.

***************************************************
A confusable letter is a keyboard slip, not noise
***************************************************

A single word that mixes Cyrillic and Latin letters, where every letter of the
minority script is a visual twin of a majority-script letter, is reported as a
WARNING (``text.homoglyph``): evidence of a probable keyboard-layout slip, not
proof of invalid structure.  It never changes the exit status and is not
auto-fixable, because choosing the intended script is the author's decision —
repairability does not determine severity, as the proven single-title ERROR
above shows.  The line points at the word itself, or carries
``(approximate line)`` when it cannot be proven.

====================================
Confusable words: what is detected
====================================

A word is a run with no space or punctuation inside it.  Its letters are split
into a majority and a minority script, and it is flagged only when *every*
minority-script letter is a known visual twin of a majority-script one:
lowercase ``а``/``a``, ``е``/``e``, ``о``/``o``, ``р``/``p``, ``с``/``c``,
``у``/``y``, ``х``/``x``, plus a separately curated set of capitals, judged per
case rather than inherited from the lowercase pairs.
``_CYRILLIC_LATIN_CONFUSABLES`` is the authoritative, hand-curated table.  The
check scans author-facing prose — the same Text nodes as the prose-word
statistics, inline literals included — and does scan block quotes: a garbled
word inside quoted material is still garbled.  Verbatim examples (a literal
block, so the illustration is not itself flagged)::

    flagged (every minority letter is a confusables-table entry):
      Аuthor        -- Cyrillic capital А, Latin "uthor"
      Сalibration   -- Cyrillic capital С, Latin "alibration"
      вcе           -- Latin c substituted for Cyrillic с, amid Cyrillic в/е
      коробочкаp    -- a trailing Latin p, confusable with Cyrillic р
      сWebSocket    -- a Russian preposition glued on: flagged, and an
                        accepted false positive (one glance to dismiss)

=====================================================
Confusable words: what is deliberately not detected
=====================================================

* Script mixing across a line: in multilingual prose Cyrillic and Latin share
  nearly every line, so a line-level signal would mean nothing.
* A word whose minority script has any letter without a visual twin — ``VPNом``
  (a Russian case ending on a Latin acronym), ``кодbase`` (a missing space),
  ``jьmati`` (etymological notation).
* A tied majority/minority split, which is genuinely ambiguous and never
  guessed.
* Code, comments, raw passthrough, generated topics, and literal blocks, whose
  content is captured output or an example rather than fresh prose.

================================
Confusable words: dispositions
================================

Replace the slipped letter when the word is a typo (``rewrite``).  When the
mixed-script word is deliberate, ``retain`` it with its reason in
``.check_rst-retained.toml``.  Nothing is auto-fixed: which script was
intended is knowledge only the author has.

========================================
Confusable words: evidence and history
========================================

The rule was derived from, and validated against, every mixed-script word in
the Journal corpus; see "Confusable letters" under "Rule evidence and history"
in :doc:`development`.

*********************************************************
A missing reference is the mirror image of a broken one
*********************************************************

Prose that mentions a real project document by its bare filename — as plain
text or inside an inline literal — without turning it into an actual
``:doc:``/``:ref:`` link is reported as a WARNING (``reference.bare-filename``)
that names up to five candidate targets.  It is the mirror image of a broken
reference, which "did you mean" (see :doc:`guide`) helps repair.  It needs the
live Sphinx environment, so it runs in verified mode only; it never changes the
exit status and is not auto-fixed, because choosing the role and target syntax
is a content decision.

=====================================
Filename mentions: what is detected
=====================================

A mention matches a known document by basename, not full path: prose usually
spells ``coding-standards.rst`` even when Sphinx resolves
``product-gui/coding-standards``.  The check scans the same author-facing
prose Text nodes as the homoglyph rule, inline literals included, because a
filename in double backticks is how authors typeset one; the line points at
the mention itself.

======================================================
Filename mentions: what is deliberately not detected
======================================================

Silence has to be as deliberate as the WARNING itself:

* **No known doc shares the basename** — nothing confident to
  suggest, stay silent rather than guess.
* **The only match is the mentioning document's own docname** —
  mentioning your own filename is not a missing cross-reference.
* **More than 5 documents share the basename** — confirmed by real
  evidence: a name shared that widely is a naming convention, not a specific,
  actionable target.  The cutoff is deliberately generous and not tuned per
  corpus.

Mentions inside real references or roles, and literal blocks, are not checked.

=================================
Filename mentions: dispositions
=================================

Convert the mention into a ``:doc:`` or ``:ref:`` link (``rewrite``).  When the
filename is discussed as a file rather than offered as a destination — or the
match is a template snippet deliberately marked ``:orphan:`` — ``retain`` it
with that reason in ``.check_rst-retained.toml``.

=========================================
Filename mentions: evidence and history
=========================================

The downstream mentions that motivated the rule and its corpus results are
recorded under "Filename mentions" in :doc:`development`.

***********************************************************
Local assets need Sphinx integration, not only a filename
***********************************************************

A plain-text mention of a real local non-RST file is reported as a WARNING
(``reference.plain-local-asset``): the rendered page offers the reader no way
to retrieve the file.  An ordinary RST hyperlink does not reliably solve that:
Sphinx emits the relative URL but does not copy an arbitrary source asset into
the HTML output, so the deployed link can return 404.  Verified mode only; it
never changes the exit status and is not auto-fixed, because the checker cannot
choose what the file means to the reader.

================================
Local assets: what is detected
================================

The exact mentioned path must resolve — relative to its physical RST owner,
the Sphinx source root, or the configured project root — to a regular file
still inside the Sphinx source tree, with a supported suffix.  The
text/document protocol is ``.cfg``, ``.conf``, ``.csv``, ``.diff``, ``.ini``,
``.json``, ``.jsonl``, ``.log``, ``.markdown``, ``.md``, ``.patch``, ``.toml``,
``.tsv``, ``.txt``, ``.xml``, ``.yaml``, and ``.yml``; the image protocol is
``.gif``, ``.jpeg``, ``.jpg``, ``.png``, ``.svg``, and ``.webp``.  These sets
are explicit compatibility policy, not an attempt to recognize every
filename-shaped token.  Inert prose, inline literals included, is diagnosed.

=================================================
Local assets: what is deliberately not detected
=================================================

* An existing ordinary hyperlink's deployment.  Proving that its target is
  copied through ``html_extra_path``, a static path, or an extension is a
  separate builder-delivery check, not a reason to guess here.
* Project-wide basename matches, which would turn common source and build-file
  discussion into noise, and a configured Sphinx source suffix, which names a
  document, not an asset.
* Unknown, missing, unsupported, outside-source, and merely same-basename
  files, and assets already integrated by a download, include, or image.
* A name marked with ``:file:``, and files that exist beside the documentation
  but are never mentioned — a separate orphan-asset question.

============================
Local assets: dispositions
============================

Choose the mechanism that states what the file means to the reader
(``rewrite``):

* ``:download:`` copies an artifact and links to the generated copy.
* ``include`` or ``literalinclude`` incorporates text or source content.
* ``image`` or ``figure`` renders a supported image.
* ``:file:`` deliberately marks a filename when reader access is unnecessary;
  it is semantic text, not a download.

``retain`` a mention whose inertness is deliberate, with the reason in
``.check_rst-retained.toml``.

====================================
Local assets: evidence and history
====================================

See "Local assets" under "Rule evidence and history" in :doc:`development`.

**********************************************************
Finding one item among many: the two-level list contract
**********************************************************

A list that is semantically a list stays one, and ``outline`` must still let
a reader find one item in it without scanning raw markup.
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

A sub-list nested inside an item lands one level deeper than that item, not
merely level with its outer container: ``list_item`` counts as an ancestor.
Enumerated markers (``1.``, ``#.``, ``a)``, roman numerals) are never stored in
the doctree — docutils renders enumerated-list numbering at write time — so
every marker shown is computed from ``enumtype``/``prefix``/``suffix``/
``start``; alpha and roman forms are supported for completeness.

The two-level representation also makes ``context`` the escape hatch when a
full outline is too long.  Use an
exact item preview when it is unique; when repeated text is ambiguous, use
the candidate's generated ``docname:enumerated-item@line`` or
``docname:bullet-item@line`` selector.  The resulting briefing returns the
item's enclosing sections and list container plus its adjacent siblings, so
neither ``--sections-only`` blindness nor a long complete outline justifies
falling back to raw-markup grep.  The compact shared slug, occurrence-suffix,
and section-alias contract is defined under "Entry selectors" in
:doc:`guide` rather than repeated per entry kind here.  The friction that
motivated list entries is recorded under "List entries" in :doc:`development`.
