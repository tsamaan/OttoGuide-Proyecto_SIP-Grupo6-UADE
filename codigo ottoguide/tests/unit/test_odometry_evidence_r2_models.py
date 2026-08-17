"""Unit tests for src.navigation.odometry_evidence_r2.models: structural
invariants that must fail closed at construction time."""
import unittest

from src.navigation.odometry_evidence_r2.models import (
    ChannelComparisonEvidence,
    CovarianceEvidence,
    EvidenceClaim,
    GroundTruthConstraint,
    ImuCrosscheckEvidence,
    JsonlParseReport,
    LidarExtrinsicEvidence,
    PhysicalEvidenceBundleR2,
    PhysicalSessionEvidence,
    ResetDiscontinuityEvidence,
    SessionTimeDomain,
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


class TestSourceFilesHashesLengthMismatch(unittest.TestCase):
    def test_mismatched_lengths_rejected(self):
        with self.assertRaises(ValueError):
            PhysicalSessionEvidence(
                evidence_id="s1", status="VERIFIED", confidence="HIGH",
                session_id="sess1", session_type="R3C_MANUAL_PHYSICAL_ROUTE",
                boot_id=None, clean_shutdown=True,
                physical_movement_authority="HUMAN_OPERATOR_ONLY",
                streams=("rt/odommodestate",), phases=("UNMARKED",), provenance=(),
                source_files=("a.json", "b.json"), source_sha256=("a" * 64,),
            )


class TestGroundTruthConstraintValidation(unittest.TestCase):
    def test_valid_best_effort_accepted(self):
        gtc = GroundTruthConstraint(
            mode="BEST_EFFORT_MEASURED", nominal_translation_m=2.0, nominal_yaw_rad=None,
            measurement_uncertainty="UNKNOWN_UNBOUNDED_VISUAL_ESTIMATE",
            source="operator_annotation", status="PARTIAL",
        )
        self.assertEqual(gtc.mode, "BEST_EFFORT_MEASURED")

    def test_invalid_mode_rejected(self):
        with self.assertRaises(ValueError):
            GroundTruthConstraint(
                mode="PROBABLY_TRUE", nominal_translation_m=None, nominal_yaw_rad=None,
                measurement_uncertainty="x", source="x", status="PARTIAL",
            )

    def test_measured_with_unbounded_uncertainty_rejected(self):
        # A mode of MEASURED (never BEST_EFFORT_MEASURED) implies a
        # calibrated measurement -- it cannot coexist with an unbounded
        # uncertainty description.
        with self.assertRaises(ValueError):
            GroundTruthConstraint(
                mode="MEASURED", nominal_translation_m=1.0, nominal_yaw_rad=None,
                measurement_uncertainty="UNKNOWN_UNBOUNDED_VISUAL_ESTIMATE",
                source="x", status="VERIFIED",
            )

    def test_nan_nominal_value_rejected(self):
        with self.assertRaises(ValueError):
            GroundTruthConstraint(
                mode="NOMINAL", nominal_translation_m=float("nan"), nominal_yaw_rad=None,
                measurement_uncertainty="x", source="x", status="PARTIAL",
            )


class TestJsonlParseReportValidation(unittest.TestCase):
    def test_valid_report_accepted(self):
        report = JsonlParseReport(
            directory="d", expected_topic="rt/odommodestate", file_count=1, record_count=1,
            discarded_records=0, terminal_nul_files=0, duplicate_sequences=0,
            monotonic_inversions=0, schema_errors=0,
        )
        self.assertEqual(report.file_count, 1)

    def test_negative_count_rejected(self):
        with self.assertRaises(ValueError):
            JsonlParseReport(
                directory="d", expected_topic="rt/odommodestate", file_count=-1, record_count=0,
                discarded_records=0, terminal_nul_files=0, duplicate_sequences=0,
                monotonic_inversions=0, schema_errors=0,
            )


def _minimal_session(evidence_id, session_id, status="VERIFIED"):
    return PhysicalSessionEvidence(
        evidence_id=evidence_id, status=status, confidence="HIGH",
        session_id=session_id, session_type="R3C_MANUAL_PHYSICAL_ROUTE",
        boot_id=None, clean_shutdown=True,
        physical_movement_authority="HUMAN_OPERATOR_ONLY",
        streams=("rt/odommodestate",), phases=("UNMARKED",), provenance=(),
        source_files=("a.json",), source_sha256=("a" * 64,),
    )


def _minimal_time_domain(evidence_id, session_id):
    return SessionTimeDomain(
        evidence_id=evidence_id, status="UNRESOLVED", confidence="LOW",
        session_id=session_id, boot_id=None, message_stamp_status="ABSENT",
        receipt_monotonic_available=True, receipt_wall_utc_available=False,
        notebook_utc_estimate=None, rtt_seconds=None, uncertainty_seconds=None,
        mapping_status="UNRESOLVED", source_files=(), source_sha256=(),
    )


def _minimal_bundle_kwargs():
    channel_comparison = ChannelComparisonEvidence(
        evidence_id="cc1", status="PARTIAL", primary_channel="rt/odommodestate",
        secondary_channel="rt/lf/odommodestate", primary_sample_count=1,
        secondary_sample_count=1, authoritative_source_channel=None,
        primary_analysis_stream_candidate=True, arbitration_status="UNRESOLVED",
        observations=(), source_files=("a.json",), source_sha256=("a" * 64,),
    )
    imu_crosscheck = ImuCrosscheckEvidence(
        evidence_id="imu1", status="PARTIAL", session_id="sess1",
        stationary_bias_observed=True, dynamic_response_observed=True,
        sign_agreement="x", source_files=("a.json",), source_sha256=("a" * 64,),
    )
    reset_discontinuity = ResetDiscontinuityEvidence(
        evidence_id="reset1", status="VERIFIED", exact_reset_instant_status="UNRESOLVED",
        from_session_id="sess1", to_session_id="sess2", from_boot_id="boot-a",
        to_boot_id="boot-b", trajectory_concatenation_permitted=False,
        source_files=("a.json",), source_sha256=("a" * 64,),
    )
    lidar_extrinsic = LidarExtrinsicEvidence(
        evidence_id="lidar1", status="PARTIAL", source_frame_semantics_status="PARTIAL",
        child_frame_id_status="UNRESOLVED", candidate_transform_available=False,
        source_files=("a.json",), source_sha256=("a" * 64,),
    )
    covariance = CovarianceEvidence(
        evidence_id="cov1", status="PARTIAL", publication_model_ready=False,
        stationary_stats_ids=("dummy_stat",), dynamic_stats_ids=(),
        source_files=(), source_sha256=(),
    )
    return dict(
        generated_utc_injected="2026-07-21T00:00:00Z",
        sessions=(_minimal_session("s1", "sess1"), _minimal_session("s2", "sess2")),
        time_domains=(_minimal_time_domain("td1", "sess1"), _minimal_time_domain("td2", "sess2")),
        dynamic_segments=(), stationary_segments=(),
        axis_observations=(), yaw_observations=(),
        channel_comparison=channel_comparison, imu_crosscheck=imu_crosscheck,
        reset_discontinuity=reset_discontinuity, lidar_extrinsic=lidar_extrinsic,
        stationary_noise_statistics=(), dynamic_residual_statistics=(),
        covariance=covariance, claims=(),
    )


class TestBundleClaimEvidenceCoherence(unittest.TestCase):
    def test_valid_bundle_with_verified_claim_citing_verified_evidence(self):
        kwargs = _minimal_bundle_kwargs()
        kwargs["claims"] = (
            EvidenceClaim(claim_id="C1", r1_state="A", v19_state="B", r2p0_state="VERIFIED",
                          reason="x", evidence_ids=("s1",), confidence="HIGH"),
        )
        bundle = PhysicalEvidenceBundleR2(**kwargs)
        self.assertEqual(len(bundle.claims), 1)

    def test_claim_referencing_unknown_evidence_id_rejected(self):
        kwargs = _minimal_bundle_kwargs()
        kwargs["claims"] = (
            EvidenceClaim(claim_id="C1", r1_state="A", v19_state="B", r2p0_state="UNRESOLVED",
                          reason="x", evidence_ids=("no_such_evidence_id",), confidence="LOW"),
        )
        with self.assertRaises(ValueError):
            PhysicalEvidenceBundleR2(**kwargs)

    def test_verified_claim_backed_by_partial_evidence_rejected(self):
        # imu1's own status is PARTIAL; a VERIFIED claim must not cite it.
        kwargs = _minimal_bundle_kwargs()
        kwargs["claims"] = (
            EvidenceClaim(claim_id="C1", r1_state="A", v19_state="B", r2p0_state="VERIFIED",
                          reason="x", evidence_ids=("imu1",), confidence="HIGH"),
        )
        with self.assertRaises(ValueError):
            PhysicalEvidenceBundleR2(**kwargs)

    def test_session_missing_time_domain_rejected(self):
        kwargs = _minimal_bundle_kwargs()
        kwargs["time_domains"] = (_minimal_time_domain("td1", "sess1"),)  # sess2 missing
        with self.assertRaises(ValueError):
            PhysicalEvidenceBundleR2(**kwargs)


if __name__ == "__main__":
    unittest.main()
