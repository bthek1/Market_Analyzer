import { describe, it, expect } from "vitest";
import { formatDateTime } from "@/lib/utils";

describe("formatDateTime", () => {
  it("formats as dd/mm/yyyy, hh:mm:ss AM", () => {
    // Local-time components -> output is timezone-independent.
    expect(formatDateTime(new Date(2026, 5, 28, 11, 30, 0))).toBe(
      "28/06/2026, 11:30:00 AM",
    );
  });

  it("uses PM for afternoon times", () => {
    expect(formatDateTime(new Date(2026, 5, 28, 15, 5, 9))).toBe(
      "28/06/2026, 03:05:09 PM",
    );
  });

  it("renders midnight as 12 AM", () => {
    expect(formatDateTime(new Date(2026, 0, 1, 0, 0, 0))).toBe(
      "01/01/2026, 12:00:00 AM",
    );
  });

  it("renders noon as 12 PM", () => {
    expect(formatDateTime(new Date(2026, 11, 9, 12, 0, 0))).toBe(
      "09/12/2026, 12:00:00 PM",
    );
  });

  it("zero-pads day, month, and time components", () => {
    expect(formatDateTime(new Date(2026, 2, 4, 9, 7, 3))).toBe(
      "04/03/2026, 09:07:03 AM",
    );
  });
});
