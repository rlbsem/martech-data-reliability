import pytest

from crash_proof import POINTS, experiment


@pytest.mark.parametrize("point", POINTS)
def test_real_process_death_and_reopen(tmp_path, point):
    assert experiment(tmp_path, point)["recovery_passed"]
