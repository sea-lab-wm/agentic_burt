import unittest

from pydantic import ValidationError

from llm_schema import ExtractionSchema
from state import CandidateMapping, Slot, SlotStatus


class StateModelTests(unittest.TestCase):
    def test_unknown_slot_accepts_empty_candidates(self):
        slot = Slot(status=SlotStatus.unknown, candidates=[])
        self.assertEqual(slot.status, SlotStatus.unknown)
        self.assertEqual(slot.candidates, [])

    def test_inferred_slot_requires_one_candidate(self):
        slot = Slot(
            status=SlotStatus.inferred,
            candidates=[CandidateMapping(value="screen_hash", evidence="quoted text")],
        )
        self.assertEqual(len(slot.candidates), 1)

    def test_confirmed_slot_requires_one_candidate(self):
        slot = Slot(
            status=SlotStatus.confirmed,
            candidates=[CandidateMapping(value="screen_hash", evidence="quoted text")],
        )
        self.assertEqual(len(slot.candidates), 1)

    def test_ambiguous_slot_accepts_two_candidates(self):
        slot = Slot(
            status=SlotStatus.ambiguous,
            candidates=[
                CandidateMapping(value="screen_a", evidence="quote a"),
                CandidateMapping(value="screen_b", evidence="quote b"),
            ],
        )
        self.assertEqual(len(slot.candidates), 2)

    def test_ambiguous_slot_accepts_three_candidates(self):
        slot = Slot(
            status=SlotStatus.ambiguous,
            candidates=[
                CandidateMapping(value="screen_a", evidence="quote a"),
                CandidateMapping(value="screen_b", evidence="quote b"),
                CandidateMapping(value="screen_c", evidence="quote c"),
            ],
        )
        self.assertEqual(len(slot.candidates), 3)

    def test_unknown_rejects_candidates(self):
        with self.assertRaises(ValidationError):
            Slot(
                status=SlotStatus.unknown,
                candidates=[CandidateMapping(value="screen_a", evidence="quote a")],
            )

    def test_inferred_rejects_zero_candidates(self):
        with self.assertRaises(ValidationError):
            Slot(status=SlotStatus.inferred, candidates=[])

    def test_confirmed_rejects_multiple_candidates(self):
        with self.assertRaises(ValidationError):
            Slot(
                status=SlotStatus.confirmed,
                candidates=[
                    CandidateMapping(value="a", evidence="1"),
                    CandidateMapping(value="b", evidence="2"),
                ],
            )

    def test_ambiguous_rejects_one_candidate(self):
        with self.assertRaises(ValidationError):
            Slot(
                status=SlotStatus.ambiguous,
                candidates=[CandidateMapping(value="screen_a", evidence="quote a")],
            )

    def test_ambiguous_rejects_more_than_three_candidates(self):
        with self.assertRaises(ValidationError):
            Slot(
                status=SlotStatus.ambiguous,
                candidates=[
                    CandidateMapping(value="a", evidence="1"),
                    CandidateMapping(value="b", evidence="2"),
                    CandidateMapping(value="c", evidence="3"),
                    CandidateMapping(value="d", evidence="4"),
                ],
            )

    def test_extraction_schema_parses_candidate_based_slots(self):
        extraction = ExtractionSchema.model_validate(
            {
                "triggering_screen_reference": {
                    "status": "confirmed",
                    "candidates": [
                        {
                            "value": "screen_hash",
                            "evidence": "The user directly named the screen.",
                        }
                    ],
                },
                "buggy_behavior": {
                    "status": "ambiguous",
                    "candidates": [
                        {"value": "freeze", "evidence": "quote a"},
                        {"value": "crash", "evidence": "quote b"},
                    ],
                },
                "correct_behavior": {"status": "unknown", "candidates": []},
            }
        )

        self.assertEqual(extraction.triggering_screen_reference.status, SlotStatus.confirmed)
        self.assertEqual(extraction.buggy_behavior.status, SlotStatus.ambiguous)
        self.assertEqual(extraction.correct_behavior.status, SlotStatus.unknown)


if __name__ == "__main__":
    unittest.main()
