"""Sortable run IDs of the form YYYYMMDDHHMMSS-<8 hex chars>."""

from __future__ import annotations

import secrets
from datetime import UTC, datetime


def generate_run_id(*, now: datetime | None = None) -> str:
    when = now or datetime.now(tz=UTC)
    stamp = when.strftime("%Y%m%d%H%M%S")
    return f"{stamp}-{secrets.token_hex(4)}"


def parse_run_id_timestamp(run_id: str) -> datetime:
    stamp, _hex = run_id.split("-", 1)
    return datetime.strptime(stamp, "%Y%m%d%H%M%S").replace(tzinfo=UTC)
