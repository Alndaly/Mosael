/** @vitest-environment jsdom */
import React from "react";
import { render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";

import { useTurnElapsedSeconds } from "./useTurnElapsedSeconds";

function Probe({ running, startedAt }: { running: boolean; startedAt: Date | null }) {
  return <output aria-label="elapsed">{useTurnElapsedSeconds(running, startedAt)}</output>;
}

afterEach(() => vi.useRealTimers());

// 「已用」从后端给的这一轮开始时间算:刷新页面不从 0 数起,一轮紧接一轮时也不把几轮加在一起。
it("从这一轮真正开始的时刻算,不从面板看到 running 的那一刻算", () => {
  vi.useFakeTimers();
  vi.setSystemTime(new Date("2026-11-15T07:30:00Z"));
  const view = render(<Probe running startedAt={null} />);
  expect(screen.getByLabelText("elapsed").textContent).toBe("0");

  view.rerender(<Probe running startedAt={new Date("2026-11-15T07:27:13Z")} />);
  expect(screen.getByLabelText("elapsed").textContent).toBe("167");

  view.rerender(<Probe running={false} startedAt={null} />);
  expect(screen.getByLabelText("elapsed").textContent).toBe("0");
});
