from digital_pdf_toolkit.cli import build_parser


def test_cli_exposes_explicit_modes_and_bindings() -> None:
    parser = build_parser()
    preprocess = parser.parse_args([
        "preprocess", "retry", "doc-0819-1430", "--from", "attempt-001_0819-1432",
        "--overrides", "overrides.json",
    ])
    assert preprocess.parent_attempt == "attempt-001_0819-1432"
    analyze = parser.parse_args([
        "analyze", "create", "doc-0819-1430", "--page-set",
        "preprocess:attempt-002_0819-1505", "--tools", "paddle,surya",
    ])
    assert analyze.page_set == "preprocess:attempt-002_0819-1505"
    finalize = parser.parse_args([
        "finalize", "create", "doc-0819-1430", "--tool", "paddle",
        "--attempt", "attempt-001_0819-1520",
    ])
    assert finalize.attempt == "attempt-001_0819-1520"


def test_aggregate_run_command_is_removed() -> None:
    parser = build_parser()
    try:
        parser.parse_args(["run", "sample.pdf"])
    except SystemExit as exc:
        assert exc.code != 0
    else:  # pragma: no cover
        raise AssertionError("legacy run command should not parse")
