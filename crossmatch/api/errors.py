"""Shared exception types for the read-model API layer.

``InvalidQuery`` lives here rather than in ``service.py`` so both ``service.py``
and ``pagination.py`` can import it without a circular import: ``service.py``
imports the cursor codec from ``pagination.py``, so a top-level
``from api.service import InvalidQuery`` inside the codec would cycle. It is
re-exported from ``service.py`` for existing importers (e.g. ``api/views.py``).
"""

from __future__ import annotations


class InvalidQuery(ValueError):
    """A request parameter is invalid; the view maps this to HTTP 400."""
