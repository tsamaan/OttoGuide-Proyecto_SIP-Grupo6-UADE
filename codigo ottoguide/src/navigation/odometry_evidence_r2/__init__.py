"""ODOM/TF R2-P0: versioned, offline, fail-closed physical evidence ingestion.

Separate from odometry_candidate_adapter (R1), which remains untouched as
the R1 baseline/regression contract. This package never publishes /odom,
TF, /scan, a map, localization, cmd_vel, or Nav2 -- see
docs/Arquitectura/ODOM_TF_R2_PHYSICAL_EVIDENCE_CONTRACT.md.
"""
from .models import SCHEMA_VERSION

__all__ = ["SCHEMA_VERSION"]
