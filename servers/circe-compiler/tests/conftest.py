import json
from pathlib import Path

import pytest

FIXTURE_DIR = Path(__file__).parent / "fixtures"


@pytest.fixture
def fixture_dir():
    """Return the path to the test fixtures directory."""
    return FIXTURE_DIR


@pytest.fixture
def t2dm_cohort_json(fixture_dir):
    """Load the T2DM + metformin - heart failure cohort definition."""
    with open(fixture_dir / "t2dm_metformin_no_hf.json") as f:
        return json.load(f)
