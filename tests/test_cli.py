import pytest

from digital_pdf_toolkit.cli import build_parser


def test_cli_exposes_only_extract_and_surya2() -> None:
    parser = build_parser()
    extract = parser.parse_args(["extract", "document.pdf", "--config", "custom.yml"])
    assert extract.command == "extract"
    assert extract.input.name == "document.pdf"
    surya2 = parser.parse_args(["surya2", "images"])
    assert surya2.command == "surya2"


@pytest.mark.parametrize("legacy", ["pages", "preprocess", "resolution", "analyze", "finalize"])
def test_legacy_commands_are_removed(legacy: str) -> None:
    parser = build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args([legacy])
