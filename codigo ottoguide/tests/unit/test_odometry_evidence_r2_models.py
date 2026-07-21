"""Unit tests for src.navigation.odometry_evidence_r2.models: structural
invariants that must fail closed at construction time."""
import unittest

from src.navigation.odometry_evidence_r2.models import (
    ChannelComparisonEvidence,
    CovarianceEvidence,
    EvidenceClaim,
    ResetDiscontinuityEvidence,
)


class TestChannelComparisonNoAuthority(unittest.TestCase):
    def test_null_authoritative_channel_accepted(self):
        evidence = ChannelComparisonEvidence(
            evidence_id="x", status="PARTIAL",
            primary_channel="rt/odommodestate", secondary_channel="rt/lf/odommodestate",
            primary_sample_count=10, secondary_sample_count=5,
            authoritative_source_channel=None,
            primary_analysis_stream_candidate=True,
            arbitration_status="UNRESOLVED", observations=(),
            source_files=("a.json",), source_sha256=("a" * 64,),
        )
        self.assertIsNone(evidence.authoritative_source_channel)

    def test_non_null_authoritative_channel_rejected(self):
        # A higher sample rate must never be treated as authority (checkpoint
        # section 19): this must raise, not silently accept a channel name.
        with self.assertRaises(ValueError):
            ChannelComparisonEvidence(
                evidence_id="x", status="PARTIAL",
                primary_channel="rt/odommodestate", secondary_channel="rt/lf/odommodestate",
                primary_sample_count=10, secondary_sample_count=5,
                authoritative_source_channel="rt/odommodestate",
                primary_analysis_stream_candidate=True,
                arbitration_status="UNRESOLVED", observations=(),
                source_files=("a.json",), source_sha256=("a" * 64,),
            )


class TestCovarianceNeverPublicationReady(unittest.TestCase):
    def test_partial_not_ready_accepted(self):
        evidence = CovarianceEvidence(
            evidence_id="cov", status="PARTIAL", publication_model_ready=False,
            stationary_stats_ids=("stat.1",), dynamic_stats_ids=(),
            source_files=("a.json",), source_sha256=("a" * 64,),
        )
        self.assertFalse(evidence.publication_model_ready)

    def test_publication_ready_true_rejected(self):
        with self.assertRaises(ValueError):
            CovarianceEvidence(
                evidence_id="cov", status="PARTIAL", publication_model_ready=True,
                stationary_stats_ids=("stat.1",), dynamic_stats_ids=(),
                source_files=("a.json",), source_sha256=("a" * 64,),
            )

    def test_no_referenced_statistics_rejected(self):
        with self.assertRaises(ValueError):
            CovarianceEvidence(
                evidence_id="cov", status="PARTIAL", publication_model_ready=False,
                stationary_stats_ids=(), dynamic_stats_ids=(),
                source_files=("a.json",), source_sha256=("a" * 64,),
            )


class TestResetDiscontinuityBootSeparation(unittest.TestCase):
    def test_distinct_boot_ids_accepted(self):
        evidence = ResetDiscontinuityEvidence(
            evidence_id="reset", status="VERIFIED",
            exact_reset_instant_status="UNRESOLVED",
            from_session_id="s1", to_session_id="s2",
            from_boot_id="boot-a", to_boot_id="boot-b",
            trajectory_concatenation_permitted=False,
            source_files=("a.json",), source_sha256=("a" * 64,),
        )
        self.assertNotEqual(evidence.from_boot_id, evidence.to_boot_id)

    def test_same_boot_id_rejected(self):
        with self.assertRaises(ValueError):
            ResetDiscontinuityEvidence(
                evidence_id="reset", status="VERIFIED",
                exact_reset_instant_status="UNRESOLVED",
                from_session_id="s1", to_session_id="s2",
                from_boot_id="boot-a", to_boot_id="boot-a",
                trajectory_concatenation_permitted=False,
                source_files=("a.json",), source_sha256=("a" * 64,),
            )

    def test_concatenation_permitted_true_rejected(self):
        # R3C and R4 must never be treated as one continuous trajectory.
        with self.assertRaises(ValueError):
            ResetDiscontinuityEvidence(
                evidence_id="reset", status="VERIFIED",
                exact_reset_instant_status="UNRESOLVED",
                from_session_id="s1", to_session_id="s2",
                from_boot_id="boot-a", to_boot_id="boot-b",
                trajectory_concatenation_permitted=True,
                source_files=("a.json",), source_sha256=("a" * 64,),
            )


class TestEvidenceClaimVerifiedRequiresEvidence(unittest.TestCase):
    def test_verified_with_evidence_accepted(self):
        claim = EvidenceClaim(
            claim_id="X", r1_state="A", v19_state="B", r2p0_state="VERIFIED",
            reason="because", evidence_ids=("some.evidence",), confidence="HIGH",
        )
        self.assertEqual(claim.r2p0_state, "VERIFIED")

    def test_verified_without_evidence_rejected(self):
        with self.assertRaises(ValueError):
            EvidenceClaim(
                claim_id="X", r1_state="A", v19_state="B", r2p0_state="VERIFIED",
                reason="because", evidence_ids=(), confidence="HIGH",
            )

    def test_unresolved_without_evidence_allowed(self):
        claim = EvidenceClaim(
            claim_id="X", r1_state="A", v19_state="B", r2p0_state="UNRESOLVED",
            reason="still open", evidence_ids=(), confidence="LOW",
        )
        self.assertEqual(claim.r2p0_state, "UNRESOLVED")


class TestUnknownFieldRejectedByDataclassSignature(unittest.TestCase):
    def test_unknown_kwarg_raises_typeerror(self):
        with self.assertRaises(TypeError):
            EvidenceClaim(
                claim_id="X", r1_state="A", v19_state="B", r2p0_state="UNRESOLVED",
                reason="x", evidence_ids=(), confidence="LOW",
                unexpected_field="should not be accepted",
            )


if __name__ == "__main__":
    unittest.main()
