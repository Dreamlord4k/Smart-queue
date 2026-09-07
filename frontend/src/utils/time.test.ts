import { describe, expect, it } from "vitest";

import {
  formatUniversitySessionStart,
  formatUniversityTime,
  UNIVERSITY_TIME_NOTE,
  UNIVERSITY_TIME_ZONE,
} from "./time";

describe("екатеринбургское время", () => {
  it("форматирует UTC-момент в зоне вуза", () => {
    expect(UNIVERSITY_TIME_ZONE).toBe("Asia/Yekaterinburg");
    expect(formatUniversityTime("2026-09-08T14:45:00Z")).toBe("19:45");
  });

  it("не сдвигает локальное время начала сессии повторно", () => {
    expect(formatUniversitySessionStart("2026-09-08", "19:45:00")).toBe(
      "2026-09-08 в 19:45",
    );
    expect(UNIVERSITY_TIME_NOTE).toBe("время местное");
  });
});
