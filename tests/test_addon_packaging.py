"""Guard against embedding a second Supervisor-discoverable add-on manifest."""

import shutil
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]


def test_embedded_backend_has_only_one_discoverable_addon(tmp_path):
    template = ROOT / "backend/config/addon-config.reference.yaml"
    shutil.copytree(ROOT / "backend", tmp_path / "backend")
    shutil.copyfile(template, tmp_path / "config.yaml")
    candidates = []
    for path in tmp_path.rglob("config.*"):
        if path.suffix not in {".yaml", ".yml", ".json"}:
            continue
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        if isinstance(data, dict) and "slug" in data and "arch" in data:
            candidates.append(path.relative_to(tmp_path).as_posix())
    assert candidates == ["config.yaml"]
    assert (tmp_path / "backend/config/__init__.py").is_file()


def test_sync_reads_renamed_template():
    workflow = (ROOT / ".github/workflows/sync-to-addon.yml").read_text(
        encoding="utf-8"
    )
    assert 'cp backend/config/addon-config.reference.yaml "$TARGET_DIR/config.yaml"' in workflow
    assert "backend/config/config.yaml" not in workflow
