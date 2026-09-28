..
   Copyright (C) 2026 Maxime P. DEMENTYEV
   SPDX-License-Identifier: GPL-3.0-only
   Maintainer release procedure — check_rst project

#####################
Releasing check_rst
#####################

This procedure defines the repository's release identity and Git tag contract.
The package version in ``src/check_rst/__init__.py`` remains the build's single
source of truth; tags label releases but do not determine package metadata.

******************
Release identity
******************

A release consists of two commits on ``main`` followed by one annotated,
explicitly unsigned tag:

#. A committed failing test change named
   ``test: RED require the X.Y.Z release identity``.
#. A version-bump commit named ``release: bump check_rst to X.Y.Z``.
#. A tag named ``vX.Y.Z`` on the version-bump commit.

The tag suffix is the exact ``__version__`` string.  Tag the commit that first
reports that version, never a later commit and never the last commit before the
next version bump.  Release branches are not used unless a real backport need
establishes their contract.

*****************************
Prepare the release commits
*****************************

#. Decide the version and record what the release contains, its compatibility
   consequences, and whether anything breaks.
#. Move every exact release-identity expectation to the new version.  This
   includes ``--version``, runtime text, JSON runtime provenance, and the
   pygit2-floor acceptance output.  Run the focused tests, confirm that they
   fail for the old version source, and commit that failing state as
   ``test: RED require the X.Y.Z release identity``.
#. Update ``src/check_rst/__init__.py``, the README wheel example, and a dated
   roadmap Shipped entry.  Confirm the focused tests pass and commit the result
   as ``release: bump check_rst to X.Y.Z``.  Never combine the version bump
   with a feature implementation.

The release commit body is the durable release record.  It states the features,
fixes, compatibility changes, observed RED/GREEN result, and validation.  For a
breaking change it also states the distinctive downstream failure signature
required by ``AGENTS.md``.

Run the complete validation from ``AGENTS.md`` and build the wheel from the
version-bump commit.  The built artifact must therefore contain the same source
that the tag will identify.

***************************
Create and verify the tag
***************************

The tagger identity is ``Maxime P. DEMENTYEV <dememax@hotmail.com>``.  Before
tagging, inspect the effective identity and ensure no environment override can
backdate the tag:

.. code-block:: bash

   git var GIT_COMMITTER_IDENT
   test -z "${GIT_COMMITTER_DATE-}"

Create the tag with ``--no-sign`` so host configuration cannot silently change
the chosen unsigned-tag policy:

.. code-block:: bash

   git tag --no-sign -a vX.Y.Z -F <message-file> <release-commit>

The message has this form:

.. code-block:: text

   check_rst X.Y.Z

   <One-paragraph summary of features, fixes, and compatibility changes.>

   Breaking changes: none.

Replace ``none`` with the diagnosable failure signature when the release
breaks compatibility.  Do not restate dates: Git already records the commit
date and the tag's real creation date.

Verify the object type, target, and version source before publication:

.. code-block:: bash

   test "$(git cat-file -t vX.Y.Z)" = tag
   test "$(git rev-parse 'vX.Y.Z^{commit}')" = "$(git rev-parse <release-commit>)"
   git show vX.Y.Z:src/check_rst/__init__.py | rg -Fx '__version__ = "X.Y.Z"'

*******************************
Publish named refs atomically
*******************************

Publishing is a separate, outward-facing action and requires the maintainer's
explicit go-ahead.  Fetch first, confirm that ``origin/main`` is still the
parent of the two release commits, and check the prospective tag name without
masking a remote-query failure:

.. code-block:: bash

   git fetch origin
   remote_tags=$(git ls-remote --tags origin vX.Y.Z) \
     || { echo "remote tag check failed; stop"; exit 1; }
   test -z "$remote_tags" \
     || { echo "tag vX.Y.Z already exists on origin; stop"; exit 1; }
   git push --atomic origin main vX.Y.Z

Push named refs only.  Never use ``--tags`` or rely on ``--follow-tags``.
Atomic publication prevents a rejected branch or tag update from leaving only
part of the release on the remote.

A published tag is not moved or deleted to correct ordinary release content,
notes, or bugs; make a new patch release.  A security, credential-exposure, or
legal incident can justify deletion.  Such a deletion is deliberate and
disclosed, and cannot remove copies that other repositories already fetched.

*********************
Historical backfill
*********************

The initial backfill labels all nine version-introducing commits from 0.1.0
through 0.7.0.  Its messages say that the version was introduced by the target
commit and that the tag was created retroactively; they do not invent unknown
publication dates or retrospective release summaries.  The 0.1.0 message
identifies the seeded, unannounced initial state, and the 0.5.0 message identifies
the feature commit that carried its version bump and CLI break.

Backfill tags use the same name, target, object type, identity, real tag date,
and publication rules as new releases.  Create and verify the complete local
set before requesting permission for one atomic push of the nine named refs.
