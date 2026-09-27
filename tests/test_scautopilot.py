#!/usr/bin/env python3
"""Tests for the scautopilot control plane: contracts, registry, equivalence.

These are the M0 deliverable's own tests. The registry tests are mostly about
*refusals* -- an unregistered parameter, an unevidenced entry, a cyclic artifact
graph -- because the registry's value is that it cannot be quietly bypassed.
The equivalence tests pin the distinction the plan turns on: a similarity
measure must never be able to sign off a refactor that changed behaviour.
"""

from __future__ import annotations

import json
import math
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scautopilot.contracts import (  # noqa: E402
    AnalysisStep,
    BudgetLedger,
    CandidateSpec,
    ComparisonProtocol,
    ConstraintSeverity,
    ConstraintSpec,
    ContractError,
    EvaluationRecord,
    MemoryObservation,
    MetricStatus,
    MultiFidelitySpec,
    ObservationStatus,
    ReferenceIndependence,
    ReferenceMode,
    ReferenceProvenance,
    ScientificState,
    SessionState,
)
from scautopilot.equivalence import (  # noqa: E402
    ArtifactClass,
    ArtifactNoise,
    Fingerprint,
    FingerprintError,
    NoiseFloor,
    ProtocolError,
    ScientificStability,
    StabilityCriteria,
    Verdict,
    WrapperEquivalence,
    measure_noise_floor,
    rank_reversal_pairs,
)
from scautopilot.equivalence import compare  # noqa: E402
from scautopilot.policy import CapabilityError, CapabilityPolicy  # noqa: E402
from scautopilot.provenance import (  # noqa: E402
    CacheIdentityError,
    ParameterRegistry,
    RegistryError,
    build_cache_key,
)


def registry_payload() -> dict:
    """A miniature registry shaped like the real one, for the refusal tests."""
    return {
        "schema_version": 1,
        "tools": {"scanpy": "0.8.0"},
        "artifacts": {
            "rna_counts": {"produced_by": "scanpy_qc", "kind": "integer"},
            "normalized": {"produced_by": "scanpy_normalize", "upstream": ["rna_counts"]},
            "hvg": {"produced_by": "scanpy_hvg", "upstream": ["normalized"]},
            "pca": {"produced_by": "scanpy_pca", "upstream": ["hvg"]},
            "neighbor_graph": {"produced_by": "scanpy_neighbors", "upstream": ["pca"]},
            "cluster_labels": {"produced_by": "scanpy_leiden", "upstream": ["neighbor_graph"]},
            "umap_coordinates": {"produced_by": "scanpy_umap", "upstream": ["neighbor_graph"]},
            "umap_figure": {"produced_by": "scanpy_umap_plot", "upstream": ["umap_coordinates"]},
            "filtered_cells": {"produced_by": "methscan_filter", "kind": "identity"},
            "allcools_features": {"produced_by": "allcools_features", "upstream": ["filtered_cells"]},
            "methylvi_inputs": {"produced_by": "methylvi_build", "upstream": ["allcools_features"]},
        },
        "parameters": {
            "scanpy.hvg.n_top_genes": {
                "stage": "scanpy_hvg",
                "affects": ["hvg"],
                "read": ["Scanpy/run_scanpy_notebook.py:1"],
                "tests": ["tests/test_core.py:1"],
                "default": 2000,
                "verified_against": "scanpy",
                "searchable": True,
            },
            "scanpy.leiden.resolution": {
                "stage": "scanpy_leiden",
                "affects": ["cluster_labels"],
                "read": ["Scanpy/run_scanpy_notebook.py:2"],
                "searchable": True,
                "tests": ["tests/test_scautopilot.py:1"],
            },
            "scanpy.umap.min_dist": {
                "stage": "scanpy_umap",
                "affects": ["umap_coordinates"],
                "read": ["Scanpy/run_scanpy_notebook.py:3"],
                "searchable": True,
                "tests": ["tests/test_scautopilot.py:1"],
            },
            "scanpy.umap.point_size": {
                "stage": "scanpy_umap_plot",
                "affects": ["umap_figure"],
                "read": ["Scanpy/run_scanpy_notebook.py:4"],
                "searchable": True,
                "tests": ["tests/test_scautopilot.py:1"],
            },
            "methscan.filter.min_coverage": {
                "stage": "methscan_filter",
                "affects": ["filtered_cells"],
                "read": ["Methscan/00_methscan_config.sh:19"],
                "searchable": True,
                "tests": ["tests/test_scautopilot.py:1"],
            },
        },
    }


class ContractTests(unittest.TestCase):
    def test_round_trip_preserves_values(self):
        step = AnalysisStep(
            tool_id="scanpy_pca",
            parameters={"n_comps": 30},
            environment="scanpy-core",
            inputs=["hvg.h5ad"],
            outputs=["pca.h5ad"],
            execution_identity="run-1",
            seed=0,
        )
        restored = AnalysisStep.from_dict(step.to_dict())
        self.assertEqual(restored, step)

    def test_unknown_field_is_refused(self):
        record = CandidateSpec(id="c1", route="scanpy", parameters={}, estimated_cost={})
        payload = record.to_dict()
        payload["surprise"] = 1
        with self.assertRaises(ContractError) as caught:
            CandidateSpec.from_dict(payload)
        self.assertIn("surprise", str(caught.exception))

    def test_future_schema_version_is_refused(self):
        record = CandidateSpec(id="c1", route="scanpy", parameters={}, estimated_cost={})
        payload = record.to_dict()
        payload["schema_version"] = 99
        with self.assertRaises(ContractError) as caught:
            CandidateSpec.from_dict(payload)
        self.assertIn("schema_version", str(caught.exception))

    def test_enum_values_are_validated(self):
        payload = EvaluationRecord(
            metric="ari", direction="maximize", status=MetricStatus.OK, value=1.0
        ).to_dict()
        payload["status"] = "probably_fine"
        with self.assertRaises(ContractError):
            EvaluationRecord.from_dict(payload)

    def test_ok_status_requires_a_value_and_others_forbid_one(self):
        with self.assertRaises(ContractError):
            EvaluationRecord(metric="ari", direction="maximize", status=MetricStatus.OK).validate()
        with self.assertRaises(ContractError):
            EvaluationRecord(
                metric="ari", direction="maximize", status=MetricStatus.UNAVAILABLE, value=0.5
            ).validate()
        EvaluationRecord(
            metric="ari", direction="maximize", status=MetricStatus.NOT_APPLICABLE
        ).validate()

    def test_cross_modal_reference_fields_are_all_or_nothing(self):
        with self.assertRaises(ContractError) as caught:
            EvaluationRecord(
                metric="knn_overlap",
                direction="maximize",
                status=MetricStatus.OK,
                value=0.7,
                reference_mode=ReferenceMode.RNA_REFERENCE,
            ).validate()
        self.assertIn("reference_provenance", str(caught.exception))
        # Provenance and independence stay separate axes: a reviewed label used
        # to derive the features is still circular evidence.
        EvaluationRecord(
            metric="knn_overlap",
            direction="maximize",
            status=MetricStatus.OK,
            value=0.7,
            reference_mode=ReferenceMode.RNA_REFERENCE,
            reference_provenance=ReferenceProvenance.REVIEWED,
            reference_independence=ReferenceIndependence.CIRCULAR,
        ).validate()

    def test_comparison_protocol_gates_comparability(self):
        base = ComparisonProtocol(
            protocol_id="p1",
            metrics={"ari": "maximize", "silhouette": "maximize"},
            cell_set="all-cells",
            feature_set="hvg-2000",
            fidelity="full",
        )
        same = ComparisonProtocol(
            protocol_id="p2",
            metrics={"ari": "maximize", "silhouette": "maximize"},
            cell_set="all-cells",
            feature_set="hvg-2000",
            fidelity="full",
        )
        self.assertTrue(base.compatible_with(same)[0])

        other_cells = ComparisonProtocol(
            protocol_id="p3",
            metrics={"ari": "maximize"},
            cell_set="filtered-cells",
            feature_set="hvg-2000",
            fidelity="full",
        )
        ok, reasons = base.compatible_with(other_cells)
        self.assertFalse(ok)
        self.assertTrue(any("cell_set" in reason for reason in reasons))

    def test_constraint_severity_maps_to_the_state_machine(self):
        integrity = ConstraintSpec(
            constraint_id="mc_le_cov",
            metric="mc_minus_cov",
            operator="<=",
            severity=ConstraintSeverity.INTEGRITY,
            threshold=0.0,
        )
        self.assertEqual(integrity.qualifying_state(), ScientificState.INVALID)
        protected = ConstraintSpec(
            constraint_id="rare_retention",
            metric="rare_retention",
            operator=">=",
            severity=ConstraintSeverity.PROTECTED,
            reference="baseline",
        )
        self.assertEqual(protected.qualifying_state(), ScientificState.REVIEW_REQUIRED)
        self.assertEqual(SessionState.BUDGET_BLOCKED.value, "budget_blocked")

    def test_constraint_needs_exactly_one_of_threshold_or_reference(self):
        with self.assertRaises(ContractError):
            ConstraintSpec(
                constraint_id="c", metric="m", operator="<=", severity=ConstraintSeverity.SCIENTIFIC
            ).validate()
        with self.assertRaises(ContractError):
            ConstraintSpec(
                constraint_id="c",
                metric="m",
                operator="<=",
                severity=ConstraintSeverity.SCIENTIFIC,
                threshold=1.0,
                reference="baseline",
            ).validate()

    def test_fidelity_ladder_must_be_monotonic_and_nested(self):
        # Epochs nest by construction, so ascending levels need no member lists.
        MultiFidelitySpec(dimension="epochs", levels=[{"resource": 50}, {"resource": 150}]).validate()
        scrambled = MultiFidelitySpec(
            dimension="cells", levels=[{"resource": 0.5, "name": "half"}, {"resource": 0.2, "name": "fifth"}]
        )
        with self.assertRaises(ContractError):
            scrambled.validate()

        nested = MultiFidelitySpec(
            dimension="cells",
            levels=[
                {"resource": 100, "name": "few", "members": ["a", "b"]},
                {"resource": 300, "name": "more", "members": ["a", "b", "c"]},
            ],
        )
        nested.validate()
        self.assertEqual(nested.validate_membership(), [])

        broken = MultiFidelitySpec(
            dimension="cells",
            levels=[
                {"resource": 100, "name": "few", "members": ["a", "b"]},
                {"resource": 300, "name": "more", "members": ["b", "c"]},
            ],
        )
        with self.assertRaises(ContractError) as caught:
            broken.validate_membership()
        self.assertIn("superset", str(caught.exception))

    def test_memory_observation_counts_must_match_their_evidence(self):
        with self.assertRaises(ContractError):
            MemoryObservation(
                observation="n_neighbors < 10 is unstable",
                scope_signature={"representation": "pca30"},
                support=["run-a", "run-b"],
                evidence_count=3,
            ).validate()
        MemoryObservation(
            observation="n_neighbors < 10 is unstable",
            scope_signature={"representation": "pca30"},
            support=["run-a"],
            evidence_count=1,
            status=ObservationStatus.NEEDS_REVALIDATION,
        ).validate()

    def test_ledger_rejects_negative_reservations(self):
        with self.assertRaises(ContractError):
            BudgetLedger(session_id="s1", reserved={"cpu_hours": -1.0}).validate()


class RegistryTests(unittest.TestCase):
    def setUp(self):
        self.registry = ParameterRegistry.from_mapping(registry_payload())
        self.registry.validate()

    def test_invalidation_follows_the_artifact_dag(self):
        reach = self.registry.affected_artifacts("scanpy.hvg.n_top_genes")
        # hvg -> pca -> neighbor_graph -> {cluster_labels, umap_coordinates}, and
        # the figure hangs off the coordinates.
        self.assertEqual(
            reach,
            frozenset(
                {"hvg", "pca", "neighbor_graph", "cluster_labels", "umap_coordinates", "umap_figure"}
            ),
        )
        # A plotting parameter reaches only its figure: coordinates and graph
        # are not invalidated by how the points are drawn.
        self.assertEqual(self.registry.affected_artifacts("scanpy.umap.point_size"), frozenset({"umap_figure"}))
        self.assertEqual(self.registry.affected_artifacts("scanpy.umap.min_dist"), frozenset({"umap_coordinates", "umap_figure"}))

    def test_filter_closure_crosses_into_the_other_routes(self):
        """The plan's cross-route claim, as a property of the graph."""
        reach = self.registry.affected_artifacts("methscan.filter.min_coverage")
        self.assertIn("allcools_features", reach)
        self.assertIn("methylvi_inputs", reach)

    def test_unregistered_parameters_are_frozen(self):
        with self.assertRaises(RegistryError) as caught:
            self.registry.assert_mutable(["scanpy.pca.n_comps"])
        self.assertIn("frozen", str(caught.exception))
        with self.assertRaises(RegistryError):
            self.registry.affected_artifacts("scanpy.pca.n_comps")

    def test_searchability_defaults_closed(self):
        payload = registry_payload()
        del payload["parameters"]["scanpy.leiden.resolution"]["searchable"]
        registry = ParameterRegistry.from_mapping(payload)
        self.assertFalse(registry.parameters["scanpy.leiden.resolution"].searchable)
        with self.assertRaises(RegistryError):
            registry.assert_mutable(["scanpy.leiden.resolution"])

    def test_an_entry_without_evidence_is_rejected(self):
        payload = registry_payload()
        del payload["parameters"]["scanpy.leiden.resolution"]["read"]
        registry = ParameterRegistry.from_mapping(payload)
        with self.assertRaises(RegistryError) as caught:
            registry.validate()
        self.assertIn("cites no read site", str(caught.exception))

    def test_searchable_entry_without_behavior_test_is_rejected(self):
        payload = registry_payload()
        del payload["parameters"]["scanpy.leiden.resolution"]["tests"]
        registry = ParameterRegistry.from_mapping(payload)
        with self.assertRaises(RegistryError) as caught:
            registry.validate()
        self.assertIn("behavioural test", str(caught.exception))

    def test_an_entry_affecting_nothing_is_rejected(self):
        payload = registry_payload()
        payload["parameters"]["scanpy.leiden.resolution"]["affects"] = []
        registry = ParameterRegistry.from_mapping(payload)
        with self.assertRaises(RegistryError) as caught:
            registry.validate()
        self.assertIn("affects nothing", str(caught.exception))

    def test_a_cyclic_artifact_graph_is_rejected(self):
        payload = registry_payload()
        payload["artifacts"]["rna_counts"]["upstream"] = ["cluster_labels"]
        registry = ParameterRegistry.from_mapping(payload)
        with self.assertRaises(RegistryError) as caught:
            registry.validate()
        self.assertIn("cycle", str(caught.exception))

    def test_dangling_artifact_reference_is_rejected(self):
        payload = registry_payload()
        payload["artifacts"]["pca"]["upstream"] = ["normalised"]
        registry = ParameterRegistry.from_mapping(payload)
        with self.assertRaises(RegistryError) as caught:
            registry.validate()
        self.assertIn("unknown upstream", str(caught.exception))

    def test_unknown_keys_are_rejected_at_load(self):
        payload = registry_payload()
        payload["parameters"]["scanpy.leiden.resolution"]["guessed"] = True
        with self.assertRaises(RegistryError) as caught:
            ParameterRegistry.from_mapping(payload)
        self.assertIn("guessed", str(caught.exception))

    def test_stale_entries_are_reported_not_inherited(self):
        self.assertEqual(self.registry.stale_entries({"scanpy": "0.8.0"}), {})
        stale = self.registry.stale_entries({"scanpy": "0.9.0"})
        self.assertIn("scanpy.hvg.n_top_genes", stale)
        self.assertIn("0.8.0", stale["scanpy.hvg.n_top_genes"])

    def test_invalidated_set_is_the_union_over_changed_parameters(self):
        changed = {"scanpy.hvg.n_top_genes": 3000, "scanpy.umap.point_size": 8}
        self.assertIn("pca", self.registry.invalidated_artifacts(changed))
        self.assertIn("umap_figure", self.registry.invalidated_artifacts(changed))


class RealRegistryTests(unittest.TestCase):
    """The shipped registry must load and answer the questions M0 poses of it."""

    @classmethod
    def setUpClass(cls):
        path = ROOT / "assets" / "project-template" / "config" / "parameters.yaml"
        if not path.is_file():
            raise unittest.SkipTest("shipped registry not present")
        cls.registry = ParameterRegistry.load(path)

    def test_every_entry_is_evidenced_and_closed(self):
        self.registry.validate()  # raises on unevidenced or dangling entries

    def test_evidence_paths_are_project_relative(self):
        """The file ships inside the generated project, so its evidence must
        resolve there; a skill-repo path would dangle for every user."""
        for entry in self.registry.parameters.values():
            for site in entry.read:
                self.assertFalse(
                    site.startswith(("assets/", "/")),
                    "%s cites %r, which does not resolve in a generated project"
                    % (entry.parameter_id, site),
                )
                self.assertIn(":", site, "%s cites %r without a line" % (entry.parameter_id, site))

    def test_every_cited_location_resolves_and_is_in_range(self):
        """Resolve each citation against the template and check the line exists.

        This is the check that keeps the registry honest: an entry is only
        evidence if the file is there and the line is inside it. A plausible
        path that does not resolve is a claim, not evidence.
        """
        template = ROOT / "assets" / "project-template"
        for entry in self.registry.parameters.values():
            for site in entry.read:
                path_text, _, line_text = site.rpartition(":")
                target = template / path_text
                self.assertTrue(target.is_file(), "%s cites missing file %s" % (entry.parameter_id, site))
                line = int(line_text)
                width = len(target.read_text(encoding="utf-8").splitlines())
                self.assertLessEqual(
                    line, width, "%s cites %s but the file has %d lines" % (entry.parameter_id, site, width)
                )

    def test_the_three_route_closure_crosses_where_the_plan_says_it_does(self):
        reach = self.registry.affected_artifacts("methscan.filter.min_sites")
        self.assertIn("allcools.h5ad", reach)
        self.assertIn("methylvi.input", reach)

    def test_a_plotting_parameter_does_not_invalidate_coordinates(self):
        reach = self.registry.affected_artifacts("scanpy.sample_palette")
        self.assertNotIn("scanpy.umap_coordinates", reach)
        self.assertNotIn("scanpy.neighbor_graph", reach)

    def test_cluster_change_does_not_reach_umap_coordinates(self):
        """The plan's layering claim, as a graph property rather than a promise."""
        reach = self.registry.affected_artifacts("scanpy.leiden.resolution")
        self.assertIn("scanpy.markers", reach)
        self.assertIn("scanpy.figures_cluster", reach)
        self.assertNotIn("scanpy.umap_coordinates", reach)
        self.assertNotIn("scanpy.pca", reach)

    def test_gaps_the_audit_found_are_recorded_as_frozen_with_reasons(self):
        for parameter_id in (
            "scanpy.neighbors.metric",
            "methylvi.train.learning_rate",
            "methylvi.model.n_latent",
        ):
            self.assertFalse(self.registry.is_registered(parameter_id))
            self.assertTrue(self.registry.frozen_reason(parameter_id))
            with self.assertRaises(RegistryError):
                self.registry.assert_mutable([parameter_id])

    def test_qc_is_traced_but_closed(self):
        entry = self.registry.parameters["scanpy.qc.min_genes"]
        self.assertFalse(entry.searchable)
        self.assertTrue(entry.read)
        with self.assertRaises(RegistryError) as caught:
            self.registry.assert_mutable(["scanpy.qc.min_genes"])
        self.assertIn("closed", str(caught.exception))

    def test_only_the_scanpy_mvp_axes_are_open_after_behavior_coverage(self):
        self.assertEqual(
            {entry.parameter_id for entry in self.registry.parameters.values() if entry.searchable},
            {
                "scanpy.pca.n_comps",
                "scanpy.neighbors.n_pcs",
                "scanpy.neighbors.n_neighbors",
                "scanpy.leiden.resolution",
                "scanpy.umap.min_dist",
            },
        )

    def test_coupled_parameters_are_recorded_as_coupled(self):
        """One canonical min_cells parameter invalidates both consumers."""
        entry = self.registry.parameters["methscan.min_cells"]
        self.assertEqual(set(entry.affects), {"methscan.vmr_bed", "methscan.dmr_pairwise"})

    def test_cross_route_coupling_is_recorded(self):
        entry = self.registry.parameters["methylvi.seed"]
        self.assertIn("methscan.scanpy_h5ad", entry.affects)
        self.assertIn("allcools.h5ad", entry.affects)

    def test_cluster_and_annotation_figures_depend_on_umap_coordinates(self):
        self.assertIn(
            "scanpy.figures_cluster",
            self.registry.affected_artifacts("scanpy.umap.min_dist"),
        )
        self.assertIn(
            "scanpy.figures_annotation",
            self.registry.affected_artifacts("scanpy.umap.min_dist"),
        )

    def test_hypodmr_cutoffs_reach_pooled_dmr_route(self):
        self.assertIn(
            "pooled_dmr.bed",
            self.registry.affected_artifacts("methscan.hypodmr.raw_p"),
        )


class CapabilityPolicyTests(unittest.TestCase):
    def setUp(self):
        self.policy = CapabilityPolicy.load_default()
        self.registry = ParameterRegistry.from_mapping(registry_payload())
        self.registry.validate()

    def test_effective_space_is_the_three_way_intersection(self):
        requested = {"scanpy.hvg.n_top_genes"}
        self.assertEqual(self.policy.effective_search_space(self.registry, requested), requested)

    def test_rendering_and_cell_set_changes_are_not_silent_search_axes(self):
        for parameter_id in ("scanpy.sample_palette", "methscan.filter.min_sites"):
            with self.assertRaises(CapabilityError):
                self.policy.effective_search_space(self.registry, [parameter_id])


class CacheIdentityTests(unittest.TestCase):
    def identity(self, **overrides):
        values = {
            "tool_implementation_digest": "code-a",
            "effective_parameters": {"n_neighbors": 15},
            "upstream_artifact_checksums": ["input-a", "input-b"],
            "environment_fingerprint": "env-a",
            "seed": 0,
            "registry_version": "registry-a",
            "contract_schema_version": 1,
        }
        values.update(overrides)
        return build_cache_key(**values)

    def test_every_effective_input_changes_the_key(self):
        baseline = self.identity()
        self.assertNotEqual(baseline, self.identity(seed=1))
        self.assertNotEqual(baseline, self.identity(environment_fingerprint="env-b"))
        self.assertNotEqual(baseline, self.identity(effective_parameters={"n_neighbors": 30}))
        self.assertNotEqual(baseline, self.identity(upstream_artifact_checksums=["input-b", "input-a"]))

    def test_missing_identity_information_fails_closed(self):
        with self.assertRaises(CacheIdentityError):
            self.identity(tool_implementation_digest="")


class BaselineRecordTests(unittest.TestCase):
    """The recorded noise floor is a measurement, and it must stay one.

    The Scanpy baseline reproduced bit-for-bit across two independent runs, so
    every artifact is deterministic and the equivalence gate demands exact
    reproduction. That is a strong claim resting on two runs; these tests keep
    it honest rather than letting a future edit quietly widen the tolerances it
    was measured to produce.
    """

    @classmethod
    def setUpClass(cls):
        path = ROOT / "baselines" / "scanpy-ipf-20260920.json"
        if not path.is_file():
            raise unittest.SkipTest("baseline record not present")
        cls.record = json.loads(path.read_text(encoding="utf-8"))

    def test_record_declares_its_scope_and_its_limits(self):
        scope = self.record["scope"]
        for key in ("machine", "python", "package_versions", "data", "analysis_signature", "not_claimed"):
            self.assertIn(key, scope)
        self.assertIn("跨环境", scope["not_claimed"])

    def test_measurement_used_at_least_two_runs(self):
        self.assertGreaterEqual(self.record["noise_floor"]["observations"], 2)
        self.assertEqual(
            len(self.record["baseline_runs"]), self.record["noise_floor"]["observations"]
        )

    def test_every_measured_artifact_came_back_deterministic(self):
        artifacts = self.record["noise_floor"]["artifacts"]
        self.assertTrue(artifacts, "a noise floor with no artifacts measures nothing")
        for artifact_id, noise in artifacts.items():
            self.assertTrue(noise["deterministic"], f"{artifact_id} was not deterministic")
            self.assertEqual(noise["max_abs_delta"], 0.0, artifact_id)
            self.assertEqual(noise["max_rel_delta"], 0.0, artifact_id)

    def test_the_record_loaded_into_a_usable_gate(self):
        floor = NoiseFloor(
            observations=self.record["noise_floor"]["observations"],
            artifacts={
                artifact_id: ArtifactNoise(
                    artifact_id=artifact_id,
                    artifact_class=ArtifactClass(noise["artifact_class"]),
                    observations=noise["observations"],
                    deterministic=noise["deterministic"],
                    max_abs_delta=noise["max_abs_delta"],
                    max_rel_delta=noise["max_rel_delta"],
                )
                for artifact_id, noise in self.record["noise_floor"]["artifacts"].items()
            },
            label=self.record["label"],
        )
        gate = WrapperEquivalence(floor)
        for artifact_id, noise in floor.artifacts.items():
            self.assertEqual(noise.tolerance(), (0.0, 0.0), artifact_id)

        identical = Fingerprint(
            "pca", ArtifactClass.FLOAT, {"values": [1.0, 2.0, 3.0]}
        )
        drifted = Fingerprint(
            "pca", ArtifactClass.FLOAT, {"values": [1.0, 2.0, 3.0 + 1e-12]}
        )
        self.assertTrue(gate.compare({"pca": identical}, {"pca": identical}).passed)
        # A deterministic baseline tolerates nothing, however small the drift.
        self.assertFalse(gate.compare({"pca": identical}, {"pca": drifted}).passed)


class ComparisonTests(unittest.TestCase):
    def test_canonical_labels_treat_relabelling_as_identity(self):
        """The exact case from the plan's review: same partition, new numbers."""
        old = [0, 0, 1, 1, 2]
        new = [2, 2, 0, 0, 1]
        self.assertEqual(compare.canonical_labels(old), compare.canonical_labels(new))
        self.assertTrue(compare.labels_identical(old, new))

    def test_canonical_labels_detect_a_real_change(self):
        old = [0, 0, 1, 1, 2]
        moved = [0, 1, 0, 1, 2]
        self.assertFalse(compare.labels_identical(old, moved))

    def test_adjusted_rand_index_bounds(self):
        self.assertAlmostEqual(compare.adjusted_rand_index([0, 0, 1, 1], [1, 1, 0, 0]), 1.0)
        independent = compare.adjusted_rand_index(
            [0, 0, 0, 0, 1, 1, 1, 1], [0, 1, 0, 1, 0, 1, 0, 1]
        )
        self.assertLess(abs(independent), 0.2)

    def test_spearman_handles_ties_and_constants(self):
        self.assertAlmostEqual(compare.spearman([1, 2, 3], [1, 2, 3]), 1.0)
        self.assertAlmostEqual(compare.spearman([1, 2, 3], [3, 2, 1]), -1.0)
        self.assertAlmostEqual(compare.spearman([1, 1, 1], [1, 2, 3]), 1.0)
        self.assertAlmostEqual(compare.spearman([1, 2, 2, 3], [1, 2, 2, 4]), 1.0)

    def test_jaccard(self):
        self.assertEqual(compare.jaccard([], []), 1.0)
        self.assertEqual(compare.jaccard([1, 2, 3], [1, 2]), 2 / 3)
        self.assertEqual(compare.jaccard(["a"], ["b"]), 0.0)

    def test_allclose_reports_the_worst_deviation(self):
        ok, worst_abs, worst_rel = compare.allclose([1.0, 2.0], [1.0, 2.5], rtol=0.0, atol=1.0)
        self.assertTrue(ok)
        self.assertAlmostEqual(worst_abs, 0.5)
        self.assertAlmostEqual(worst_rel, 0.5 / 2.5)
        ok, _, _ = compare.allclose([1.0], [1.0 + 1e-3], rtol=0.0, atol=1e-6)
        self.assertFalse(ok)

    def test_distance_correlation_is_invariant_to_rotation(self):
        """PCA and latent spaces are defined up to rotation; a coordinate-wise
        comparison would call two identical geometries different."""
        points = [[0.0, 0.0], [1.0, 0.0], [0.0, 2.0], [3.0, 1.0]]
        rotated = [[-y, x] for x, y in points]
        self.assertAlmostEqual(compare.pairwise_distance_correlation(points, rotated), 1.0, places=9)
        translated = [[x + 100.0, y - 5.0] for x, y in points]
        self.assertAlmostEqual(compare.pairwise_distance_correlation(points, translated), 1.0, places=9)

    def test_edge_overlap_ignores_direction(self):
        self.assertEqual(compare.edge_overlap([("a", "b")], [("b", "a")]), 1.0)


class FingerprintTests(unittest.TestCase):
    def test_exact_classes_reject_fractional_values(self):
        with self.assertRaises(FingerprintError) as caught:
            Fingerprint(
                artifact_id="counts",
                artifact_class=ArtifactClass.INTEGER,
                payload={"values": [1.0, 1.5]},
            )
        self.assertIn("must hold integers", str(caught.exception))

    def test_payload_cannot_be_both_digest_and_values(self):
        with self.assertRaises(FingerprintError):
            Fingerprint(
                artifact_id="x",
                artifact_class=ArtifactClass.FLOAT,
                payload={"digest": "abc", "values": [1.0]},
            )

    def test_noise_floor_needs_two_runs(self):
        with self.assertRaises(FingerprintError):
            measure_noise_floor([{}])

    def test_noise_floor_detects_deterministic_and_drifting_artifacts(self):
        def run(latent_shift: float):
            return {
                "cluster_labels": Fingerprint(
                    artifact_id="cluster_labels",
                    artifact_class=ArtifactClass.DISCRETE,
                    payload={"labels": [0, 0, 1, 1, 2]},
                ),
                "latent": Fingerprint(
                    artifact_id="latent",
                    artifact_class=ArtifactClass.FLOAT,
                    payload={"values": [1.0 + latent_shift, 2.0, 3.0]},
                ),
            }

        floor = measure_noise_floor([run(0.0), run(1e-6)], label="baseline")
        self.assertTrue(floor.get("cluster_labels").deterministic)
        self.assertFalse(floor.get("latent").deterministic)
        rtol, atol = floor.get("latent").tolerance(safety_factor=10.0)
        self.assertGreater(atol, 0.0)
        self.assertGreater(rtol, 0.0)
        self.assertEqual(floor.get("cluster_labels").tolerance(), (0.0, 0.0))

    def test_set_valued_noise_floor_uses_overlap(self):
        def run(members):
            return {
                "hvg": Fingerprint(
                    artifact_id="hvg",
                    artifact_class=ArtifactClass.SET,
                    payload={"members": members},
                )
            }

        floor = measure_noise_floor([run(["a", "b"]), run(["a", "b"])])
        self.assertEqual(floor.get("hvg").required_overlap(), 1.0)
        drifting = measure_noise_floor([run(["a", "b"]), run(["a", "b", "c"])])
        self.assertAlmostEqual(drifting.get("hvg").required_overlap(), 2 / 3)


class WrapperEquivalenceTests(unittest.TestCase):
    def _floor(self, label="baseline"):
        def run(shift=0.0):
            return {
                "counts": Fingerprint(
                    artifact_id="counts",
                    artifact_class=ArtifactClass.INTEGER,
                    payload={"values": [1, 2, 3]},
                ),
                "cluster_labels": Fingerprint(
                    artifact_id="cluster_labels",
                    artifact_class=ArtifactClass.DISCRETE,
                    payload={"labels": [0, 0, 1, 1, 2]},
                ),
                "latent": Fingerprint(
                    artifact_id="latent",
                    artifact_class=ArtifactClass.FLOAT,
                    payload={"values": [1.0 + shift, 2.0, 3.0]},
                ),
            }

        return measure_noise_floor([run(), run(1e-9)], label=label)

    def test_relabelled_clusters_are_equivalent(self):
        floor = self._floor()
        baseline = {
            "cluster_labels": Fingerprint(
                artifact_id="cluster_labels",
                artifact_class=ArtifactClass.DISCRETE,
                payload={"labels": [0, 0, 1, 1, 2]},
            )
        }
        candidate = {
            "cluster_labels": Fingerprint(
                artifact_id="cluster_labels",
                artifact_class=ArtifactClass.DISCRETE,
                payload={"labels": [2, 2, 0, 0, 1]},
            )
        }
        self.assertTrue(WrapperEquivalence(floor).compare(baseline, candidate).passed)

    def test_one_moved_cell_fails_even_though_ari_is_high(self):
        """The point of the whole split: ARI ~= 0.99 still means a cell moved."""
        floor = self._floor()
        before = [0] * 50 + [1] * 50
        after = list(before)
        after[0] = 1
        self.assertGreater(compare.adjusted_rand_index(before, after), 0.95)

        report = WrapperEquivalence(floor).compare(
            {"cluster_labels": Fingerprint("cluster_labels", ArtifactClass.DISCRETE, {"labels": before})},
            {"cluster_labels": Fingerprint("cluster_labels", ArtifactClass.DISCRETE, {"labels": after})},
        )
        self.assertFalse(report.passed)
        self.assertEqual(report.verdict, Verdict.DIFFERED)

        # The same change judged by the stability protocol is a different verdict
        # on purpose -- that protocol is allowed to call it stable.
        stable = ScientificStability(StabilityCriteria(ari=0.90)).evaluate(
            "ari",
            Fingerprint("cluster_labels", ArtifactClass.DISCRETE, {"labels": before}),
            Fingerprint("cluster_labels", ArtifactClass.DISCRETE, {"labels": after}),
        )
        self.assertTrue(stable.stable)

    def test_float_within_the_measured_floor_passes(self):
        floor = self._floor()
        report = WrapperEquivalence(floor).compare(
            {"latent": Fingerprint("latent", ArtifactClass.FLOAT, {"values": [1.0, 2.0, 3.0]})},
            {"latent": Fingerprint("latent", ArtifactClass.FLOAT, {"values": [1.0 + 1e-11, 2.0, 3.0]})},
        )
        self.assertTrue(report.passed)

    def test_float_beyond_the_floor_fails(self):
        floor = self._floor()
        report = WrapperEquivalence(floor).compare(
            {"latent": Fingerprint("latent", ArtifactClass.FLOAT, {"values": [1.0, 2.0, 3.0]})},
            {"latent": Fingerprint("latent", ArtifactClass.FLOAT, {"values": [1.5, 2.0, 3.0]})},
        )
        self.assertFalse(report.passed)

    def test_deterministic_artifact_tolerates_nothing(self):
        floor = self._floor()
        report = WrapperEquivalence(floor).compare(
            {"counts": Fingerprint("counts", ArtifactClass.INTEGER, {"values": [1, 2, 3]})},
            {"counts": Fingerprint("counts", ArtifactClass.INTEGER, {"values": [1, 2, 4]})},
        )
        self.assertFalse(report.passed)

    def test_a_missing_artifact_is_not_a_pass(self):
        floor = self._floor()
        report = WrapperEquivalence(floor).compare(
            {},
            {"counts": Fingerprint("counts", ArtifactClass.INTEGER, {"values": [1, 2, 3]})},
        )
        self.assertFalse(report.passed)
        self.assertEqual(report.verdict, Verdict.NOT_COMPARABLE)

    def test_changed_sampling_is_not_comparable(self):
        floor = self._floor()
        report = WrapperEquivalence(floor).compare(
            {"latent": Fingerprint("latent", ArtifactClass.FLOAT, {"values": [1.0]}, sampling="first-100")},
            {"latent": Fingerprint("latent", ArtifactClass.FLOAT, {"values": [1.0]}, sampling="random-100")},
        )
        self.assertEqual(report.verdict, Verdict.NOT_COMPARABLE)
        self.assertIn("sampling", report.blockers[0].detail)

    def test_equivalence_refuses_a_stability_table(self):
        with self.assertRaises(ProtocolError) as caught:
            WrapperEquivalence(StabilityCriteria())
        self.assertIn("NoiseFloor", str(caught.exception))

    def test_stability_refuses_a_noise_floor(self):
        with self.assertRaises(ProtocolError) as caught:
            ScientificStability(self._floor())
        self.assertIn("StabilityCriteria", str(caught.exception))

    def test_rank_reversals_are_reported_as_pairs(self):
        low = {"a": 0.9, "b": 0.5, "c": 0.1}
        high = {"a": 0.2, "b": 0.5, "c": 0.8}
        reversals = rank_reversal_pairs(low, high)
        self.assertIn(("a", "c"), [tuple(sorted(pair)) for pair in reversals] or reversals)
        self.assertEqual(rank_reversal_pairs(low, low), [])

    def test_report_serialises(self):
        report = WrapperEquivalence(self._floor()).compare(
            {"latent": Fingerprint("latent", ArtifactClass.FLOAT, {"values": [1.0]})},
            {"latent": Fingerprint("latent", ArtifactClass.FLOAT, {"values": [1.0]})},
        )
        payload = report.to_dict()
        self.assertTrue(payload["passed"])
        self.assertEqual(payload["artifacts"][0]["verdict"], "equivalent")


if __name__ == "__main__":
    unittest.main()
