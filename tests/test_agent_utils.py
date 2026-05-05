import unittest

from langchain_core.messages import HumanMessage

from agent_utils import (
    find_unknown_or_ambiguous,
    format_bug_info_for_prompt,
    format_extraction_update,
    format_unknown_or_ambiguous_references,
    llm_clarity_follow_up,
    llm_extract,
    llm_more_info_follow_up,
    validate_info_status,
)
from llm_schema import ClarityFollowUpSchema, ExtractionSchema, MoreInfoFollowUpSchema
from state import (
    ActiveFollowUp,
    BugAgentState,
    CandidateMapping,
    FollowUpKind,
    InfoSlots,
    InformationElementExtraction,
    Slot,
    SlotStatus,
)


class FakeStructuredModel:
    def __init__(self, result):
        self.result = result
        self.invocations = []

    def invoke(self, messages):
        self.invocations.append(messages)
        return self.result


class FakeModel:
    def __init__(self, result):
        self.result = result
        self.requested_schema = None
        self.structured_model = None

    def with_structured_output(self, schema):
        self.requested_schema = schema
        self.structured_model = FakeStructuredModel(self.result)
        return self.structured_model


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
            active_follow_up=ActiveFollowUp(
                kind=FollowUpKind.more_info,
                question="Which screen were you on?",
                target_info_elements=["triggering_screen_reference"],
            ),
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
        self.assertIsNone(update["active_follow_up"])

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

    def test_validate_info_status_raises_on_unresolved_slot(self):
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
            validate_info_status(info)

    def test_format_unknown_or_ambiguous_references_prioritizes_unknown_and_normalizes_labels(self):
        info = InfoSlots(
            triggering_screen_reference=Slot(
                status=SlotStatus.ambiguous,
                candidates=[
                    CandidateMapping(value="screen_a", evidence="quote a"),
                    CandidateMapping(value="screen_b", evidence="quote b"),
                ],
            ),
            triggering_GUI_interactions=[
                Slot(status=SlotStatus.unknown, candidates=[]),
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
                candidates=[CandidateMapping(value="freeze", evidence="quote")],
            ),
            correct_behavior=Slot(status=SlotStatus.unknown, candidates=[]),
            steps_to_reproduce=[],
        )

        formatted = format_unknown_or_ambiguous_references(
            info,
            {
                "triggering_screen_reference",
                "triggering_GUI_interactions[0]",
                "triggering_GUI_interactions[1]",
                "correct_behavior",
            },
        )

        self.assertEqual(
            formatted,
            "\n".join(
                [
                    "- correct_behavior",
                    "- triggering_gui_interactions[0]",
                    "- triggering_GUI_interactions[1]".replace("GUI", "gui"),
                    "- triggering_screen_reference",
                ]
            ),
        )

    def test_llm_extract_uses_more_info_mode_and_targets(self):
        model = FakeModel(InformationElementExtraction())

        llm_extract(
            user_messages=["I was on the reports screen."],
            model=model,
            app_name="Test App",
            follow_up_question="Which screen were you on?",
            target_info_elements=["triggering_screen_reference"],
            extraction_mode="more_info_follow_up",
        )

        self.assertEqual(model.requested_schema, InformationElementExtraction)
        messages = model.structured_model.invocations[0]
        self.assertIn("Extraction mode: more_info_follow_up", messages[1].content)
        self.assertIn("Which screen were you on?", messages[1].content)
        self.assertIn("triggering_screen_reference", messages[1].content)

    def test_llm_clarity_follow_up_uses_clarity_schema(self):
        model = FakeModel(
            ClarityFollowUpSchema(follow_up_question="What do you mean by it?")
        )

        result = llm_clarity_follow_up(
            information_element_extraction=InformationElementExtraction(
                buggy_behavior={
                    "value": "it restarts on its own",
                    "evidence": ["it restarts on its own"],
                }
            ),
            clarity_issues=["Pronoun 'it' is ambiguous."],
            model=model,
            app_name="Test App",
        )

        self.assertEqual(model.requested_schema, ClarityFollowUpSchema)
        self.assertEqual(result.follow_up_question, "What do you mean by it?")

    def test_llm_more_info_follow_up_uses_more_info_schema(self):
        model = FakeModel(
            MoreInfoFollowUpSchema(
                follow_up_question="Which screen were you on?",
                clarification_target_info_elements=["triggering_screen_reference"],
            )
        )

        result = llm_more_info_follow_up(
            current_bug_info=InfoSlots(),
            transitions="open_app -> home",
            screen_descriptions="[home] - Home: landing screen",
            formatted_unknown_and_low_confidence_info="- triggering_screen_reference",
            model=model,
            app_name="Test App",
        )

        self.assertEqual(model.requested_schema, MoreInfoFollowUpSchema)
        self.assertEqual(result.follow_up_question, "Which screen were you on?")
        self.assertEqual(
            result.clarification_target_info_elements,
            ["triggering_screen_reference"],
        )


if __name__ == "__main__":
    unittest.main()
