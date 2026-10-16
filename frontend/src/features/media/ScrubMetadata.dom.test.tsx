/** @vitest-environment jsdom */
/**
 * 清除元数据(ADR 0062)在素材详情里的那一条链。维护者拍板的是「素材详情页一个动作」,所以这里盯的是:
 *
 * - **入口只给视频**(非视频一个都不出现);
 * - **确认不是一句话**:那个开关(默认关)、它的后果原文、「原素材不动」都在;
 * - 确认之后拿到 `JobOut`、在跑时看得见,任务那条走**既有那一套**(任务中心);
 * - 跑完的出口:打开那份干净素材、查看对账(两份都对上 id),以及十道门 / 清掉了什么 / warnings 如实摊开。
 *
 * 上游(接口形状、门禁、对账文本)在 backend/tests/test_media_scrub.py;这里只管界面把它们读对。
 */
import React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { ScrubReport } from "@/api/domains/assets";

/** 这一份测试里被 `vi.mock` 换掉的接口。逐个重置,免得用例之间互相影响。 */
const api = vi.hoisted(() => ({
  listJobs: vi.fn(async () => [] as unknown[]),
  getJob: vi.fn(async (_id: string) => ({}) as unknown),
  getAsset: vi.fn(async (_id: string) => ({}) as unknown),
  startScrub: vi.fn(async (_id: string, _provenance = false) => ({}) as unknown),
  getScrubReport: vi.fn(async (_id: string) => ({ asset_id: _id, status: "none", markdown: "" }) as ScrubReport),
}));

vi.mock("@/api/client", async (original) => ({
  ...(await original<typeof import("@/api/client")>()),
  listJobs: api.listJobs,
  getJob: api.getJob,
  getAsset: api.getAsset,
  startScrub: api.startScrub,
  getScrubReport: api.getScrubReport,
}));

//: 跟着中文表走(和 AssetPreviewModal.shots.dom.test.tsx 同一套):要断言那一句后果原文真的渲染出来了。
vi.mock("@/app/preferences", async () => {
  const { zhCN } = await import("@/app/messages/zh-CN");
  const table = zhCN as unknown as Record<string, string>;
  return { useI18n: () => (key: string) => table[key] ?? key };
});

vi.mock("@/components/app/MediaPreviewPlayer", () => ({ MediaPreviewPlayer: () => <div data-media-preview-player="" /> }));
vi.mock("@/components/app/image-preview", () => ({ useImagePreview: () => ({ openImagePreview: vi.fn(), isImagePreviewOpen: false }) }));
vi.mock("@/features/entities/AssetEntities", () => ({ AssetEntitiesList: () => null }));
vi.mock("@/features/media/DocumentReader", () => ({ DocumentReader: () => null }));
vi.mock("@/lib/download", () => ({ saveAssetToDisk: vi.fn() }));
vi.mock("@/features/notes/SaveToNote", () => ({ SaveToNote: () => null }));

import { AssetPreviewModal } from "./AssetPreviewModal";

const videoAsset = {
  id: "clip",
  workspace_id: "ws",
  name: "片头.mp4",
  original_filename: "opening.mp4",
  kind: "video",
  source: "imported",
  tags: [],
  media_info: { width: 1920, height: 1080, duration: 40, fps: 24 },
};

/** 一份跑完的清除任务:新素材 `clip-clean`,十道门里 G5 没过(软门)、两个计数、一条 warnings。 */
const scrubJob = {
  id: "job-scrub",
  kind: "scrub_metadata",
  status: "succeeded",
  message: "元数据已清除",
  progress: 1,
  payload: { asset_id: "clip", subject: "片头.mp4", provenance: false },
  result: {
    asset_id: "clip-clean",
    source_asset_id: "clip",
    report: "# 清除元数据 · 对账\n\n清理前的发现……\n",
    gates: [
      { id: "G1", name: "容器键与 UUID 盒子", ok: true, detail: "" },
      { id: "G2", name: "只剩画面和声音的轨", ok: true, detail: "" },
      { id: "G3", name: "SEI(编码器设置 / 设备串)", ok: true, detail: "" },
      { id: "G4", name: "compressorname(stsd 里那 32 字节)", ok: true, detail: "" },
      { id: "G5", name: "AAC 帧内元素(DSE / 填充)", ok: false, detail: "还有 2 个写过东西的填充元素" },
      { id: "G6", name: "画面载荷逐字节相同", ok: true, detail: "" },
      { id: "G7", name: "声音载荷只差被清掉的那几段", ok: true, detail: "" },
      { id: "G8", name: "样本表逐项相同", ok: true, detail: "" },
      { id: "G9", name: "输出仍能解码,画面与声音解码后一致", ok: true, detail: "" },
      { id: "G10", name: "流式:没有整份读进内存", ok: true, detail: "" },
    ],
    gates_ok: false,
    removed: {
      sei_nals: 3, sei_payloads: 5, aac_dse: 0, aac_dse_zeroed: 0, aac_fill_zeroed: 2,
      compressorname: 1, uuid_boxes: 0, data_tracks: 2, container_keys: 7,
      provenance_kept: 1, provenance_removed: 0,
    },
    provenance: false,
    warnings: ["视频轨 av1 不支持按字节重写 SEI,这一层没做"],
  },
};

/** 还在跑的那条(载荷里是这份素材)。 */
const runningJob = {
  id: "job-running",
  kind: "scrub_metadata",
  status: "running",
  message: "正在清除元数据",
  progress: 0.4,
  payload: { asset_id: "clip", subject: "片头.mp4" },
};

function mount(asset: unknown = videoAsset) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: Infinity } } });
  return render(
    <QueryClientProvider client={client}>
      <AssetPreviewModal asset={asset as never} onClose={vi.fn()} />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  api.listJobs.mockReset().mockResolvedValue([]);
  api.getJob.mockReset().mockResolvedValue({});
  api.getAsset.mockReset().mockResolvedValue({});
  api.startScrub.mockReset().mockResolvedValue({ ...runningJob, id: "job-new" });
  api.getScrubReport.mockReset().mockResolvedValue({ asset_id: "clip", status: "none", markdown: "" });
});

afterEach(cleanup);

describe("入口", () => {
  it("视频详情里有「清除元数据…」,非视频没有", async () => {
    mount();
    expect(screen.getByRole("button", { name: /清除元数据/ })).toBeInTheDocument();
    cleanup();

    for (const kind of ["image", "audio", "document"]) {
      mount({ ...videoAsset, id: `x-${kind}`, kind });
      expect(screen.queryByRole("button", { name: /清除元数据/ })).toBeNull();
      cleanup();
    }
  });
});

describe("确认面板", () => {
  it("provenance 默认关;勾上之后 POST 的 body 里是 true", async () => {
    mount();
    fireEvent.click(screen.getByRole("button", { name: /清除元数据/ }));

    const toggle = await screen.findByRole("switch", { name: "也抹掉 AI 生成标记(C2PA)" });
    //: 默认关 —— 和后端 policy.PROVENANCE["default"] 一致。
    expect(toggle.getAttribute("data-state")).toBe("unchecked");

    fireEvent.click(toggle);
    expect(toggle.getAttribute("data-state")).toBe("checked");

    //: 「原素材不动,会多出一份干净素材」写清了。
    expect(document.querySelector("[data-scrub-confirm]")?.textContent).toContain("原素材一个字节都不动");

    fireEvent.click(screen.getByRole("button", { name: "开始清除" }));
    await waitFor(() => expect(api.startScrub).toHaveBeenCalledWith("clip", true));
  });

  it("默认关时不带 provenance(传 false),后果原文照样渲染出来", async () => {
    mount();
    fireEvent.click(screen.getByRole("button", { name: /清除元数据/ }));

    const consequence = await waitFor(() => {
      const element = document.querySelector<HTMLElement>("[data-scrub-consequence]");
      expect(element).not.toBeNull();
      return element!;
    });
    expect(consequence.textContent).toContain("抹掉「这段是 AI 生成的」这个声明");
    expect(consequence.textContent).toContain("这可能让发布违规");

    fireEvent.click(screen.getByRole("button", { name: "开始清除" }));
    await waitFor(() => expect(api.startScrub).toHaveBeenCalledWith("clip", false));
  });

  it("排不上时说得出为什么(走那一份失败卡),面板不关", async () => {
    api.startScrub.mockRejectedValue(new Error("这份素材在盘上找不到了"));
    mount();
    fireEvent.click(screen.getByRole("button", { name: /清除元数据/ }));
    fireEvent.click(screen.getByRole("button", { name: "开始清除" }));

    await waitFor(() => expect(screen.getByText("这份素材在盘上找不到了")).toBeInTheDocument());
    //: 面板还开着 —— 用户能再按一次,而不是"点了一下什么都没发生"。
    expect(screen.getByRole("button", { name: "开始清除" })).toBeInTheDocument();
  });
});

describe("跑起来之后", () => {
  it("拿到 JobOut,并在进行中的状态里看得见;任务中心被叫起来", async () => {
    const openTasks = vi.fn();
    window.addEventListener("mosael:open-tasks", openTasks);
    mount();
    fireEvent.click(screen.getByRole("button", { name: /清除元数据/ }));
    fireEvent.click(screen.getByRole("button", { name: "开始清除" }));

    //: 拿到的是那条 JobOut(确认面板随即收起)。
    await waitFor(() => expect(api.startScrub).toHaveBeenCalled());
    await waitFor(() => expect(screen.queryByRole("button", { name: "开始清除" })).toBeNull());

    //: 任务列表还没回来之前,那一块按「进行中」显示。
    await waitFor(() => expect(document.querySelector("[data-scrub-running]")).not.toBeNull());
    expect(document.querySelector("[data-scrub-running]")).toHaveTextContent("清除元数据进行中…");

    //: 进度和取消在任务中心(既有那一套):排上之后把它打开,带上那条任务的 id。
    await waitFor(() => expect(openTasks).toHaveBeenCalled());
    const event = openTasks.mock.calls[0][0] as CustomEvent<string>;
    expect(event.type).toBe("mosael:open-tasks");
    expect(event.detail).toBe("job-new");
    window.removeEventListener("mosael:open-tasks", openTasks);
  });

  it("上一次没成时把那一句原因说出来,不留下一个空块", async () => {
    api.listJobs.mockResolvedValue([{
      id: "job-failed",
      kind: "scrub_metadata",
      status: "failed",
      message: "清除元数据 失败",
      payload: { asset_id: "clip", subject: "片头.mp4" },
      error: "清除后的产出没有通过硬门禁(G6),已丢弃,没有登记进素材库",
      error_summary: "清除后的产出没有通过硬门禁(G6),已丢弃,没有登记进素材库",
    }]);
    mount();
    const card = await waitFor(() => {
      const element = document.querySelector<HTMLElement>("[data-scrub-failed]");
      expect(element).not.toBeNull();
      return element!;
    });
    expect(card.textContent).toContain("没有通过硬门禁(G6)");
  });

  it("列表里那条在跑时,那一行用的是任务自己的话", async () => {
    api.listJobs.mockResolvedValue([runningJob]);
    mount();
    const row = await waitFor(() => {
      const element = document.querySelector<HTMLElement>("[data-scrub-panel] [data-scrub-running]");
      expect(element).not.toBeNull();
      return element!;
    });
    expect(row).toHaveTextContent("正在清除元数据");
  });
});

describe("跑完的出口", () => {
  beforeEach(() => {
    api.listJobs.mockResolvedValue([scrubJob]);
    api.getJob.mockResolvedValue(scrubJob);
    api.getScrubReport.mockResolvedValue({
      asset_id: "clip-clean",
      status: "ready",
      markdown: "# 清除元数据 · 对账\n\n## 门禁结果\n\n- G1 过\n",
    });
  });

  it("「打开这份干净素材」指向新素材那个 id", async () => {
    mount();
    const open = await screen.findByRole("button", { name: /打开这份干净素材/ });
    fireEvent.click(open);
    //: 走的是详情页那条跳转(`openSource` → `getAsset`):拿到的是**新素材**那个 id,不是被清的这一份。
    await waitFor(() => expect(api.getAsset).toHaveBeenCalledWith("clip-clean"));
  });

  it("「查看对账」把那份 Markdown 渲染出来,而且读的是干净素材的 id", async () => {
    mount();
    await waitFor(() => expect(api.getScrubReport).toHaveBeenCalledWith("clip-clean"));
    fireEvent.click(await screen.findByRole("button", { name: /查看对账/ }));
    //: 既有的那套 Markdown 渲染器(AgentMarkdown → Streamdown)把标题渲染成标题,不是一行原文。
    await waitFor(() =>
      expect(document.querySelector("[data-scrub-report-body] h1")?.textContent).toBe("清除元数据 · 对账"),
    );
  });

  it("对账是 status:none 时也说人话,不报错、不留空白", async () => {
    api.getScrubReport.mockResolvedValue({ asset_id: "clip-clean", status: "none", markdown: "" });
    mount();
    const btn = await screen.findByRole("button", { name: /查看对账/ });
    console.log("BEFORE_CLICK_BODY", document.querySelector("[data-scrub-report-body]") ? "EXISTS" : "NONE");
    fireEvent.click(btn);
    console.log("AFTER_CLICK_BODY", document.querySelector("[data-scrub-report-body]")?.innerHTML.slice(0, 200) ?? "NONE");
    await waitFor(() => expect(document.querySelector("[data-scrub-report-body]")?.textContent).toContain("还没有对账"));
  });

  it("十道门逐条:过 / 没过 + 说明,硬门标出来", async () => {
    mount();
    await waitFor(() => expect(document.querySelectorAll("[data-scrub-gate]")).toHaveLength(10));
    expect(document.querySelector('[data-scrub-gate="G5"]')?.textContent).toContain("没过");
    expect(document.querySelector('[data-scrub-gate="G5"]')?.textContent).toContain("还有 2 个写过东西的填充元素");
    expect(document.querySelector('[data-scrub-gate="G6"]')?.textContent).toContain("过");
    expect(document.querySelector('[data-scrub-gate="G6"]')?.textContent).toContain("硬门");
    //: gates_ok 为假:显眼(警告色的一句话),但不是"出错了"。
    expect(document.querySelector("[data-scrub-gates]")?.textContent).toContain("有软门没过");
  });

  it("removed 用中文说清每一项(SEI / AAC 的 DSE / 容器键……)", async () => {
    mount();
    await waitFor(() => expect(document.querySelector("[data-scrub-removed]")).not.toBeNull());
    const removed = document.querySelector("[data-scrub-removed]")?.textContent ?? "";
    expect(removed).toContain("SEI 换成等长填充:3 条");
    expect(removed).toContain("SEI 载荷抹掉:5 段");
    expect(removed).toContain("AAC 填充元素里写过的字节清零:2 处");
    expect(removed).toContain("容器键不在输出里:7 个");
    expect(removed).toContain("数据轨整条不留在输出里:2 条");
    //: 计数是 0 的那几项不摆出来(「清了 0 条」不是清账,是噪音)。
    expect(removed).not.toContain("AAC 的 DSE");
  });

  it("warnings 看得见", async () => {
    mount();
    await waitFor(() =>
      expect(document.querySelector("[data-scrub-warning]")?.textContent).toContain("av1 不支持按字节重写 SEI"),
    );
  });
});
