from nepal_flashflood.config import load_config


def test_load_config(tmp_path):
    config_path = tmp_path / "config.yaml"
    config_path.write_text("project:\n  name: test\n", encoding="utf-8")
    assert load_config(config_path)["project"]["name"] == "test"

