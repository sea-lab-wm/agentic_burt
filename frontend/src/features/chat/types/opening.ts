import type { AgentMessage } from "./chat";

const baseOpeningCopy = [
  "I’m BURT++, your bug reporting assistant.",
  "Describe what happened, what you expected, and any steps that led up to the issue. I’ll ask follow-up questions until I can assemble the report.",
];

export function buildOpeningMessages(bugId: number): AgentMessage[] {
  return baseOpeningCopy.map((text, index) => ({
    id: `opening-${bugId}-${index}`,
    kind: "agent",
    text,
  }));
}
