#!/usr/bin/env python3
"""Behavioral gates for the Scanpy automatic-review MVP."""

from __future__ import annotations

import json
import base64
import sys
import tempfile
import types
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
from scautopilot.review.visual import (  # noqa: E402
    VisualEvidenceError, validate_observations, verify_observations,
)
from system_one_adapter_runner import response_to_payload  # noqa: E402
from visual_vlm_runner import _run as run_visual_vlm  # noqa: E402


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
        commercial = backend["system_one_commercial"]
        self.assertIn("openai_compatible", (ROOT / "references/optimization.md").read_text())
        self.assertEqual(commercial["api"], "chat_completions")
        self.assertIsNone(commercial["base_url"])
        self.assertIsNone(commercial["api_key_env"])
        visual = optimization["scanpy_mvp"]["visual_review"]
        self.assertTrue(visual["enabled"])
        self.assertLessEqual(visual["max_images"], 4)
        self.assertEqual(visual["backend"]["mode"], "openai_compatible")
        self.assertEqual(visual["backend"]["base_url"], "https://api.deepseek.com")
        self.assertEqual(visual["backend"]["model"], "deepseek-flash")
        self.assertEqual(visual["backend"]["api_key_env"], "DEEPSEEK_API_KEY")

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


class VisualEvidenceTests(unittest.TestCase):
    def _observation(self, kind, present=True, labels=None):
        return {"observation_type": kind, "present": present, "confidence": 0.8,
                "figure_ids": ["leiden_umap"], "labels": labels or [],
                "description": "bounded visual observation"}

    def test_visual_schema_refuses_a_quality_score_or_free_form_type(self):
        value = self._observation("possible_overfragmentation")
        value["quality_score"] = 9
        with self.assertRaises(VisualEvidenceError):
            validate_observations([value])
        value = self._observation("looks_bad")
        with self.assertRaises(VisualEvidenceError):
            validate_observations([value])

    def test_visual_observations_are_confirmed_refuted_or_unverified(self):
        observations = validate_observations([
            self._observation("sample_specific_islands", True),
            self._observation("disconnected_same_label", True, ["AT2"]),
            self._observation("extreme_crowding", False),
            self._observation("bridge_patterns", True),
        ])
        metrics = {
            "same_sample_neighbor_enrichment": 0.30,
            "disconnected_label_components": {},
            "nearest_q01_to_median": 0.5,
            "duplicate_coordinate_fraction": 0.0,
            "n_umap_components": 1,
            "smallest_component_fraction": 1.0,
            "clusters_per_celltype": {"AT2": 1},
        }
        result = verify_observations(observations, metrics)
        self.assertEqual([item["verdict"] for item in result],
                         ["confirmed", "refuted", "confirmed", "unverified"])

    def test_overfragmentation_threshold_is_inclusive(self):
        observations = validate_observations([
            self._observation("possible_overfragmentation", True, ["Fibroblast"]),
        ])
        metrics = {"clusters_per_celltype": {"Fibroblast": 3}}
        result = verify_observations(
            observations,
            metrics,
            {"clusters_per_celltype": 3},
        )
        self.assertEqual(result[0]["verdict"], "confirmed")

    def test_visual_runner_sends_images_and_returns_only_observations(self):
        captured = {}

        class FakeResponse:
            choices = [types.SimpleNamespace(message=types.SimpleNamespace(content=json.dumps({
                "observations": [self._observation("possible_overfragmentation")]
            })))]

            def model_dump(self, mode=None):
                return {"id": "visual-1", "model": "vision-test",
                        "usage": {"prompt_tokens": 10, "completion_tokens": 5},
                        "choices": [{"finish_reason": "stop"}]}

        class FakeCompletions:
            def create(self, **kwargs):
                captured.update(kwargs)
                return FakeResponse()

        class FakeOpenAI:
            def __init__(self, **kwargs):
                captured["client"] = kwargs
                self.chat = types.SimpleNamespace(completions=FakeCompletions())

        png = base64.b64decode(
            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAusB9Y9Z2S8AAAAASUVORK5CYII=")
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "figure.png"
            path.write_bytes(png)
            payload = {"settings": {"base_url": "http://vision.invalid/v1", "model": "vision-test",
                                     "api_key_env": "VISUAL_TEST_KEY", "structured_outputs": False},
                       "request": {"dataset": {"n_cells": 10}, "figures": [{
                           "figure_id": "leiden_umap", "path": str(path), "mime_type": "image/png",
                           "sha256": "x", "width": 1, "height": 1}]}}
            with mock.patch.dict(sys.modules, {"openai": types.SimpleNamespace(OpenAI=FakeOpenAI)}), \
                    mock.patch.dict("os.environ", {"VISUAL_TEST_KEY": "secret"}, clear=False):
                result = run_visual_vlm(payload)
        user_content = captured["messages"][1]["content"]
        images = [item for item in user_content if item.get("type") == "image_url"]
        self.assertEqual(len(images), 1)
        self.assertTrue(images[0]["image_url"]["url"].startswith("data:image/png;base64,"))
        self.assertEqual(images[0]["image_url"]["detail"], "low")
        self.assertEqual(result["audit"]["response_id"], "visual-1")
        self.assertNotIn("secret", json.dumps(result))


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
