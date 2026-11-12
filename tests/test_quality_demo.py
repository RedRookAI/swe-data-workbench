"""Exercise the public account-free example with actual checks and frozen decisions."""
from tools.run_quality_demo import run_demo


def test_documented_quality_example(tmp_path):
    receipt = run_demo(tmp_path / "quality")
    assert receipt["new_model_calls"] == 0
    assert receipt["integrity"]["ok"]
    assert receipt["ordinary_verification"]["accepted_count"] == 0
    assert [version["score"]["context"]["quality"]["decision"] for version in receipt["versions"]] == ["needs-repair", "approved"]
    # run_demo verifies each named patch's exact score and critical gate,
    # missing evidence, reproducible export identity and original input hashes.
