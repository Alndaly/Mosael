/** @vitest-environment jsdom */
import React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

type Row = {
  id: string;
  workspace_id: string;
  project_id: null;
  content: string;
  source: string;
  created_at: string;
  updated_at: string;
};

let rows: Row[] = [];
const api = vi.fn();

vi.mock("@/api/client", () => ({
  api: (...args: unknown[]) => api(...args),
}));

vi.mock("@/app/preferences", () => ({
  useI18n: () => (key: string) => key,
  usePreferences: () => ({ locale: "en-US" }),
}));

import { AgentMemorySection } from "./AgentMemorySection";

const memory = (id: string, content: string, source: "agent" | "user", edited = false): Row => ({
  id,
  workspace_id: "ws-1",
  project_id: null,
  content,
  source,
  created_at: "2026-09-01T10:00:00",
  updated_at: edited ? "2026-09-03T10:00:00" : "2026-09-01T10:00:00.000200",
});

function renderSection() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <AgentMemorySection workspace={{ id: "ws-1" } as never} />
    </QueryClientProvider>,
  );
}

function calls(method: string) {
  return api.mock.calls.filter(([, init]) => (init as RequestInit | undefined)?.method === method);
}

describe("AgentMemorySection", () => {
  beforeEach(() => {
    rows = [];
    api.mockReset();
    api.mockImplementation(async (url: string, init?: RequestInit) => {
      if (!init?.method) return rows;
      if (init.method === "POST") {
        const body = JSON.parse(String(init.body));
        const row = memory(`m${rows.length + 1}`, body.content, "user");
        rows = [...rows, row];
        return row;
      }
      if (init.method === "PATCH") {
        const id = url.split("/").pop();
        const body = JSON.parse(String(init.body));
        rows = rows.map((row) => (row.id === id ? { ...row, content: body.content } : row));
        return rows.find((row) => row.id === id);
      }
      if (init.method === "DELETE") {
        const id = url.split("/").pop();
        rows = rows.filter((row) => row.id !== id);
        return undefined;
      }
      throw new Error(`unexpected ${init.method} ${url}`);
    });
  });

  it("explains what memories are for when there are none, and offers to add one", async () => {
    renderSection();

    expect(await screen.findByText("agentMemoryEmpty")).toBeInTheDocument();
    expect(screen.getByText("agentMemoryEmptyHint")).toBeInTheDocument();
    // 标题旁的「选择」在没有东西可选时禁用;添加入口有两个(标题旁 + 空态里),都能点。
    expect(screen.getByRole("button", { name: "bulkSelect" })).toBeDisabled();
    const adds = screen.getAllByRole("button", { name: "agentMemoryAdd" });
    expect(adds).toHaveLength(2);
    for (const button of adds) expect(button).toBeEnabled();
  });

  it("shows the source as a badge beside the time, not glued onto the sentence", async () => {
    rows = [memory("u1", "Final cuts are 1080x1920", "user"), memory("a1", "Client dislikes red", "agent", true)];
    const { container } = renderSection();

    const sentence = await screen.findByText("Client dislikes red");
    expect(sentence.tagName).toBe("P");
    // 正文里只有正文。
    expect(sentence).toHaveTextContent(/^Client dislikes red$/);

    const items = [...container.querySelectorAll<HTMLElement>('[data-slot="settings-list-item"]')];
    expect(items).toHaveLength(2);
    const [userRow, agentRow] = items;
    expect(userRow.dataset.source).toBe("user");
    expect(within(userRow).getByText("agentMemoryFromUser").closest('[data-slot="memory-source"]')).not.toBeNull();
    expect(within(agentRow).getByText("agentMemoryFromAgent").closest('[data-slot="memory-source"]')).not.toBeNull();
    expect(within(userRow).queryByText("agentMemoryFromAgent")).toBeNull();

    // 新建后没改过的说"记下",改过的说"改过",时间都带机器可读的 dateTime。
    expect(userRow.querySelector("time")?.textContent).toMatch(/^agentMemoryAddedAt$/);
    expect(agentRow.querySelector("time")?.textContent).toMatch(/^agentMemoryEditedAt$/);
    expect(agentRow.querySelector("time")?.getAttribute("dateTime")).toBe("2026-09-03T10:00:00");

    expect(screen.getByText("agentMemorySummary")).toBeInTheDocument();
  });

  it("adds through a dialog: Cmd+Enter saves", async () => {
    const user = userEvent.setup();
    renderSection();
    await screen.findByText("agentMemoryEmpty");

    await user.click(screen.getAllByRole("button", { name: "agentMemoryAdd" })[0]);
    const dialog = screen.getByRole("dialog", { name: "agentMemoryAddTitle" });
    const field = within(dialog).getByRole("textbox", { name: "agentMemoryContentLabel" });
    expect(field).toHaveFocus();
    // 空的时候保存键按不动。
    expect(within(dialog).getByRole("button", { name: "save" })).toBeDisabled();

    await user.type(field, "  Intro is brand-intro.mp4  ");
    await user.keyboard("{Meta>}{Enter}{/Meta}");

    await waitFor(() => expect(calls("POST")).toHaveLength(1));
    expect(JSON.parse(String(calls("POST")[0][1].body))).toEqual({
      workspace_id: "ws-1",
      content: "Intro is brand-intro.mp4",
      source: "user",
    });
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(await screen.findByText("Intro is brand-intro.mp4")).toBeInTheDocument();
  });

  it("Ctrl+Enter also saves; plain Enter is a newline", async () => {
    const user = userEvent.setup();
    renderSection();
    await screen.findByText("agentMemoryEmpty");

    await user.click(screen.getAllByRole("button", { name: "agentMemoryAdd" })[0]);
    const field = screen.getByRole("textbox", { name: "agentMemoryContentLabel" });
    await user.type(field, "line one{Enter}line two");
    expect(calls("POST")).toHaveLength(0);
    await user.keyboard("{Control>}{Enter}{/Control}");

    await waitFor(() => expect(calls("POST")).toHaveLength(1));
    expect(JSON.parse(String(calls("POST")[0][1].body)).content).toBe("line one\nline two");
  });

  it("Escape cancels the add dialog without saving", async () => {
    const user = userEvent.setup();
    renderSection();
    await screen.findByText("agentMemoryEmpty");

    await user.click(screen.getAllByRole("button", { name: "agentMemoryAdd" })[0]);
    await user.type(screen.getByRole("textbox", { name: "agentMemoryContentLabel" }), "draft");
    await user.keyboard("{Escape}");

    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(calls("POST")).toHaveLength(0);

    // 再打开是空的 —— 上一次没存的草稿不该留着。
    await user.click(screen.getAllByRole("button", { name: "agentMemoryAdd" })[0]);
    expect(screen.getByRole("textbox", { name: "agentMemoryContentLabel" })).toHaveValue("");
  });

  it("edits a memory in the same dialog, prefilled", async () => {
    const user = userEvent.setup();
    rows = [memory("a1", "Client dislikes red", "agent")];
    renderSection();
    await screen.findByText("Client dislikes red");

    await user.click(screen.getByRole("button", { name: "agentMemoryEdit" }));
    const dialog = screen.getByRole("dialog", { name: "agentMemoryEdit" });
    const field = within(dialog).getByRole("textbox", { name: "agentMemoryContentLabel" });
    expect(field).toHaveValue("Client dislikes red");
    // 没改就不给存。
    expect(within(dialog).getByRole("button", { name: "save" })).toBeDisabled();

    await user.clear(field);
    await user.type(field, "Client dislikes red and orange");
    await user.click(within(dialog).getByRole("button", { name: "save" }));

    await waitFor(() => expect(calls("PATCH")).toHaveLength(1));
    expect(calls("PATCH")[0][0]).toBe("/api/agent/memories/a1");
    expect(await screen.findByText("Client dislikes red and orange")).toBeInTheDocument();
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("asks before deleting, quoting the memory", async () => {
    const user = userEvent.setup();
    rows = [memory("a1", "Client dislikes red", "agent")];
    renderSection();
    await screen.findByText("Client dislikes red");

    await user.click(screen.getByRole("button", { name: "delete" }));
    let confirm = screen.getByRole("alertdialog", { name: "agentMemoryDeleteTitle" });
    expect(calls("DELETE")).toHaveLength(0);

    await user.click(within(confirm).getByRole("button", { name: "cancel" }));
    await waitFor(() => expect(screen.queryByRole("alertdialog")).toBeNull());
    expect(calls("DELETE")).toHaveLength(0);

    await user.click(screen.getByRole("button", { name: "delete" }));
    confirm = screen.getByRole("alertdialog", { name: "agentMemoryDeleteTitle" });
    await user.click(within(confirm).getByRole("button", { name: "delete" }));

    await waitFor(() => expect(calls("DELETE")).toHaveLength(1));
    expect(calls("DELETE")[0][0]).toBe("/api/agent/memories/a1");
    expect(await screen.findByText("agentMemoryEmpty")).toBeInTheDocument();
  });

  it("bulk-deletes the selected memories after confirming", async () => {
    const user = userEvent.setup();
    rows = [memory("u1", "One", "user"), memory("a1", "Two", "agent"), memory("a2", "Three", "agent")];
    renderSection();
    await screen.findByText("One");

    await user.click(screen.getByRole("button", { name: "bulkSelect" }));
    // 选择模式下行尾的编辑/删除让位给勾选框。
    expect(screen.queryByRole("button", { name: "agentMemoryEdit" })).toBeNull();
    const boxes = screen.getAllByRole("checkbox", { name: "bulkSelectRow" });
    await user.click(boxes[1]);
    await user.click(boxes[2]);
    await user.click(screen.getByRole("button", { name: "bulkDelete" }));
    const confirm = screen.getByRole("alertdialog", { name: "bulkDeleteConfirm" });
    await user.click(within(confirm).getByRole("button", { name: "delete" }));

    await waitFor(() => expect(calls("DELETE")).toHaveLength(2));
    expect(calls("DELETE").map(([url]) => url).sort()).toEqual(["/api/agent/memories/a1", "/api/agent/memories/a2"]);
    await waitFor(() => expect(screen.queryByText("Two")).toBeNull());
    expect(screen.getByText("One")).toBeInTheDocument();
  });
});
