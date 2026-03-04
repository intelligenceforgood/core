"""Schema definitions for i4g storage.

Defines the canonical in-memory representation for records persisted to the
structured store and vectors. This dataclass is intended to be simple and
JSON-serializable so it can be stored in SQLite without additional DB layers.
"""

from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import Any


@dataclass
class ScamRecord:
    """Unified normalized record stored in i4g structured storage.

    Attributes:
        case_id: Unique identifier for the case (external or internal).
        text: The original text (or OCR concatenation) that produced these entities.
        entities: Normalized entity map, e.g., {"people": ["Alice"], "wallet_addresses": ["0x..."]}.
        classification: Highest-level classification label (e.g., "crypto_investment").
        confidence: Fraud confidence score in [0.0, 1.0].
        created_at: UTC timestamp when the record was created.
        embedding: Optional numeric embedding vector (list of floats).
        metadata: Optional free-form metadata dictionary.
    """

    case_id: str
    text: str
    entities: dict[str, list[str]]
    classification: str
    confidence: float
    classification_status: str = "pending"
    classification_result: dict[str, Any] | None = None
    tags: list[str] | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    embedding: list[float] | None = None
    metadata: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        """Serialize the ScamRecord to a JSON-safe dictionary.

        Returns:
            A dictionary with JSON-serializable values.
        """
        d = asdict(self)
        # created_at -> ISO string
        d["created_at"] = self.created_at.isoformat()
        # embedding and metadata are already JSON-safe (if they are None or simple types)
        return d

    @staticmethod
    def from_dict(d: dict[str, Any]) -> "ScamRecord":
        """Deserialize a ScamRecord from a dictionary.

        Args:
            d: Dictionary produced by :meth:`to_dict` or loaded from storage.

        Returns:
            ScamRecord instance.
        """
        created_at = d.get("created_at")
        if isinstance(created_at, str):
            created_at = datetime.fromisoformat(created_at)
        return ScamRecord(
            case_id=d["case_id"],
            text=d.get("text", ""),
            entities=d.get("entities", {}),
            classification=d.get("classification", ""),
            confidence=float(d.get("confidence", 0.0)),
            classification_status=d.get("classification_status", "pending"),
            classification_result=d.get("classification_result"),
            tags=d.get("tags"),
            created_at=created_at or datetime.now(UTC),
            embedding=d.get("embedding"),
            metadata=d.get("metadata"),
        )
