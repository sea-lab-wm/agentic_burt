import unittest

from langchain_core.messages import HumanMessage

from graph_utils import (
    find_unknown_or_ambiguous,
    format_bug_info_for_prompt,
    format_extraction_update,
    process_bug_info,
)
from llm_schema import ExtractionSchema
from state import BugAgentState, CandidateMapping, InfoSlots, InformationElementExtraction, Slot, SlotStatus


class GraphUtilsTests(unittest.TestCase):
    def test_find_unknown_or_ambiguous_flags_scalar_and_list_entries(self):
        info = InfoSlots(
            triggering_screen_reference=Slot(
                status=SlotStatus.ambiguous,
                candidates=[
                    CandidateMapping(value="screen_a", evidence="quote a"),
                    CandidateMapping(value="screen_b", evidence="quote b"),
                ],
            ),
            triggering_GUI_interactions=[
                Slot(
                    status=SlotStatus.confirmed,
                    candidates=[CandidateMapping(value="transition_1", evidence="direct quote")],
                ),
                Slot(
                    status=SlotStatus.ambiguous,
                    candidates=[
                        CandidateMapping(value="transition_2", evidence="quote c"),
                        CandidateMapping(value="transition_3", evidence="quote d"),
                    ],
                ),
            ],
            buggy_behavior=Slot(
                status=SlotStatus.confirmed,
                candidates=[CandidateMapping(value="freeze", evidence="direct quote")],
            ),
            correct_behavior=Slot(status=SlotStatus.unknown, candidates=[]),
            steps_to_reproduce=[],
        )

        flagged = find_unknown_or_ambiguous(info)

        self.assertEqual(
            flagged,
            {
                "triggering_screen_reference",
                "triggering_GUI_interactions[1]",
                "correct_behavior",
                "steps_to_reproduce",
            },
        )

    def test_format_extraction_update_preserves_existing_fields_when_omitted(self):
        state = BugAgentState(
            messages=[HumanMessage(content="the app crashes")],
            BugInfo=InfoSlots(
                triggering_screen_reference=Slot(
                    status=SlotStatus.confirmed,
                    candidates=[CandidateMapping(value="screen_hash", evidence="named directly")],
                ),
                triggering_GUI_interactions=[
                    Slot(
                        status=SlotStatus.inferred,
                        candidates=[CandidateMapping(value="tap_hash", evidence="single likely tap")],
                    )
                ],
                buggy_behavior=Slot(status=SlotStatus.unknown, candidates=[]),
                correct_behavior=Slot(status=SlotStatus.unknown, candidates=[]),
                steps_to_reproduce=[],
            ),
        )
        extraction = ExtractionSchema(
            buggy_behavior=Slot(
                status=SlotStatus.confirmed,
                candidates=[
                    CandidateMapping(value="the app crashes", evidence="user said it crashes")
                ],
            )
        )

        update = format_extraction_update(state, extraction)
        bug_info = update["BugInfo"]

        self.assertEqual(
            bug_info.triggering_screen_reference.candidates[0].value,
            "screen_hash",
        )
        self.assertEqual(
            bug_info.triggering_GUI_interactions[0].candidates[0].value,
            "tap_hash",
        )
        self.assertEqual(bug_info.buggy_behavior.candidates[0].value, "the app crashes")
        self.assertIsInstance(
            update["information_element_extraction"],
            InformationElementExtraction,
        )

    def test_format_bug_info_for_prompt_includes_candidate_evidence(self):
        info = InfoSlots(
            triggering_screen_reference=Slot(
                status=SlotStatus.ambiguous,
                candidates=[
                    CandidateMapping(
                        value="reports_income_tab",
                        evidence='User mentioned "Incomes by Articles".',
                    ),
                    CandidateMapping(
                        value="reports_expense_tab",
                        evidence='User also mentioned "Expenses by Articles".',
                    ),
                ],
            ),
            buggy_behavior=Slot(status=SlotStatus.unknown, candidates=[]),
            correct_behavior=Slot(status=SlotStatus.unknown, candidates=[]),
            triggering_GUI_interactions=[],
            steps_to_reproduce=[],
        )

        serialized = format_bug_info_for_prompt(info)

        self.assertIn('"status": "ambiguous"', serialized)
        self.assertIn("reports_income_tab", serialized)
        self.assertIn('User mentioned \\"Incomes by Articles\\".', serialized)
        self.assertIn("reports_expense_tab", serialized)

    def test_process_bug_info_raises_on_unresolved_slot(self):
        info = InfoSlots(
            triggering_screen_reference=Slot(status=SlotStatus.unknown, candidates=[]),
            triggering_GUI_interactions=[],
            buggy_behavior=Slot(
                status=SlotStatus.confirmed,
                candidates=[CandidateMapping(value="freeze", evidence="quote")],
            ),
            correct_behavior=Slot(
                status=SlotStatus.confirmed,
                candidates=[CandidateMapping(value="stay stable", evidence="quote")],
            ),
            steps_to_reproduce=[],
        )

        with self.assertRaises(ValueError):
            process_bug_info(info)


if __name__ == "__main__":
    unittest.main()
