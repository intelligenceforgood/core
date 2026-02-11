"""CamelCase-serialising Pydantic base model for API responses.

All API **response** models should inherit from ``CamelModel`` rather than
plain ``BaseModel``.  Request models stay as ``BaseModel``.  This gives us:

* **snake_case field names in Python** — idiomatic for backend code.
* **camelCase JSON keys on the wire** — idiomatic for TypeScript clients.
* ``populate_by_name=True`` so constructors accept *either* casing.

Usage::

    from i4g.api.camel import CamelModel

    class MyResponse(CamelModel):
        user_name: str          # Python attribute name
        # JSON serializes to {"userName": "..."}
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel


class CamelModel(BaseModel):
    """Base model that serialises field names as camelCase in JSON."""

    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
    )
