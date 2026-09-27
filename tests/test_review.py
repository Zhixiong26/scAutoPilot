#!/usr/bin/env python3
"""Behavioral gates for the Scanpy automatic-review MVP."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from unittest import mock
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from apply_scanpy_round import ApplyError, apply  # noqa: E402
from scautopilot.policy import CapabilityPolicy  # noqa: E402
from scautopilot.provenance import ParameterRegistry  # noqa: E402
from scautopilot.review.backend import (  # noqa: E402
    BackendError, rule_fallback, system_one_adapter_backend, validate_judgments,
)
from scautopilot.review.controller import PARAMETER_IDS  # noqa: E402
from scautopilot.review.primitives import Choice, Noul, PrimitiveError, Score  # noqa: E402
from system_one_adapter_runner import response_to_payload  # noqa: E402


class PrimitiveTests(unittest.TestCase):
    def test_typed_primitives_are_bounded(self):
        self.assertAlmostEqual(Noul("a", "?", 0.7, "test").to_dict()["probability_no"], 0.3)
        self.assertEqual(Choice("p", "?", {"x": "x", "y": "y"},
                                {"x": 0.2, "y": 0.8}, "test").to_dict()["selected"], "y")
        self.assertEqual(Score("q", "?", ["bad", "good"],
                              {"bad": 0.25, "good": 0.75}, "test").to_dict()["expected_score"], 0.75)
        with self.assertRaises(PrimitiveError):
            Noul("a", "?", 1.1, "test").to_dict()

    def test_backend_refuses_free_form_or_incomplete_actions(self):
        with self.assertRaises(BackendError):
            validate_judgments({"accept_probability": 0.5, "python": "scanpy()"}, "test")

    def test_system_one_timeout_becomes_a_fallback_eligible_backend_error(self):
        settings = {"python": sys.executable, "base_url": "http://127.0.0.1:8000/v1",
                    "model": "local-test"}
        with mock.patch("scautopilot.review.backend.subprocess.run",
                        side_effect=subprocess.TimeoutExpired("runner", 1)):
            with self.assertRaises(BackendError) as caught:
                system_one_adapter_backend(ROOT, "system_one_local", settings, {}, timeout=1)
        self.assertIn("could not complete", str(caught.exception))


class SearchSpaceTests(unittest.TestCase):
    def test_four_scanpy_mvp_parameters_are_authorized(self):
        registry = ParameterRegistry.load(ROOT / "assets/project-template/config/parameters.yaml")
        policy = CapabilityPolicy.load_default()
        concrete = [parameter for group in PARAMETER_IDS.values() for parameter in group]
        self.assertEqual(set(PARAMETER_IDS), {"n_pcs", "n_neighbors", "resolution", "min_dist"})
        self.assertEqual(policy.effective_search_space(registry, concrete), frozenset(concrete))
        optimization = json.loads((ROOT / "assets/project-template/config/optimization.yaml").read_text())
        grids = optimization["scanpy_mvp"]["parameter_grids"]
        self.assertEqual(grids["n_pcs"], [20, 30, 40, 50, 60])
        self.assertEqual(grids["n_neighbors"], [10, 15, 20, 30, 40, 50])
        self.assertEqual(grids["resolution"], [0.4, 0.6, 0.8, 1.0, 1.2])
        self.assertEqual(grids["min_dist"], [0.1, 0.3, 0.5, 0.7, 0.9])
        backend = optimization["scanpy_mvp"]["decision_backend"]
        self.assertEqual(backend["mode"], "system_one_local")
        self.assertEqual(backend["system_one_local"]["api"], "chat_completions")
        self.assertFalse(backend["system_one_local"]["structured_outputs"])

    def test_fallback_is_explicitly_not_jev(self):
        state = {"embedding": {"trustworthiness": 0.5, "knn_preservation": 0.5},
                 "clustering": {"silhouette": 0.1},
                 "biology": {"celltype_asw": 0.9, "independent": False},
                 "batch": {"ilisi": 0.5}}
        result = rule_fallback(state)
        self.assertEqual(result["backend"], "uncalibrated_rule_fallback_v0")
        self.assertNotEqual(result["backend"], "jev")

    def test_official_adapter_response_is_mapped_and_audited(self):
        class FakeResponse:
            def model_dump(self, mode=None):
                self.mode = mode
                return {
                    "answers": {
                        "accept": {"noul": 0.8},
                        "parameter": {"probabilities": {
                            "n_pcs": 0.1, "n_neighbors": 0.1, "resolution": 0.6,
                            "min_dist": 0.1, "none": 0.05, "escalate": 0.05}},
                        "direction": {"probabilities": {
                            "increase": 0.7, "decrease": 0.2, "keep": 0.1}},
                        "quality": {"probabilities": {
                            "0": 0.0, "1": 0.1, "2": 0.2, "3": 0.6, "4": 0.1}},
                        "escalate": {"noul": 0.05},
                    },
                    "usage": {"input_tokens_total": 100, "output_tokens_total": 20,
                              "latency": 0.5, "n_retries": 0,
                              "n_retries_malformed_structure": 0},
                    "debug": {"llm_attempts": [{"model": "local-test"}]},
                }

        result = response_to_payload(FakeResponse(), "system_one_local",
                                     {"model": "local-test", "api_key": "secret"})
        validated = validate_judgments(result["judgments"], "system_one_local")
        self.assertEqual(validated["backend"], "system_one_local")
        self.assertEqual(validated["parameter"]["resolution"], 0.6)
        self.assertEqual(validated["quality"]["good"], 0.6)
        self.assertEqual(result["audit"]["usage"]["input_tokens_total"], 100)
        self.assertEqual(len(result["audit"]["response"]["debug"]["llm_attempts"]), 1)
        self.assertNotIn("api_key", result["audit"]["settings"])


class ApplyTests(unittest.TestCase):
    def test_apply_changes_exactly_one_logical_axis_and_is_single_use(self):
        cases = {"n_pcs": 30, "n_neighbors": 20, "resolution": 1.0, "min_dist": 0.3}
        current = {"n_pcs": 20, "n_neighbors": 15, "resolution": 0.8, "min_dist": 0.5}
        import apply_scanpy_round
        for parameter, new_value in cases.items():
            with self.subTest(parameter=parameter), tempfile.TemporaryDirectory() as temp:
                project = Path(temp)
                round_root = project / ".workflow/optimization/s/round_000"
                round_root.mkdir(parents=True)
                config = {"analysis": {"scanpy": {"pca": {"n_comps": 30},
                          "neighbors": {"n_pcs": 20, "n_neighbors": 15},
                          "leiden": {"resolution": 0.8}, "umap": {"min_dist": 0.5},
                          "notebook": {}}}}
                (project / "config").mkdir()
                (project / "config/analysis.yaml").write_text(json.dumps(config))
                next_parameters = dict(current)
                next_parameters[parameter] = new_value
                plan = {"schema_version": 1, "frozen": True, "status": "next_candidate",
                        "current_parameters": current, "next_parameters": next_parameters,
                        "parameter_diff": {"parameter": parameter, "old_value": current[parameter],
                                           "new_value": new_value}}
                plan["plan_digest"] = apply_scanpy_round.digest(plan)
                (round_root / "round_plan.json").write_text(json.dumps(plan))
                apply(project, "s", "round_000", "candidate-001")
                updated = json.loads((project / "config/analysis.yaml").read_text())["analysis"]["scanpy"]
                observed = {"n_pcs": updated["neighbors"]["n_pcs"],
                            "n_neighbors": updated["neighbors"]["n_neighbors"],
                            "resolution": updated["leiden"]["resolution"],
                            "min_dist": updated["umap"]["min_dist"]}
                self.assertEqual(observed, next_parameters)
                self.assertEqual(updated["pca"]["n_comps"], 30)
                with self.assertRaises(ApplyError):
                    apply(project, "s", "round_000", "candidate-002")


if __name__ == "__main__":
    unittest.main()
