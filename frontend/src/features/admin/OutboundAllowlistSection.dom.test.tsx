/** @vitest-environment jsdom */
import React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";

/**
 * 内网访问的允许名单:列出来的是后端存的那份,加一项 / 去一项都是整份清单 PUT 回去 —— 写得对不对由后端判,
 * 挡下来的那句话(点名写不对的那一项)留在弹窗里。
 */

const t = (key: string) => key;
vi.mock("@/app/preferences", () => ({ useI18n: () => t }));
vi.mock("sonner", () => ({ toast: { error: vi.fn() } }));

const puts: string[][] = [];
let stored: string[] = [];
vi.mock("@/api/client", () => ({
  getOutboundAllowlist: () => Promise.resolve({ entries: stored }),
  setOutboundAllowlist: (entries: string[]) => {
    puts.push(entries);
    if (entries.includes("nas local")) return Promise.reject(new Error("允许名单里这一项写不对:nas local"));
    stored = entries;
    return Promise.resolve({ entries: stored });
  },
}));

const { OutboundAllowlistSection } = await import("./OutboundAllowlistSection");

function show() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <OutboundAllowlistSection />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  puts.length = 0;
  stored = ["127.0.0.1:11434"];
});

it("加一项、去一项都把整份清单交给后端", async () => {
  show();
  expect(await screen.findByText("127.0.0.1:11434")).toBeInTheDocument();

  fireEvent.click(screen.getByRole("button", { name: /deployOutboundNew/ }));
  const dialog = await screen.findByRole("dialog");
  const input = within(dialog).getByLabelText(/deployOutboundEntry/);
  fireEvent.change(input, { target: { value: " 10.0.0.0/8 " } });
  fireEvent.keyDown(input, { key: "Enter", keyCode: 229 });
  expect(puts).toEqual([]);
  fireEvent.keyDown(input, { key: "Enter" });
  await waitFor(() => expect(screen.getByText("10.0.0.0/8")).toBeInTheDocument());
  expect(puts).toEqual([["127.0.0.1:11434", "10.0.0.0/8"]]);
  await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());

  fireEvent.click(screen.getAllByRole("button", { name: "deployOutboundRemove" })[0]);
  await waitFor(() => expect(screen.queryByText("127.0.0.1:11434")).not.toBeInTheDocument());
  expect(stored).toEqual(["10.0.0.0/8"]);
});

it("后端挡下来的那句话留在弹窗里,贴着输入框;一改输入就消失", async () => {
  show();
  await screen.findByText("127.0.0.1:11434");
  fireEvent.click(screen.getByRole("button", { name: /deployOutboundNew/ }));
  const dialog = await screen.findByRole("dialog");
  const input = within(dialog).getByLabelText(/deployOutboundEntry/);
  fireEvent.change(input, { target: { value: "nas local" } });
  fireEvent.click(within(dialog).getByRole("button", { name: "deployOutboundAdd" }));

  expect(await within(dialog).findByRole("alert")).toHaveTextContent("nas local");
  expect(input).toHaveAttribute("aria-invalid", "true");
  expect(stored).toEqual(["127.0.0.1:11434"]);
  fireEvent.change(input, { target: { value: "nas.local" } });
  expect(within(dialog).queryByRole("alert")).not.toBeInTheDocument();
});

it("一项都没放行时是「只许公网」的空态", async () => {
  stored = [];
  show();
  expect(await screen.findByText("deployOutboundEmpty")).toBeInTheDocument();
});
