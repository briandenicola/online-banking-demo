"""Tests against Turk's REAL ``banker-copilot-service`` — the only ones that can fail
because of somebody else's code.

Everything in ``tests/`` outside this package runs against the spec oracle in
``spec/``. A green run there means the SPECIFICATION is coherent. This package
is different: it imports ``src/banker-copilot-service`` and asserts against the
shipping loader, registry, executor, envelope and routes.

The separation is deliberate and load-bearing — it is the same split Phase 1
kept between ``Spec/`` and ``Production/``, for the same reason: it must never
be possible to read a green suite and not know which of the two you proved.
"""
