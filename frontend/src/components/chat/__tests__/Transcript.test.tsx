import { describe, expect, it } from "vitest";
import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { renderWithQuery } from "@/test/render";
import { Transcript } from "@/components/chat/Transcript";
import type { TranscriptTurn } from "@/hooks/useChatAgent";

const STEP = {
  id: "step-0",
  order: 0,
  thought: "I need AAPL's snapshot",
  tool: "company_snapshot",
  tool_args: { symbol: "AAPL" },
  observation: '{"trailing_pe": 39.07}',
  is_answer: false,
  status: "done" as const,
  error: "",
  created_at: "2026-09-28T00:00:00Z",
};

const ANSWER_STEP = { ...STEP, id: "step-1", order: 1, tool: "", tool_args: null, is_answer: true };

function turn(overrides: Partial<TranscriptTurn> = {}): TranscriptTurn {
  return {
    id: "run-1",
    query: "What is AAPL's trailing P/E?",
    output: "AAPL's trailing P/E is 39.07.",
    error: "",
    status: "done",
    steps: [STEP, ANSWER_STEP],
    toolsUsed: ["company_snapshot"],
    compacted: 0,
    ...overrides,
  };
}

describe("Transcript", () => {
  it("renders the empty state before anything is said", () => {
    renderWithQuery(<Transcript turns={[]} summary="" isRunning={false} />);

    expect(screen.getByText(/Ask about a company/i)).toBeInTheDocument();
  });

  it("shows the question and the reply", () => {
    renderWithQuery(<Transcript turns={[turn()]} summary="" isRunning={false} />);

    expect(screen.getByText("What is AAPL's trailing P/E?")).toBeInTheDocument();
    expect(screen.getByText("AAPL's trailing P/E is 39.07.")).toBeInTheDocument();
  });

  it("collapses tool calls and counts only the ones that used a tool", async () => {
    // The answer step carries no tool and is not worth a row - "used 2 tools" for one
    // lookup plus the reply would misdescribe what happened.
    renderWithQuery(<Transcript turns={[turn()]} summary="" isRunning={false} />);

    const toggle = screen.getByRole("button", { name: /used 1 tool/i });
    expect(screen.queryByText(/trailing_pe/)).not.toBeInTheDocument();

    await userEvent.click(toggle);

    expect(screen.getByText(/company_snapshot\(\{"symbol":"AAPL"\}\)/)).toBeInTheDocument();
    expect(screen.getByText(/trailing_pe/)).toBeInTheDocument();
  });

  it("shows the compaction summary once, for the conversation", () => {
    // Compaction is a property of the SESSION, not of the turn that triggered it.
    renderWithQuery(
      <Transcript turns={[turn(), turn()]} summary="They asked about AAPL." isRunning={false} />,
    );

    expect(screen.getAllByText(/Earlier messages summarised/)).toHaveLength(1);
  });

  it("marks a stopped turn rather than hiding it", () => {
    // The backend replays a stopped turn's partial output into the next prompt, so the UI
    // must show that it happened.
    renderWithQuery(
      <Transcript
        turns={[turn({ output: "", status: "stopped" })]}
        summary=""
        isRunning={false}
      />,
    );

    expect(screen.getByText("Stopped.")).toBeInTheDocument();
  });

  it("shows the error on a failed turn", () => {
    renderWithQuery(
      <Transcript
        turns={[turn({ output: "", status: "error", error: "Ollama is down" })]}
        summary=""
        isRunning={false}
      />,
    );

    expect(screen.getByText("Ollama is down")).toBeInTheDocument();
  });

  it("shows a thinking indicator only on the last turn while running", () => {
    renderWithQuery(
      <Transcript
        turns={[turn(), turn({ id: "run-2", output: "", status: "running", steps: [] })]}
        summary=""
        isRunning
      />,
    );

    expect(screen.getAllByLabelText("Thinking")).toHaveLength(1);
  });
});

describe("Transcript - partial replies", () => {
  it("marks a stopped turn that already has text", () => {
    // Without this a half-written reply reads as a complete answer that ended oddly.
    renderWithQuery(
      <Transcript
        turns={[turn({ output: "I was halfway thr", status: "stopped" })]}
        summary=""
        isRunning={false}
      />,
    );

    expect(screen.getByText(/I was halfway thr/)).toBeInTheDocument();
    expect(screen.getByText(/stopped/)).toBeInTheDocument();
  });
});
