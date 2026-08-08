.. Copyright (C) 2026 Maxime P. DEMENTYEV
.. SPDX-License-Identifier: GPL-3.0-only
.. Worked check/fix/analyse demonstration — check_rst project

#############################################################
Worked demonstration: one file, both halves of the contract
#############################################################

Everything below is real, captured output — one invented 38-line file
exercising the writing workflow and the reading oracle, extended
2026-07-20 with a ``list-table`` to also demonstrate that same day's
``outline`` enrichment.  The draft is written the way this page
prescribes: placeholder underlines, no computed syntax — and with two
typos planted the way real drafts plant them accidentally (``sensro``,
``batery``).

***********
The draft
***********

.. code-block:: rst

    Weather station
    #########

    Балконная метеостанция: датчик шлёт температуру каждые пять минут.

    Sensors
    *********

    **Note:** the sensor battery lasts about a month.

    The sensor reports temperature over MQTT; the sensro drops
    a reading when the batery is low.

    Colleague's advice:

        Try lowering the sensor polling interval — the sensor
        warms itself when polled too often.

    .. code-block:: python

       READ_INTERVAL = 300  # seconds, not prose

    Recent readings:

    .. list-table:: Sensor readings
       :header-rows: 1

       * - Time
         - Temp
       * - 09:00
         - 21.4
       * - 09:05
         - 21.6

    История
    *********

    Вчера датчик завис.  Перезагрузил датчик — датчик работает.

********************************
Editing: review, fix, converge
********************************

Step 1 (``--skip-fixable``) surfaces the single thing needing
judgment::

      (bold paragraph opener: AI documents often use this pattern as an
      informal heading; consider a proper section title)
    station.rst:9: WARNING: bold paragraph opener 'Note:'

No leading glyph and no ``path:line:``-shaped hint line by accident: the
finding itself is bare ``path:line: WARNING: message`` — de-facto compiler
output, the shape generic tooling (IDE problem matchers, editor jump-to-
error) parses — and the shared rationale prints once per run, not once
per finding, above the first finding it applies to (see "De-facto
compiler output" in :doc:`guide`).

The judgment is yours: here ``**Note:**`` is a legitimate note marker,
not a heading substitute — leave it.  Step 2 (``fix``; explicit
filename only because this file is freshly invented and entirely ours
to normalize) materializes the syntax the placeholders declared::

    #################
    Weather station
    #################

Seventeen ``#`` for a fifteen-character title — computed, never
counted by hand.

********************************
Analysis: the structure oracle
********************************

``check_rst outline --verbose station.rst`` — structure-only is
``outline``'s own default now, still implying ``--quiet``; ``--verbose``
adds the ``blocks:``/``lines:``/``words:``/top-and-rare-prose-words level-2
lines the main guide's "Verbosity levels" section describes; ``levels:`` and
the entries themselves would already be there without it.  This transcript was
regenerated on 2026-07-30 with Python 3.14.6, Sphinx 9.1.0, docutils 0.23, and
snowballstemmer 3.1.1.  The top/rare-word tail depends on Sphinx's stopword
tables and snowballstemmer and must be regenerated, not copied as a stable
golden value, when that runtime changes::

    Outline: station.rst
      levels: 1 '#' (1), 2 '*' (2), 3 sections total
      blocks: 1 code block, 1 blockquote, 1 table
      2-41:# Weather station [2 subsections, 1 code block, 1 blockquote, 1 table]
          8-35:* Sensors [1 code block, 1 blockquote, 1 table]
              18-19: blockquote "Try lowering the sensor polling interval — the sensor warms itself when po..."
              21-23: code-block (python): READ_INTERVAL = 300 # seconds, not prose
              27-35: Table (list, 3x2), "Sensor readings": Time Temp 09:00 21.4 09:05 21.6
          38-41:* История
    check_rst: 1 file(s) checked, 0 error(s), 1 warning(s), 719 char(s) (87 distinct, 31 once), 835 byte(s), 112 space(s) (16%)
    lines: 41 total (13 empty, 32%), length min/avg/max 7/24/66 chars / 7/28/123 bytes
    words: 100 total, 75 distinct (64 once), length min/avg/max 1/6/17
    top prose words: sensor (6 @11), датчик (4 @5), readings (3 @25), polling (2 @18), when (2 @14),
      about (1 @11), advice (1 @16), batery (1 @14), battery (1 @11), colleague (1 @16) (yet 34 suppressed)
    rare prose words: batery @14 ↔ battery @11, sensro @13 (~sensor 6x), about @11, advice @16,
      colleague @16, drops @13, interval @18, itself @19, lasts @11, low @14 (yet 28 suppressed)

What an AI reads off this, line by line — as its own subsections, not a
bullet list: this whole page argues for ``outline`` because a
compressed structure beats opening a file to find things, and a
bulleted list of eight points would be invisible to exactly that
oracle, undermining the argument on its own page.  As sections, each
point is independently visible in ``outline``, addressable at a
specific range, and a candidate ``:ref:`` target — a live instance of
the value this page sells rather than an assertion of it.

=============================
Levels legend, with a total
=============================

The depth→char mapping, per-level section counts, and the document's
total section count in one place; depth is recoverable from any
grepped line's indentation (4 spaces per level).

================================================
Every entry states its own adornment character
================================================

``2-41:# Weather station``, ``8-35:* Sensors`` — the char sits right
after the range, on every entry, not only in the legend above (Max,
2026-07-20, reversing a 2026-07-18 decision that called this
per-entry repetition "pure noise"): picking the right character for a
*new* heading means knowing the established char at that exact depth,
and cross-referencing a legend against indentation in a large,
evolving document is precisely the kind of counting task an LLM is
unreliable at — confirmed the hard way, writing this very page,
getting it wrong twice in one session before this feature existed.
Add a sibling under any grepped line by copying its character
directly; no legend lookup, no counting.

===============
Blocks legend
===============

Code-block/blockquote/table totals for the whole document, one line,
omitted entirely when there are none of them (a prose-only file shows
no ``blocks:`` line at all — absence is itself information).

=========================
Ranges, not start lines
=========================

``8-35: Sensors`` feeds a targeted read (``sed -n '8,35p'``) with no
arithmetic.

===========================================================
Bracketed counts are cumulative, not just direct children
===========================================================

``Weather station``'s ``[2 subsections, 1 code block, 1 blockquote,
1 table]`` rolls up everything under it, including what's nested
inside ``Sensors``; a depth-limited view (``--outline-depth 1``)
would still show that same total even with ``Sensors`` itself
hidden — the limit trims *entries*, never the *information* about
what they contain.

=======================================================
Every preview is the same contract, three entry kinds
=======================================================

The blockquote's preview is quoted material (exempt from the
bold/rubric warnings, which is *why* the outline shows it at all)
truncated at 74 characters with ``...`` (here it actually hits the
bound); the code-block's language is unquoted (``(python)``, not
``('python')``) and its own content is now previewed the same way
(``READ_INTERVAL = 300 # seconds, not prose``); the table adds its
syntax kind, dimensions, and caption, then chains every row's cells
in order — header row first — into that same collapsed, truncated
preview (short enough here to show whole: ``Time Temp 09:00 21.4
09:05 21.6``).

======================================
The footer tells the truth even here
======================================

1 warning counted (the bold opener left to judgment), and the
statistics separate layers — raw ``words:`` versus *prose* words (the
code-block's ``READ_INTERVAL`` is in neither top nor rare: code is
not prose).

=======================================
Top prose words are the file's themes
=======================================

``sensor`` and ``датчик``, each with a first-match jump target;
``readings`` ranks third purely from the table's own caption and
lead-in line, a small demonstration that table text is prose too.

=======================================================
Rare prose words surface both planted typos, as facts
=======================================================

``batery @14 ↔ battery @11`` — two once-words one edit apart, the
small-page typo signature, reported once as a symmetric pair — and
``sensro @13 (~sensor 6x)`` — a once-word one edit from a frequent
word, the frequency asymmetry pointing at the mistake.  The tool
never says "typo": ``advice @16`` sits in the same list, a perfectly
good word that simply occurs once.  Judgment stays yours — at these
jump targets, it takes seconds.

And the same model as machine-readable data —
``check_rst check --format=json --verbose station.rst`` (outline data is
always part of the JSON model, so there is no separate outline flag to add;
``--verbose`` again, for the same reason as above: ``rare_words``/``top_words`` are
``null`` without it or an explicit ``--word-samples``; stable ids,
extents, every entry's own preview/kind/dims fields, the rare pairs)::

    {"lineno": 8, "depth": 2, "char": "*", "title": "Sensors",
     "children": 0, "end": 35, "docname": null, "id": "station:Sensors"}
    {"lineno": 21, "depth": 3, "language": "python",
     "preview": "READ_INTERVAL = 300 # seconds, not prose", "end": 23}
    {"lineno": 27, "depth": 3, "kind": "list", "dims": [3, 2],
     "caption": "Sensor readings",
     "preview": "Time Temp 09:00 21.4 09:05 21.6", "end": 35}
    "rare_words": [["batery", "battery", 1], ["sensro", "sensor", 6]], …

One file, one loop, one oracle: the AI wrote intent and judged one
warning; everything countable, locatable, and structural came from the
tool.
