/** @vitest-environment jsdom */
import React from "react";
import { fireEvent, render, screen } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import { AdminActivityChart } from "./AdminActivityChart";

vi.mock("@/app/preferences", () => ({ useI18n: () => (key: string) => key }));
vi.mock("@/components/app/chart", () => ({
  ChartContainer: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
  ChartTooltip: () => null,
  ChartTooltipContent: () => null,
}));
vi.mock("recharts", () => ({
  BarChart: ({ data }: { data: unknown }) => <output aria-label="activity">{JSON.stringify(data)}</output>,
  Bar: () => null, CartesianGrid: () => null, XAxis: () => null,
}));

it("renders positive API totals even when the API has no succeeded field", () => {
  render(<AdminActivityChart points={[{ day: "2026-09-06", total: 5, failed: 2 }]} loading={false} error={false} onRetry={() => {}} />);
  expect(JSON.parse(screen.getByLabelText("activity").textContent!)).toEqual([{ day: "2026-09-06", total: 5, failed: 2, other: 3 }]);
  expect(screen.getByText("adminJobsOther")).toBeInTheDocument();
  expect(screen.queryByText("homeLegendSucceeded")).not.toBeInTheDocument();
});

it.each([{ points: [] }, { points: [{ day: "2026-09-06", total: 0, failed: 0 }] }])("shows an empty state for no activity", ({ points }) => {
  render(<AdminActivityChart points={points} loading={false} error={false} onRetry={() => {}} />);
  expect(screen.getByText("adminNoDataTitle")).toBeInTheDocument();
  expect(screen.queryByLabelText("activity")).not.toBeInTheDocument();
});

it("does not confuse loading or errors with no activity and offers retry", () => {
  const retry = vi.fn();
  const { rerender } = render(<AdminActivityChart points={[]} loading error={false} onRetry={retry} />);
  expect(screen.queryByText("adminNoDataTitle")).not.toBeInTheDocument();
  rerender(<AdminActivityChart points={[]} loading={false} error onRetry={retry} />);
  expect(screen.getByText("adminJobsLoadError")).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "retry" }));
  expect(retry).toHaveBeenCalledOnce();
});
