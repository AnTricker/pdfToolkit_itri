from pathlib import Path

from digital_pdf_toolkit.config import deep_merge, load_config


ROOT = Path(__file__).resolve().parents[1]


def test_deep_merge_does_not_drop_siblings() -> None:
    assert deep_merge({"a": {"b": 1, "c": 2}}, {"a": {"b": 3}}) == {
        "a": {"b": 3, "c": 2}
    }


def test_default_surya2_and_marker_config_are_loaded() -> None:
    config = load_config(ROOT)
    assert config["project"]["render_dpi"] == 150
    assert config["surya2"]["environment"] == "digital-pdf-surya"
    assert config["surya2"]["command"][0] == "surya_ocr"
    assert config["marker"]["environment"] == "digital-pdf-marker"
    assert config["marker"]["mode"] == "balanced"
    assert config["marker"]["inference_backend"] == "llamacpp"
    assert config["marker"]["command"][0] == "python"
