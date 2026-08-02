import json

from prisma_sdwan_mcp.tools.config_gen import generate_site_config


def test_schema_resolves_from_unrelated_working_directory(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    result = json.loads(
        generate_site_config(
            site_id="site-1",
            elements=[{"serial_number": "serial-1"}],
            filename="generated.yaml",
        )
    )

    assert result["status"] == "success"
    assert result["filename"] == str(tmp_path / "generated.yaml")
    assert (tmp_path / "generated.yaml").exists()


def test_path_traversal_and_absolute_paths_are_rejected(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    elements = [{"serial_number": "serial-1"}]

    for filename in ("../outside.yaml", "/outside.yaml", r"C:\outside.yaml"):
        result = json.loads(
            generate_site_config(site_id="site-1", elements=elements, filename=filename)
        )
        assert result["code"] == "invalid_filename"

    assert list(tmp_path.iterdir()) == []