from pathlib import Path

from lexiaodu.demo_data import load_demo_materials


def test_load_fictional_demo_materials() -> None:
    materials = load_demo_materials(Path("demo/reading_materials.json"))

    assert len(materials) == 2
    assert all("虚构演示资料" in item.source_note for item in materials)
    assert len({item.identifier for item in materials}) == len(materials)
