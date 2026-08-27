from pathlib import Path

from digital_pdf_toolkit.config import deep_merge, load_config


ROOT = Path(__file__).resolve().parents[1]


def test_deep_merge_does_not_drop_siblings() -> None:
    assert deep_merge({"a": {"b": 1, "c": 2}}, {"a": {"b": 3}}) == {
        "a": {"b": 3, "c": 2}
    }


def test_profile_and_tool_resolution() -> None:
    config = load_config(ROOT, profile="extract-only", tools=["mineru"])
    assert config["profile"]["stages"] == ["extract"]
    assert config["resolved_tools"] == ["mineru"]
    assert config["tools"]["mineru"]["options"]["effort"] == "high"

