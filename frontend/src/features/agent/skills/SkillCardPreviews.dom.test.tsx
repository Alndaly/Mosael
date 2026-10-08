/** @vitest-environment jsdom */
import React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { Confirmation } from "@/api/client";

/**
 * 智能体改技能的确认卡(ADR 0043):卡上是要批的东西本身 —— 新建 / 复制是全文加「建好就启用」(默认勾着),
 * 改是每个文件「改之前 → 改之后」,开是全文,从链接导入是和设置页同一个审阅(脚本标「不会执行」、默认不开);
 * 「在用技能时提出的」那句摆在后果提示里;这几张卡**每次都问**,对话里不给「本会话始终允许」。
 * 批准时卡上拨过的开关一起带走。
 */

const api = vi.hoisted(() => ({
  listConfirmations: vi.fn(),
  approveConfirmation: vi.fn(),
  rejectConfirmation: vi.fn(),
  getSkill: vi.fn(),
  getSkillImport: vi.fn(),
  getAgentSession: vi.fn(),
  updateAgentSession: vi.fn(),
  listAgentQuestions: vi.fn(),
  answerAgentQuestion: vi.fn(),
  dismissAgentQuestion: vi.fn(),
}));
vi.mock("@/api/client", () => api);
vi.mock("@/app/preferences", async () => {
  const { messages } = await import("@/app/messages");
  return {
    useI18n: () => (key: keyof (typeof messages)["zh-CN"]) => messages["zh-CN"][key] ?? key,
    usePreferences: () => ({ locale: "zh-CN" }),
  };
});
vi.mock("@/features/agent/confirmSurface", () => ({
  registerInlineConfirmSurface: () => () => {},
  useInlineConfirmSessions: () => [],
}));

import { ConfirmationCenter } from "@/features/agent/ConfirmationCenter";
import { PendingDecisions, SessionDecisions } from "@/features/agent/PendingDecisions";

function card(tool: string, payload: Record<string, unknown>, over: Partial<Confirmation> = {}): Confirmation {
  return {
    id: `card-${tool}`, workspace_id: "ws-1", session_id: null, tool_call_id: null, tool, allow_tool: tool, permission: "edit", writes: ["skills"],
    summary: "摘要", headline: `卡:${tool}`, warning: "", summary_key: "", summary_params: {}, payload, status: "pending",
    result: {}, error: null, error_summary: null, error_detail: null, error_hint: null, requested_by: "pi-agent", decision_mode: "manual", decided_by: null,
    created_at: "2026-10-07T00:00:00Z", resolved_at: null, always_asks: true, choices: {}, ...over,
  };
}

const CREATE = card("create_skill", {
  name: "ad-cuts", description: "把长视频剪成广告片", enable: true,
  files: { "references/tips.md": "节奏要快", "scripts/cut.py": "print('cut')" },
  _skill_md: "---\nname: ad-cuts\ndescription: \"把长视频剪成广告片\"\n---\n\n1. 先看素材\n2. 挑三段\n",
  _files: [
    { path: "SKILL.md", size: 60, script: false, binary: false },
    { path: "references/tips.md", size: 12, script: false, binary: false },
    { path: "scripts/cut.py", size: 12, script: true, binary: false },
  ],
}, { choices: { enable: true }, warning: "这是在用技能『创意画板』时提出的" });

function mountCenter() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <ConfirmationCenter workspaceId="ws-1" />
    </QueryClientProvider>,
  );
}

const theCard = () => document.querySelector("article[data-status='pending']") as HTMLElement;

beforeEach(() => {
  for (const fn of Object.values(api)) fn.mockReset();
  api.approveConfirmation.mockImplementation(async (id: string) => ({ ...CREATE, id, status: "executed" }));
  api.listAgentQuestions.mockResolvedValue([]);
});
afterEach(cleanup);

describe("新建技能的卡", () => {
  it("全文摆在卡上,脚本标不会执行,在用技能那句单独成行", async () => {
    api.listConfirmations.mockResolvedValue([CREATE]);
    mountCenter();
    await waitFor(() => expect(theCard()).toBeTruthy());

    const skillMd = () => theCard().querySelector("[data-slot='skill-content'] [data-skill-file='SKILL.md'] pre");
    expect(skillMd()?.textContent).toContain("2. 挑三段");
    expect(theCard().querySelector("[data-slot='skill-content'] dd")?.textContent).toBe("把长视频剪成广告片");
    expect(within(theCard()).getByText("脚本 · 不会执行")).toBeInTheDocument();
    expect(within(theCard()).getByRole("note").textContent).toContain("这是在用技能『创意画板』时提出的");
  });

  it("建好就启用默认勾着;取消勾选再批,批准请求带着 enable=false", async () => {
    api.listConfirmations.mockResolvedValue([CREATE]);
    mountCenter();
    await waitFor(() => expect(theCard()).toBeTruthy());
    const box = within(theCard().querySelector("[data-slot='skill-card-enable']") as HTMLElement).getByRole("checkbox");
    expect(box).toHaveAttribute("data-state", "checked");

    fireEvent.click(box);
    fireEvent.click(within(theCard()).getByRole("button", { name: /批准/ }));

    await waitFor(() => expect(api.approveConfirmation).toHaveBeenCalledWith("card-create_skill", { enable: false }));
  });
});

describe("改技能的卡", () => {
  it("每个动了的文件一块:改之前划掉、改之后标出来,删掉的文件说明白", async () => {
    api.listConfirmations.mockResolvedValue([card("update_skill", {
      name: "brand-rules",
      _changes: [
        { path: "SKILL.md", before: "1. 第一步\n3. 第三步\n", after: "1. 第一步\n3. 改过的第三步\n" },
        { path: "references/old.md", before: "旧的", after: null },
      ],
    })]);
    mountCenter();
    await waitFor(() => expect(theCard()).toBeTruthy());

    const skillMd = theCard().querySelector("[data-skill-change='SKILL.md']") as HTMLElement;
    expect(skillMd.querySelector("ins")?.textContent).toContain("改过的");
    const removed = theCard().querySelector("[data-skill-change='references/old.md']") as HTMLElement;
    expect(removed.textContent).toContain("删掉这个文件");
    expect(removed.querySelector("del")?.textContent).toContain("旧的");
    expect(theCard().querySelector("[data-slot='skill-card-enable']")).toBeNull();
  });
});

describe("改技能的卡:长文件只看改动那一截", () => {
  it("改动落在很长的原样文字后面,折起来时也看得到;点「看整个文件」才摊开全部", async () => {
    const head = `---\nname: long\n---\n${"原样的一句话。\n".repeat(80)}`;
    api.listConfirmations.mockResolvedValue([card("update_skill", {
      name: "long",
      _changes: [{ path: "SKILL.md", before: `${head}3. 第三步\n`, after: `${head}3. 第三步,标上预计时长\n` }],
    })]);
    mountCenter();
    await waitFor(() => expect(theCard()).toBeTruthy());

    const file = theCard().querySelector("[data-skill-change='SKILL.md']") as HTMLElement;
    expect(file.querySelector("ins")?.textContent).toContain("标上预计时长");
    expect(file.textContent).not.toContain("name: long");
    fireEvent.click(within(file).getByRole("button", { name: "看整个文件" }));
    fireEvent.click(within(file).getByRole("button", { name: "展开全文" }));
    expect(file.textContent).toContain("name: long");
  });
});

describe("开关、导入、复制的卡", () => {
  it("开:读全文摊在卡上;关:只有标题那一句", async () => {
    api.getSkill.mockResolvedValue({
      ref: "tips", name: "tips", title: "小窍门", description: "插件的做法", source: "plugin", source_label: "插件「Tips」",
      origin: "plugin", enabled: false, editable: false, problem: "", license: "", compatibility: "", allowed_tools: "",
      unknown_fields: [], metadata: {}, body: "", files: [{ path: "SKILL.md", size: 30, script: false, text: "---\nname: tips\n---\n插件的全文", binary: false }],
    });
    api.listConfirmations.mockResolvedValue([
      card("set_skill_enabled", { name: "dev.x:tips", enabled: true }, { id: "on" }),
      card("set_skill_enabled", { name: "workflow-canvas", enabled: false }, { id: "off" }),
    ]);
    mountCenter();
    await waitFor(() => expect(screen.getByText(/插件的全文/)).toBeInTheDocument());
    expect(api.getSkill).toHaveBeenCalledTimes(1);
    expect(api.getSkill).toHaveBeenCalledWith("ws-1", "dev.x:tips");
    expect(document.querySelector("[data-slot='skill-card-enable-review']")?.textContent).toContain("插件「Tips」");
  });

  it("从链接导入:和设置页同一个审阅,装好就启用默认不勾", async () => {
    api.getSkillImport.mockResolvedValue({
      import_id: "i".repeat(32), source_name: "github.com/acme/skills/tree/main/skills/pdf",
      skills: [{
        name: "pdf", title: "", description: "PDF 的做法", license: "", compatibility: "", allowed_tools: "", unknown_fields: ["argument-hint"],
        folder: "pdf", conflict: "workspace",
        files: [
          { path: "SKILL.md", size: 40, script: false, text: "---\nname: pdf\n---\n导入的全文", binary: false },
          { path: "scripts/run.py", size: 10, script: true, text: "print('x')", binary: false },
          { path: "assets/logo.png", size: 2048, script: false, text: null, binary: true },
        ],
      }],
    });
    api.listConfirmations.mockResolvedValue([card("import_skill", {
      url: "https://github.com/acme/skills/tree/main/skills/pdf", import_id: "i".repeat(32), enable: false,
      _skills: [{ name: "pdf", title: "", conflict: "workspace", files: 3 }],
    }, { choices: { enable: false } })]);
    mountCenter();
    await waitFor(() => expect(screen.getByText(/导入的全文/)).toBeInTheDocument());

    expect(within(theCard()).getByText("脚本 · 不会执行")).toBeInTheDocument();
    expect(within(theCard()).getByText(/二进制 · 2.0 KB/)).toBeInTheDocument();
    expect(theCard().querySelector("[data-slot='skill-unknown-fields']")?.textContent).toContain("argument-hint");
    expect(within(theCard()).getByText("会替换掉这个工作区里已有的同名技能")).toBeInTheDocument();
    const box = within(theCard().querySelector("[data-slot='skill-card-enable']") as HTMLElement).getByRole("checkbox");
    expect(box).toHaveAttribute("data-state", "unchecked");
  });

  it("复制成我的:新的 SKILL.md 和没改的文件(从原来那份读)都摊开", async () => {
    api.getSkill.mockResolvedValue({
      ref: "creative-board", name: "creative-board", title: "创意画板", description: "d", source: "builtin", source_label: "Mosael 内置",
      origin: "builtin", enabled: true, editable: false, problem: "", license: "", compatibility: "", allowed_tools: "",
      unknown_fields: [], metadata: {}, body: "", files: [{ path: "references/cells.md", size: 9, script: false, text: "格子的参考", binary: false }],
    });
    api.listConfirmations.mockResolvedValue([card("copy_skill", {
      name: "creative-board", new_name: "my-board", enable: true, _source_title: "创意画板", _source_label: "Mosael 内置",
      _description: "我们自己的画板做法", _skill_md: "---\nname: my-board\n---\n新的正文",
      _files: [{ path: "SKILL.md", size: 30, script: false, binary: false }, { path: "references/cells.md", size: 9, script: false, binary: false }],
    }, { choices: { enable: true } })]);
    mountCenter();
    await waitFor(() => expect(theCard()).toBeTruthy());

    expect(theCard().textContent).toContain("复制自「创意画板」(Mosael 内置)");
    expect(theCard().querySelector("[data-skill-file='SKILL.md'] pre")?.textContent).toContain("新的正文");
    const cells = () => theCard().querySelector("[data-skill-file='references/cells.md'] button") as HTMLButtonElement;
    await waitFor(() => expect(cells()).not.toBeDisabled());
    fireEvent.click(cells());
    await waitFor(() => expect(within(theCard()).getByText("格子的参考")).toBeInTheDocument());
  });
});

describe("每次都问", () => {
  function mountChat() {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    return render(
      <QueryClientProvider client={client}>
        <SessionDecisions workspaceId="ws-1" sessionId="s1">
          <PendingDecisions placed={new Set()} />
        </SessionDecisions>
      </QueryClientProvider>,
    );
  }

  it("对话里改技能的卡不给「本会话始终允许」,写明每次都要确认;别的 edit 卡照旧给", async () => {
    api.listConfirmations.mockImplementation(async ({ status }: { status?: string }) =>
      status === "pending"
        ? [
            { ...CREATE, session_id: "s1" },
            card("edit_timeline", {}, { id: "plain", session_id: "s1", always_asks: false }),
          ]
        : [],
    );
    mountChat();
    await waitFor(() => expect(document.querySelectorAll("article[data-status='pending']").length).toBe(2));
    const [skillCard, plainCard] = [...document.querySelectorAll("article[data-status='pending']")] as HTMLElement[];

    expect(within(skillCard).queryByRole("button", { name: /本会话始终允许/ })).toBeNull();
    expect(skillCard.textContent).toContain("这类改动每次都要你确认");
    expect(within(plainCard).getByRole("button", { name: /本会话始终允许/ })).toBeInTheDocument();

    fireEvent.click(within(skillCard).getByRole("button", { name: /允许一次/ }));
    await waitFor(() => expect(api.approveConfirmation).toHaveBeenCalledWith("card-create_skill", { enable: true }));
  });
});
