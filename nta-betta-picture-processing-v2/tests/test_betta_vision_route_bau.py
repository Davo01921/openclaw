"""Offline safety tests for the canonical BAU vision route attestation."""

import importlib.util
import sys
import unittest
from pathlib import Path


def load(name, filename):
    spec = importlib.util.spec_from_file_location(
        name, Path(__file__).parents[1] / "scripts" / filename,
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


route_mod = load("betta_vision_route_bau_t", "betta_vision_route.py")
review_mod = load("vision_review_bau_t", "vision_review.py")


class VisionRouteBAUTests(unittest.TestCase):
    def route(self):
        return {
            "class": "STANDARD", "authority": "adaptive-model-router/v2.1",
            "requested_route": "openai/gpt-vision",
            "eligible_routes": ["openai/gpt-vision", "qwen/qwen-vision"],
            "execution_attested": False,
        }

    def test_attest_and_validate_exact_execution(self):
        evidence = route_mod.attest(self.route(), "qwen", "qwen-vision")
        self.assertTrue(evidence["execution_attested"])
        self.assertTrue(evidence["fallback_used"])
        self.assertIs(
            route_mod.validate_attestation(evidence, "qwen", "qwen-vision"),
            evidence,
        )

    def test_unknown_mismatch_override_and_inconsistent_fallback_rejected(self):
        valid = route_mod.attest(self.route(), "openai", "gpt-vision")
        cases = [
            ({**valid, "override": True}, "openai", "gpt-vision"),
            (valid, "unknown", "gpt-vision"),
            (valid, "openai", "other"),
            ({**valid, "fallback_used": True}, "openai", "gpt-vision"),
        ]
        for evidence, provider, model in cases:
            with self.subTest(evidence=evidence, provider=provider, model=model):
                with self.assertRaises(ValueError):
                    route_mod.validate_attestation(evidence, provider, model)

    def test_review_override_is_rejected_before_any_external_call(self):
        with self.assertRaisesRegex(RuntimeError, "overrides are disabled"):
            review_mod.run_review([], "catalogue", "fred", ["openai/other"])

    def test_failed_provider_attempt_usage_is_preserved(self):
        attempts = review_mod.failed_attempts({
            "attempts": [{
                "provider": "qwen", "model": "vision",
                "status": "FAILED", "error": {"message": "rate limited"},
                "usage": {"input_tokens": 4, "output_tokens": 1},
            }, {"provider": "openai", "model": "vision", "status": "SUCCESS"}],
        })
        self.assertEqual(len(attempts), 1)
        self.assertEqual(attempts[0]["error"], "rate limited")
        self.assertEqual(attempts[0]["usage"]["tokens_input"], 4)


if __name__ == "__main__":
    unittest.main()
