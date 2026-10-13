import pytest

from render_betta_label import valid_tank_number


@pytest.mark.parametrize("tank", ["5BT24", "APE16"])
def test_valid_tank_number_accepts_supported_namespaces(tank):
    assert valid_tank_number(tank)


@pytest.mark.parametrize("tank", ["", "APE", "BT16", "5BT"])
def test_valid_tank_number_rejects_malformed_values(tank):
    assert not valid_tank_number(tank)
