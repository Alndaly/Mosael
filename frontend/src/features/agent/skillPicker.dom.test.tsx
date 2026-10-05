/** @vitest-environment jsdom */
import React from "react";
import { act, cleanup, fireEvent, render, waitFor } from "@testing-library/react";
import type { Editor, JSONContent } from "@tiptap/react";
import { afterEach, describe, expect, it, vi } from "vitest";

/**
 * 输入框里的「/」:点名一个技能,这一轮照它做(ADR 0040 §4)。
 *
 * 盯四件事:菜单里是开着的技能;挑一个落成胶囊、正文里写 `/显示名`、点名的名字收得出来;只在行首或空格后面触发
 * (打网址不弹);菜单开着时回车是选,不是发送。
 */

vi.mock("@/app/preferences", async () => {
  const { messages } = await import("@/app/messages");
  return { useI18n: () => (key: keyof (typeof messages)["zh-CN"]) => messages["zh-CN"][key] ?? key };
});
vi.mock("@/api/client", () => ({ assetThumbnailUrl: (id: string) => `/thumb/${id}`, listSkills: async () => [] }));
vi.mock("@/features/agent/useReferencePreview", () => ({ useReferencePreview: () => ({ open: vi.fn(), modal: null }) }));
vi.mock("@floating-ui/dom", () => ({
  offset: vi.fn(),
  flip: vi.fn(),
  shift: vi.fn(),
  autoUpdate: (_reference: unknown, _element: unknown, update: () => void) => {
    update();
    return () => {};
  },
  computePosition: () => Promise.resolve({ x: 10, y: 10 }),
}));

import { ChatComposer, documentText, emptyDocument } from "@/features/agent/ChatComposer";
import { ReferenceDocument } from "@/features/agent/ReferenceDocument";
import { MAX_FORCED_SKILLS, collectSkills, type SkillOption } from "@/features/agent/SkillChip";

afterEach(cleanup);

const OPTIONS: SkillOption[] = [
  { ref: "short-video-ads", title: "做带货短视频", description: "从商品图写脚本、配音、出竖屏", sourceLabel: "工作区成员写的" },
  { ref: "brand-rules", title: "品牌规范", description: "片头、字体、颜色", sourceLabel: "从 brand.zip 导入" },
  { ref: "dev.example.tips:tips", title: "小窍门", description: "插件带的", sourceLabel: "插件「Tips」" },
  { ref: "fourth", title: "第四个", description: "x", sourceLabel: "x" },
];

function mount() {
  const onChange = vi.fn();
  const onSubmit = vi.fn();
  const skills = vi.fn(async (_workspaceId: string, query: string) =>
    OPTIONS.filter((one) => !query || one.title.includes(query) || one.ref.includes(query)),
  );
  function Harness() {
    const [value, setValue] = React.useState<JSONContent>(emptyDocument);
    return (
      <ChatComposer
        workspaceId="ws-1"
        value={value}
        onChange={(next) => {
          setValue(next);
          onChange(next);
        }}
        onSubmit={onSubmit}
        search={async () => []}
        skills={skills}
      />
    );
  }
  const view = render(<Harness />);
  const dom = view.container.querySelector(".ProseMirror") as HTMLElement & { editor?: Editor };
  return { view, editor: dom.editor as Editor, onChange, onSubmit, skills };
}

async function type(editor: Editor, text: string) {
  await act(async () => {
    editor.commands.focus("end");
    editor.commands.insertContent(text);
  });
}

const rows = () => [...document.querySelectorAll<HTMLElement>("[data-suggestion-menu] [data-skill-option]")];

describe("「/」点名技能", () => {
  it("菜单里列开着的技能:显示名、名字、说明", async () => {
    const { editor } = mount();
    await type(editor, "/");
    await waitFor(() => expect(rows().length).toBe(4));
    expect(rows()[0].textContent).toContain("做带货短视频");
    expect(rows()[0].textContent).toContain("short-video-ads");
    expect(document.querySelector("[data-suggestion-menu]")?.textContent).toContain("技能 —— 这一轮照它做");
  });

  it("挑一个:落成胶囊,正文写 /显示名,点名收得出名字", async () => {
    const { editor, onChange, view } = mount();
    await type(editor, "/带货");
    await waitFor(() => expect(rows().length).toBe(1));
    fireEvent.click(rows()[0]);
    await waitFor(() => expect(view.container.querySelector('[data-agent-skill="short-video-ads"]')).toBeTruthy());
    const document: JSONContent = onChange.mock.calls.at(-1)![0];
    expect(collectSkills(document)).toEqual(["short-video-ads"]);
    expect(documentText(document).trim()).toBe("/做带货短视频");
  });

  it("插件的技能带前缀也挑得中", async () => {
    const { editor, onChange } = mount();
    await type(editor, "/小窍门");
    await waitFor(() => expect(rows().length).toBe(1));
    fireEvent.click(rows()[0]);
    await waitFor(() => expect(collectSkills(onChange.mock.calls.at(-1)![0])).toEqual(["dev.example.tips:tips"]));
  });

  it("只在行首或空格后面触发:打网址不弹", async () => {
    const { editor, skills } = mount();
    await type(editor, "https://example.com/path");
    await new Promise((resolve) => setTimeout(resolve, 30));
    expect(rows().length).toBe(0);
    expect(skills).not.toHaveBeenCalled();
  });

  it("菜单开着时回车是选,不是发送", async () => {
    const { editor, onSubmit, onChange } = mount();
    await type(editor, "/品牌");
    await waitFor(() => expect(rows().length).toBe(1));
    await act(async () => {
      editor.view.dom.dispatchEvent(new KeyboardEvent("keydown", { key: "Enter", bubbles: true }));
    });
    expect(onSubmit).not.toHaveBeenCalled();
    await waitFor(() => expect(collectSkills(onChange.mock.calls.at(-1)![0])).toEqual(["brand-rules"]));
  });

  it(`最多点名 ${MAX_FORCED_SKILLS} 个`, async () => {
    const { editor, onChange } = mount();
    for (const query of ["带货", "品牌", "小窍门", "第四"]) {
      await type(editor, ` /${query}`);
      await waitFor(() => expect(rows().length).toBe(1));
      fireEvent.click(rows()[0]);
      await waitFor(() => expect(rows().length).toBe(0));
    }
    expect(collectSkills(onChange.mock.calls.at(-1)![0])).toEqual(["short-video-ads", "brand-rules", "dev.example.tips:tips"]);
  });
});

describe("发出去之后的气泡", () => {
  it("点名的技能画成同一颗胶囊", () => {
    const view = render(
      <ReferenceDocument
        document={{
          type: "doc",
          content: [{ type: "paragraph", content: [
            { type: "agentSkill", attrs: { ref: "short-video-ads", title: "做带货短视频" } },
            { type: "text", text: " 帮我做一条" },
          ] }],
        }}
      />,
    );
    const chip = view.container.querySelector('[data-agent-skill="short-video-ads"]');
    expect(chip?.textContent).toBe("/做带货短视频");
    expect(view.container.textContent).toContain("帮我做一条");
  });
});
