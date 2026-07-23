import os
from pathlib import Path

import pytest

from src.navigation.odometry_contract_r2_p2.frame_semantics import frame_vocabulary
from src.navigation.odometry_contract_r2_p2.models import ValidationContext


MAPPING_ENV = os.environ.get("OTTOGUIDE_P2_MAPPING_ROOT")


@pytest.mark.skipif(not MAPPING_ENV, reason="explicit P2 mapping root not provided")
def test_mapping_root_contains_preserved_replay_inputs():
    root = Path(MAPPING_ENV)
    assert root.is_dir()
    db3 = list(root.glob("**/*.db3"))
    assert len(db3) >= 3
    assert any(root.glob("**/metadata.yaml"))


@pytest.mark.skipif(not MAPPING_ENV, reason="explicit P2 mapping root not provided")
def test_mapping_inputs_are_references_not_physical_promotion():
    root = Path(MAPPING_ENV)
    before = {path.relative_to(root) for path in root.glob("**/metadata.yaml")}
    entries = frame_vocabulary()
    after = {path.relative_to(root) for path in root.glob("**/metadata.yaml")}
    assert before == after
    mapping_entries = [
        entry for entry in entries
        if entry.validation_context is ValidationContext.OFFLINE_REPLAY
    ]
    assert mapping_entries
    assert all(entry.claim_strength != "PHYSICAL_VERIFIED" for entry in mapping_entries)
