import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { TaskStatusBadge } from "@/components/tasks/TaskStatusBadge";
import type { TaskStatus } from "@/types/tasks";

const CASES: { status: TaskStatus; label: string }[] = [
  { status: "SUCCESS", label: "Success" },
  { status: "FAILURE", label: "Failure" },
  { status: "PENDING", label: "Pending" },
  { status: "STARTED", label: "Started" },
  { status: "RETRY", label: "Retry" },
  { status: "REVOKED", label: "Revoked" },
];

describe("TaskStatusBadge", () => {
  for (const { status, label } of CASES) {
    it(`renders correct label for ${status}`, () => {
      render(<TaskStatusBadge status={status} />);
      expect(screen.getByText(label)).toBeTruthy();
    });
  }

  it("applies green class for SUCCESS", () => {
    const { container } = render(<TaskStatusBadge status="SUCCESS" />);
    expect(container.innerHTML).toContain("green");
  });

  it("uses destructive variant for FAILURE", () => {
    const { container } = render(<TaskStatusBadge status="FAILURE" />);
    expect(container.innerHTML).toContain("destructive");
  });
});
