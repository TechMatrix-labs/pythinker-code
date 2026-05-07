from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from pythinker_code.auth.oauth import OAuthManager
    from pythinker_code.config import LLMProvider

UsageUnit = str  # one of: "tokens", "USD", "CNY", "%", "requests", "credits"


@dataclass(slots=True, frozen=True)
class UsageRow:
    label: str
    used: int
    limit: int
    unit: UsageUnit | None = None
    reset_hint: str | None = None


@dataclass(slots=True, frozen=True)
class UsageReport:
    provider_label: str
    summary: UsageRow | None
    limits: list[UsageRow]
    notes: list[str] = field(default_factory=lambda: list[str]())
    unit_hint: str | None = None

    @property
    def is_empty(self) -> bool:
        return self.summary is None and not self.limits and not self.notes

    def to_dict(self) -> dict[str, object]:
        return {
            "provider_label": self.provider_label,
            "unit_hint": self.unit_hint,
            "summary": (
                {
                    "label": self.summary.label,
                    "used": self.summary.used,
                    "limit": self.summary.limit,
                    "unit": self.summary.unit,
                    "reset_hint": self.summary.reset_hint,
                }
                if self.summary
                else None
            ),
            "limits": [
                {
                    "label": r.label,
                    "used": r.used,
                    "limit": r.limit,
                    "unit": r.unit,
                    "reset_hint": r.reset_hint,
                }
                for r in self.limits
            ],
            "notes": list(self.notes),
        }


class UsageAdapter(Protocol):
    platform_id: str
    provider_label: str
    requires_admin_key: bool

    async def fetch(
        self,
        provider: LLMProvider,
        oauth_mgr: OAuthManager,
    ) -> UsageReport: ...
