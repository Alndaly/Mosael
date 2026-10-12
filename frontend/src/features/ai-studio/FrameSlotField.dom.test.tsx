/** @vitest-environment jsdom */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen } from "@testing-library/react";
import React from "react";
import { describe, expect, it, vi } from "vitest";

/**
 * 一个槽位控件要把三件事表现出来:**能挂几份**、**现在挂了几份**、**为什么现在不能挂**。
 *
 * 三件事都只在界面上,后端拦得住但那已经太晚了 —— 用户挂满九张、点了生成、等了几秒,
 * 才被告知这一组根本不能和首帧一起用。
 */

vi.mock("@/app/preferences", () => ({ useI18n: () => (key: string) => key }));
vi.mock("@/components/app/image-preview", () => ({ useImagePreview: () => ({ openImagePreview: vi.fn() }) }));
vi.mock("@/api/client", () => ({
  assetFileUrl: (id: string) => `/f/${id}`,
  assetThumbnailUrl: (id: string) => `/t/${id}`,
  importAsset: vi.fn(),
}));

import { FrameSlotField, KeyframePairField } from "@/features/ai-studio/FrameSlotField";
import { EMPTY_SLOT } from "@/lib/sourceFrames";

function mount(ui: React.ReactElement) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={qc}>{ui}</QueryClientProvider>);
}

describe("参考图槽位", () => {
  it("计数说的是**真的挂了几张**,空槽不算", () => {
    const { container } = mount(
      <FrameSlotField
        role="reference_image"
        slots={[{ url: "", assetId: "a", assetName: "a.png" }, { ...EMPTY_SLOT }]}
        limit={9}
        onChange={vi.fn()}
        workspaceId="w"
      />,
    );
    expect(screen.getByText("1/9")).toBeTruthy();
    // 一格缩略图 + 一个加号格
    expect(container.querySelectorAll("img").length).toBe(1);
    expect(container.querySelectorAll("input[type=file]").length).toBe(1);
  });

  it("模型给了槽位名字(source_labels):填了的那一格标着它的名字,加号上写下一格叫什么", () => {
    // ComfyUI 一张工作流有几个读图节点时,它们是「人物」「背景」,而不是几个一样的「参考图」(ADR 0038 §4)
    const { container } = mount(
      <FrameSlotField
        role="reference_image"
        slots={[{ url: "", assetId: "a", assetName: "a.png" }]}
        limit={2}
        names={["人物", "背景"]}
        onChange={vi.fn()}
        workspaceId="w"
      />,
    );
    expect(container.querySelector("[data-slot-name]")?.getAttribute("data-slot-name")).toBe("人物");
    expect(screen.getByRole("button", { name: "人物 · a.png" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "背景" })).toBeTruthy();
  });

  /**
   * 槽位名字是**节点名**(ComfyUI 里用户自己起的,`Optional Load Image : …`),长度不由我们定。
   *
   * 维护者截图(暗色主题,首/尾帧那两格):标题左右各被切掉一截,连省略号都没有。量出来的原因是那一格的
   * `place-items-center` —— 里面的 `justify-items: center` 把「图标 + 名字」那一行按 **max-content** 排版:
   * 一行 300px 的面板里,120px 的格子里那一行量出来 310px(真浏览器实测),再由格子自己的 `overflow-hidden`
   * 从**两边**硬裁;里面的 `Truncate` 拿到的是文字本身的宽度(`clientWidth == scrollWidth`),省略号永远不触发。
   *
   * jsdom 没有排版、量不了宽,所以这里按源码判(和 design/truncateNeedsShrinkableBox 同一种做法):那一格
   * **不能**把里面的行按内容宽排版,那一行还得能收缩。真浏览器里前后量到的数写在 FrameSlotField.tsx 的 `TILE` 上头。
   */
  it("长槽位名:那一格不按内容宽排版,标题真的会截断,悬停看得到全文", async () => {
    const NAME = "Optional Load Image : a very long node title #10";
    mount(
      <FrameSlotField
        role="reference_image"
        slots={[{ ...EMPTY_SLOT }]}
        limit={2}
        names={[NAME, NAME]}
        onChange={vi.fn()}
        workspaceId="w"
      />,
    );
    const title = screen.getByText(NAME);
    //: 截断走仓库的 `Truncate`(真被截断了悬停才出说明,说明里是全文)。
    expect(title.className).toContain("truncate");
    const tile = title.closest("button")!;
    //: 按内容宽排版的那一格(justify-items: center)就是从两边硬裁 —— 名字只看得见中间一段,还没有省略号。
    expect(tile.className, "那一格不能把里面的行按内容宽排版(见 FrameSlotField.tsx 的 TILE)").not.toContain("place-items-center");
    expect(tile.className).toContain("min-w-0");
    //: `Truncate` 的父级:有宽度,而且能收缩(进 docs/CONVENTIONS 那条棘轮)。
    const row = title.parentElement!;
    expect(row.className).toContain("min-w-0");
    expect(row.className).toContain("flex");
    //: 全文一直在 DOM 里 —— 读屏念的和悬停看到的是同一份,不是被切过的那一段。
    expect(title.textContent).toBe(NAME);
    //: 这一格自己就是一条说明的触发器(`Truncate` 只在真被截断时开,见 components/ui/truncate)。
    expect(title.hasAttribute("data-hint-trigger")).toBe(true);

    //: 真被截断时,悬停出的说明里是**全文**(量法照 components/ui/truncate.dom.test.tsx)。
    Object.defineProperty(title, "scrollWidth", { value: 400, configurable: true });
    Object.defineProperty(title, "clientWidth", { value: 120, configurable: true });
    fireEvent.pointerEnter(title);
    fireEvent.pointerMove(title);
    expect((await screen.findByRole("tooltip")).textContent).toBe(NAME);
  });

  it("加到上限就不再给加号 —— 上限是接口的硬约束,不是建议", () => {
    const { container } = mount(
      <FrameSlotField
        role="reference_video"
        slots={[{ url: "", assetId: "a", assetName: "a.mp4" }]}
        limit={1}
        onChange={vi.fn()}
        workspaceId="w"
      />,
    );
    expect(container.querySelector("input[type=file]")).toBeNull();
  });

  it("参考图能一次选多个 —— 挂九张让人点九次是没道理的", () => {
    const { container } = mount(
      <FrameSlotField role="reference_image" slots={[{ ...EMPTY_SLOT }]} limit={9} onChange={vi.fn()} workspaceId="w" />,
    );
    expect(container.querySelector("input[type=file]")?.hasAttribute("multiple")).toBe(true);
  });

  it("只收一份的角色不给多选", () => {
    const { container } = mount(
      <FrameSlotField role="source_video" slots={[{ ...EMPTY_SLOT }]} limit={1} onChange={vi.fn()} workspaceId="w" />,
    );
    expect(container.querySelector("input[type=file]")?.hasAttribute("multiple")).toBe(false);
  });

  it("面板里不再有 URL 输入框", () => {
    // 那一栏几乎没人用(素材本来就在素材库里),却让每个角色多占两行。外链这条路本身留着,
    // 智能体和工作流照样能发 <role>_url,只是不再占据面板。
    const { container } = mount(
      <FrameSlotField role="reference_image" slots={[{ ...EMPTY_SLOT }]} limit={9} onChange={vi.fn()} workspaceId="w" />,
    );
    expect(container.querySelector("input[type=text]")).toBeNull();
  });

  it("上限为 1 时不显示计数 —— 1/1 是句废话", () => {
    mount(
      <FrameSlotField role="source_video" slots={[{ ...EMPTY_SLOT }]} limit={1} onChange={vi.fn()} workspaceId="w" />,
    );
    expect(screen.queryByText("0/1")).toBeNull();
  });

  it("被另一组锁住时说清楚为什么,而不是只灰掉", () => {
    // 只灰不说的话,用户看到的是一个"坏了"的控件,而不是"这条路我已经选了另一条"。
    mount(
      <FrameSlotField
        role="reference_image"
        slots={[{ ...EMPTY_SLOT }]}
        limit={9}
        onChange={vi.fn()}
        workspaceId="w"
        disabled
        disabledReason="不能一起用"
      />,
    );
    expect(screen.getByText("不能一起用")).toBeTruthy();
    // 锁住时连加号格都不画 —— 留一个点不动的按钮,用户点了没反应,那比直接没有更费解。
    const { container } = mount(
      <FrameSlotField
        role="reference_image"
        slots={[{ ...EMPTY_SLOT }]}
        limit={9}
        onChange={vi.fn()}
        workspaceId="w"
        disabled
        disabledReason="不能一起用"
      />,
    );
    expect(container.querySelector("input[type=file]")).toBeNull();
  });
});

describe("蒙版那一格", () => {
  /**
   * 蒙版能**画出来**(ADR 0056 第二步):空槽那一格并排多一格「画一张」——上传那条路原样留着。
   *
   * 「这一格能画」由调用方说(onDrawMask / onEditMask):控件自己不发明这条路,也不在别的角色上长出一支笔。
   */
  it("调用方说能画:空槽多一格「画一张」,上传那一格照旧", () => {
    const onDrawMask = vi.fn();
    const { container } = mount(
      <FrameSlotField
        role="mask"
        slots={[{ ...EMPTY_SLOT }]}
        limit={1}
        onChange={vi.fn()}
        workspaceId="w"
        onDrawMask={onDrawMask}
      />,
    );
    //: 上传那一格还在(点它还是选文件),「画一张」是并排的第二格。
    expect(container.querySelector("input[type=file]")).toBeTruthy();
    expect(screen.getByRole("button", { name: "maskUpload" })).toBeTruthy();
    screen.getByRole("button", { name: "maskDraw" }).click();
    expect(onDrawMask).toHaveBeenCalledTimes(1);
  });

  it("别的角色没有这一格 —— 哪怕调用方把回调传下来了", () => {
    //: 传错角色(或者在音频格上顺手传一个)时不该在旁边长出一支笔。
    mount(
      <FrameSlotField
        role="reference_image"
        slots={[{ ...EMPTY_SLOT }]}
        limit={9}
        onChange={vi.fn()}
        workspaceId="w"
        onDrawMask={vi.fn()}
        onEditMask={vi.fn()}
      />,
    );
    expect(screen.queryByRole("button", { name: "maskDraw" })).toBeNull();
    expect(screen.queryByRole("button", { name: "maskEdit" })).toBeNull();
  });

  it("没人说能画时,还是原来那一个加号(控件不自己发明入口)", () => {
    mount(
      <FrameSlotField role="mask" slots={[{ ...EMPTY_SLOT }]} limit={1} onChange={vi.fn()} workspaceId="w" />,
    );
    expect(screen.queryByRole("button", { name: "maskDraw" })).toBeNull();
    expect(screen.queryByRole("button", { name: "maskUpload" })).toBeNull();
  });

  it("已经填了的那一格:角一个「编辑蒙版」,点它把那一格交回调用方(带着它当底稿)", () => {
    const onEditMask = vi.fn();
    const slot = { url: "", assetId: "m1", assetName: "蒙版 · scene.png" };
    mount(
      <FrameSlotField
        role="mask"
        slots={[slot]}
        limit={1}
        onChange={vi.fn()}
        workspaceId="w"
        onEditMask={onEditMask}
      />,
    );
    screen.getByRole("button", { name: "maskEdit" }).click();
    expect(onEditMask).toHaveBeenCalledWith(slot);
  });
});

describe("视频输入槽位", () => {  it("待编辑的视频收 video/*,不是 image/*", () => {
    // 收 image/* 的话,用户在系统文件面板里一个视频都点不亮。
    const { container } = mount(
      <FrameSlotField role="source_video" slots={[{ ...EMPTY_SLOT }]} limit={1} onChange={vi.fn()} workspaceId="w" />,
    );
    expect(container.querySelector("input[type=file]")?.getAttribute("accept")).toBe("video/*");
  });

  it("参考音频收 audio/*", () => {
    const { container } = mount(
      <FrameSlotField role="reference_audio" slots={[{ ...EMPTY_SLOT }]} limit={3} onChange={vi.fn()} workspaceId="w" />,
    );
    expect(container.querySelector("input[type=file]")?.getAttribute("accept")).toBe("audio/*");
  });
});


describe("首尾帧是一对", () => {
  const filled = (id: string) => [{ url: "", assetId: id, assetName: id }];

  it("并排两格,中间一个交换按钮", () => {
    mount(
      <KeyframePairField
        first={filled("a")}
        last={filled("b")}
        showLast
        onChange={vi.fn()}
        workspaceId="w"
      />,
    );
    expect(screen.getByRole("button", { name: "genSwapKeyframes" })).toBeTruthy();
  });

  it("交换就是把两边对调,不用删掉重传", () => {
    // 「拍反了」是最常见的手误,删两张重传是最笨的补救。
    const onChange = vi.fn();
    mount(
      <KeyframePairField first={filled("a")} last={filled("b")} showLast onChange={onChange} workspaceId="w" />,
    );
    screen.getByRole("button", { name: "genSwapKeyframes" }).click();
    expect(onChange).toHaveBeenCalledWith({ first: filled("b"), last: filled("a") });
  });

  it("只挂了一边时换不动 —— 那不是对调,是搬家", () => {
    mount(
      <KeyframePairField first={filled("a")} last={[{ ...EMPTY_SLOT }]} showLast onChange={vi.fn()} workspaceId="w" />,
    );
    expect(screen.getByRole("button", { name: "genSwapKeyframes" }).hasAttribute("disabled")).toBe(true);
  });

  it("模型不认尾帧时不画箭头,也不画第二格", () => {
    mount(
      <KeyframePairField
        first={[{ ...EMPTY_SLOT }]}
        last={[{ ...EMPTY_SLOT }]}
        showLast={false}
        onChange={vi.fn()}
        workspaceId="w"
      />,
    );
    expect(screen.queryByRole("button", { name: "genSwapKeyframes" })).toBeNull();
  });
});
