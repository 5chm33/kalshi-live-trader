from __future__ import annotations

import unittest

from research.readiness import ProductionControls, ResearchEvidence, production_gate, research_gate


class ReadinessTests(unittest.TestCase):
    def research_evidence(self) -> ResearchEvidence:
        return ResearchEvidence(True, True, True, True, True, True, True, True, True)

    def production_controls(self) -> ProductionControls:
        return ProductionControls(True, True, True, True, True, True, True, True, True, True)

    def test_research_pass_only_creates_review_candidate(self) -> None:
        result = research_gate(self.research_evidence())
        self.assertTrue(result["eligible"])
        self.assertEqual("review_candidate", result["outcome"])
        self.assertFalse(result["live_orders_enabled"])

    def test_production_gate_requires_separate_review_and_never_enables_orders(self) -> None:
        blocked = production_gate(self.production_controls(), False)
        self.assertFalse(blocked["eligible"])
        self.assertIn("independent_research_review_not_accepted", blocked["failures"])
        approved = production_gate(self.production_controls(), True)
        self.assertTrue(approved["eligible"])
        self.assertEqual("production_review_candidate", approved["outcome"])
        self.assertFalse(approved["live_orders_enabled"])
        self.assertTrue(approved["human_approval_required"])


if __name__ == "__main__":
    unittest.main()
