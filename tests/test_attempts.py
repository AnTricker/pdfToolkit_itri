from pathlib import Path

from digital_pdf_toolkit.identifiers import next_attempt_id


def test_attempt_ids_keep_namespace_sequence(tmp_path: Path) -> None:
    (tmp_path / "attempt-001_0819-1432").mkdir()
    (tmp_path / "attempt-002_0819-1505").mkdir()
    value = next_attempt_id(tmp_path)
    assert value.startswith("attempt-003_")
