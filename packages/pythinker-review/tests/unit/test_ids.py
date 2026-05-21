import re
from datetime import UTC, datetime

from pythinker_review.store.ids import generate_run_id, parse_run_id_timestamp

RUN_ID_RE = re.compile(r"^\d{14}-[0-9a-f]{8}$")


def test_generate_run_id_matches_format() -> None:
    assert RUN_ID_RE.fullmatch(generate_run_id())


def test_generate_run_id_sorts_lexicographically_by_time() -> None:
    fixed = datetime(2026, 5, 20, 12, 30, 45, tzinfo=UTC)
    later = datetime(2026, 5, 20, 12, 30, 46, tzinfo=UTC)
    assert generate_run_id(now=fixed) < generate_run_id(now=later)


def test_parse_run_id_timestamp() -> None:
    fixed = datetime(2026, 5, 20, 12, 30, 45, tzinfo=UTC)
    parsed = parse_run_id_timestamp(generate_run_id(now=fixed))
    assert parsed.tzinfo is UTC
    assert parsed == fixed


def test_two_ids_in_same_second_differ() -> None:
    fixed = datetime(2026, 5, 20, 12, 30, 45, tzinfo=UTC)
    assert generate_run_id(now=fixed) != generate_run_id(now=fixed)
