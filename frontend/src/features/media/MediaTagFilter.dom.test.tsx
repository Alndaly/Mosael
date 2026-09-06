/** @vitest-environment jsdom */
import React from "react";
import { fireEvent, render, screen, within } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import { MediaTagFilter } from "./MediaTagFilter";

vi.mock("@/app/preferences", () => ({ useI18n: () => (key: string) => key }));

it("searches tags, applies one filter, and allows it to be cleared", async () => {
  const change = vi.fn();
  function Harness() {
    const [value, setValue] = React.useState<string | null>(null);
    return <MediaTagFilter tags={["Interview", "Landscape", "Demo"]} value={value} onChange={next => { change(next); setValue(next); }} />;
  }
  render(<Harness />);
  fireEvent.click(screen.getByRole("button", { name: "filterByTag" }));
  const dialog = await screen.findByRole("dialog");
  fireEvent.change(within(dialog).getByRole("textbox"), { target: { value: " INTER " } });
  expect(within(dialog).queryByRole("button", { name: "Demo" })).not.toBeInTheDocument();
  fireEvent.click(within(dialog).getByRole("button", { name: "Interview" }));
  expect(change).toHaveBeenLastCalledWith("Interview");
  expect(screen.getByRole("button", { name: "filterByTag" })).toHaveTextContent("Interview");
  fireEvent.click(screen.getByRole("button", { name: "mediaClearTag" }));
  expect(change).toHaveBeenLastCalledWith(null);
  fireEvent.click(screen.getByRole("button", { name: "filterByTag" }));
  expect(within(await screen.findByRole("dialog")).getByRole("button", { name: "Landscape" })).toBeInTheDocument();
});
