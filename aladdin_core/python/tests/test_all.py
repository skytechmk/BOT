import pytest
import aladdin_core


def test_sum_as_string():
    assert aladdin_core.sum_as_string(1, 1) == "2"
