"""Opt-in hosted failure-path qualification. Not included in normal test discovery."""
def test_intentional_failure_artifact():
    assert False, 'Intentional real pytest failure: qualify artifact delivery without making CI green.'
