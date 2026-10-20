/** @vitest-environment jsdom */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import React from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

/**
 * 管理 → 引擎 → 转写:每个模型是卡片里的一行(和管理页其余的行同一套版式),而下载、进度、
 * 「已安装」、运行环境检测、失败重试照旧。
 */

vi.mock("@/app/preferences", () => ({
  useI18n: () => (key: string) => key,
  usePreferences: () => ({ locale: "zh-CN" }),
}));

const base = {
  detail: "中文识别", status: "missing", runtime_ready: false, runtime_checked: true, downloaded_bytes: 0,
  total_bytes: 0, expected_bytes: 973_000_000, total_is_estimate: false, speed_bps: 0, eta_seconds: null, message: "",
  is_default: false,
};
let models: Array<Record<string, unknown>> = [];
const downloads: string[] = [];
//: 「设为默认」点过哪几个。
const defaultCalls: string[] = [];
//: 接口拒了一次时的原话(toast 会把它显示出来)。
const errors: string[] = [];
let rejectDefault: string | null = null;
//: 这份列表被问了几次。「装完之后界面跟着变」= 它再问了一次,而这一次后端答的是新状态。
const reads: string[] = [];

vi.mock("sonner", () => ({
  toast: { error: (message: string) => errors.push(message) },
}));

vi.mock("@/api/client", () => ({
  listAsrModels: () => {
    reads.push("read");
    return Promise.resolve(models);
  },
  downloadAsrModel: (id: string) => {
    downloads.push(id);
    return Promise.resolve(models[0]);
  },
  setDefaultAsrModel: (id: string) => {
    defaultCalls.push(id);
    if (rejectDefault) return Promise.reject(new Error(rejectDefault));
    // 后端是真的存下来了:再问一次列表时,它也会照新答案回。
    models = models.map((one) => ({ ...one, is_default: one.id === id }));
    return Promise.resolve(models.find((one) => one.id === id));
  },
}));

import { AsrModelsSection } from "./AsrModelsSection";
import { ADMIN_CARD } from "./adminLayout";

function renderSection(rows: Array<Record<string, unknown>>) {
  models = rows;
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <AsrModelsSection />
    </QueryClientProvider>,
  );
  return client;
}

//: 节顶那条「默认模型」里也会写着默认的那一个名字 —— 找**行**不能只认第一个同名字符串。
const rowOf = async (label: string) => {
  const row = (await screen.findAllByText(label))
    .map((one) => one.closest("[data-admin-row]"))
    .find((one): one is HTMLElement => one instanceof HTMLElement);
  if (!row) throw new Error(`没有「${label}」那一行`);
  return row;
};

beforeEach(() => {
  downloads.length = 0;
  defaultCalls.length = 0;
  errors.length = 0;
  rejectDefault = null;
  reads.length = 0;
});

describe("转写模型", () => {
  it("每个模型是卡片里的一行:引擎族和大小是名字旁的小字,不是描边的大写小标", async () => {
    renderSection([
      { ...base, id: "funasr", engine: "funasr", label: "FunASR(SenseVoice)" },
      { ...base, id: "whisperx", engine: "whisperx", label: "WhisperX" },
    ]);
    const row = await rowOf("FunASR(SenseVoice)");
    expect(row.parentElement?.className).toBe(ADMIN_CARD);
    expect(row).not.toHaveClass("border");
    expect(row).not.toHaveClass("rounded-lg");
    const meta = row.querySelector("[data-admin-row-meta]")!;
    expect(meta).toHaveTextContent("funasr · 973 MB");
    expect(meta).not.toHaveClass("uppercase");
    expect(within(row).getByText("中文识别")).toHaveAttribute("data-admin-row-description");
    // 两行是同一张卡片里的兄弟 —— 分隔线由卡片画。
    expect((await rowOf("WhisperX")).parentElement).toBe(row.parentElement);
  });

  it("点下载只下这一个", async () => {
    const user = userEvent.setup();
    renderSection([{ ...base, id: "funasr", engine: "funasr", label: "FunASR" }]);
    await user.click(within(await rowOf("FunASR")).getByRole("button", { name: /asrModelDownload/ }));
    await waitFor(() => expect(downloads).toEqual(["funasr"]));
  });

  it("装好且跑得起来:右边是已安装和「设为默认」,没有下载按钮", async () => {
    //: ≥2 个候选才存在「默认」(见 defaultRow.dom.test.tsx),所以这里给两个。
    renderSection([
      { ...base, id: "funasr", engine: "funasr", label: "FunASR", status: "installed", runtime_ready: true },
      { ...base, id: "whisperx", engine: "whisperx", label: "WhisperX" },
    ]);
    const row = await rowOf("FunASR");
    const state = within(row).getByText("asrModelInstalled").closest("[data-admin-row-state]");
    expect(state).toHaveAttribute("data-tone", "success");
    //: 已安装 = 能设默认(盘上有这份权重)。下载那一套按钮不该再出现。
    expect(within(row).getByRole("button", { name: /asrModelSetDefault/ })).toBeInTheDocument();
    expect(within(row).queryByRole("button", { name: /asrModelDownload|asrModelRetry|asrModelInstallRuntime/ })).toBeNull();
  });

  it("运行环境还没测完时说「正在检查」,不下结论也不摆下载按钮(默认仍可设:权重在盘上)", async () => {
    renderSection([
      { ...base, id: "funasr", engine: "funasr", label: "FunASR", status: "installed", runtime_checked: false },
      { ...base, id: "whisperx", engine: "whisperx", label: "WhisperX" },
    ]);
    const row = await rowOf("FunASR");
    expect(within(row).getByText("runtimeChecking")).toHaveAttribute("data-admin-row-note");
    expect(within(row).queryByRole("button", { name: /asrModelDownload|asrModelRetry|asrModelInstallRuntime/ })).toBeNull();
    //: 权重在盘上,只是还没探完环境 —— 设默认仍然成立(设默认看的是权重在不在)。
    expect(within(row).getByRole("button", { name: /asrModelSetDefault/ })).toBeInTheDocument();
    expect(row).not.toHaveTextContent("asrModelInstalled");
  });

  it("权重在盘上但跑不起来:说原因,按钮是装运行环境", async () => {
    renderSection([{ ...base, id: "funasr", engine: "funasr", label: "FunASR", status: "installed" }]);
    const row = await rowOf("FunASR");
    expect(within(row).getByText("asrModelNoRuntime")).toHaveAttribute("data-tone", "destructive");
    expect(within(row).getByRole("button", { name: /asrModelInstallRuntime/ })).toBeInTheDocument();
  });

  it("有分母时进度条横贯整行,右边报百分比", async () => {
    renderSection([
      {
        ...base, id: "funasr", engine: "funasr", label: "FunASR", status: "downloading",
        downloaded_bytes: 486_500_000, total_bytes: 973_000_000, speed_bps: 2_000_000,
      },
    ]);
    const row = await rowOf("FunASR");
    const footer = row.querySelector("[data-admin-row-footer]")!;
    expect(within(footer as HTMLElement).getByRole("progressbar")).toBeInTheDocument();
    expect(footer).toHaveTextContent("/");
    expect(row.querySelector("[data-admin-row-state]")).toHaveTextContent("50%");
    expect(within(row).queryByRole("button")).toBeNull();
  });

  it("没有分母(装运行环境)时不画进度条、不报 0%,在说明下面说正在做什么", async () => {
    renderSection([
      { ...base, id: "funasr", engine: "funasr", label: "FunASR", status: "downloading", message: "正在安装 torch" },
    ]);
    const row = await rowOf("FunASR");
    expect(row.querySelector("[data-admin-row-footer]")).toBeNull();
    expect(within(row).getByText("正在安装 torch").closest("[data-admin-row-note]")).not.toBeNull();
    expect(row.querySelector("[data-admin-row-state]")).not.toHaveTextContent("%");
  });

  it("失败原因原样显示,按钮变成重试", async () => {
    const user = userEvent.setup();
    renderSection([
      { ...base, id: "funasr", engine: "funasr", label: "FunASR", status: "failed", message: "连不上 ModelScope" },
    ]);
    const row = await rowOf("FunASR");
    expect(within(row).getByText("连不上 ModelScope").closest("[data-admin-row-note]")).toHaveAttribute(
      "data-tone",
      "destructive",
    );
    await user.click(within(row).getByRole("button", { name: /asrModelRetry/ }));
    await waitFor(() => expect(downloads).toEqual(["funasr"]));
  });

  /**
   * 用户报的那一幕:权重在盘上、环境其实也装好了,这一行却一直写着
   * 「模型已在磁盘上,但还没有能运行它的 Python 环境 —— 点右边装一次」,**刷新一次页面又对了**。
   *
   * 界面在环境还没装好的那一刻看到的是 `runtime_checked=true, runtime_ready=false` —— 一个
   * **定了的**答案。轮询的判据是"还有没答完的问题"(`runtime_checked=false`,或正在下,
   * 见 lib/pollWhileUnsettled),于是它就此停住;这一行的话也就定在那儿了。
   * 这正是用户说"刷新一下就好了"的形状:刷新之后整份列表重取一次,后端那时答的才是真答案。
   *
   * 所以这条钉的是那一半归前端的契约:**"定了"的答案变了之后,这一页必须再问一次,并照着新答案改口**。
   * (让它有机会变的那一半在后端:装环境那条路必须把新答案记在 `_probes` 里,见
   * backend/tests/test_asr_runtime_is_honest.py。)
   */
  it("那个「定了的」答案变了之后:再问一次就改口,不把旧话钉在页面上", async () => {
    const client = renderSection([
      { ...base, id: "funasr", engine: "funasr", label: "FunASR", status: "installed" },
    ]);
    const row = await rowOf("FunASR");
    expect(within(row).getByText("asrModelNoRuntime")).toBeInTheDocument();
    expect(reads).toHaveLength(1);

    // 环境装好了(或后端重新探明白了):同一个模型,现在是「能跑」。
    models = [{ ...base, id: "funasr", engine: "funasr", label: "FunASR", status: "installed", runtime_ready: true }];
    await act(() => client.invalidateQueries({ queryKey: ["asr-models"] }));

    // 再问一次 —— 而且要看到新答案,不是把上一轮那句话留在页面上。
    await waitFor(() => expect(reads.length).toBeGreaterThan(1));
    await waitFor(() => expect(within(row).getByText("asrModelInstalled")).toBeInTheDocument());
    expect(within(row).queryByText("asrModelNoRuntime")).toBeNull();
  });
});

/**
 * 用户报的那件事:五张卡(已安装)只有「已安装 / 下载」,没有**设为默认**。
 * 默认是这台机器的设定,所以只有部署管理员、且只有**已经装在盘上**的模型能设 ——
 * 设一份没装的,下一次转写照样得先下几个 GB,「默认」只是一句空话。
 */
describe("设为默认", () => {
  it("已安装的卡上能设默认;已默认的显示「默认模型」且不能再点", async () => {
    const user = userEvent.setup();
    renderSection([
      { ...base, id: "funasr", engine: "funasr", label: "FunASR", status: "installed", runtime_ready: true },
      { ...base, id: "whisperx-large-v3", engine: "whisperx", label: "WhisperX Large v3", status: "installed", runtime_ready: true, is_default: true },
    ]);
    const funasr = await rowOf("FunASR");
    //: 已默认的那一个只说「默认模型」,不再是一颗能点的按钮。
    const large = await rowOf("WhisperX Large v3");
    expect(within(large).getByText("asrModelIsDefault")).toHaveAttribute("data-admin-row-state");
    expect(within(large).queryByRole("button", { name: /asrModelSetDefault/ })).toBeNull();

    await user.click(within(funasr).getByRole("button", { name: /asrModelSetDefault/ }));
    await waitFor(() => expect(defaultCalls).toEqual(["funasr"]));
  });

  it("没安装的卡上没有「设为默认」", async () => {
    renderSection([
      { ...base, id: "funasr", engine: "funasr", label: "FunASR" },
      { ...base, id: "whisperx", engine: "whisperx", label: "WhisperX", status: "installed", runtime_ready: true },
    ]);
    const row = await rowOf("FunASR");
    expect(within(row).queryByRole("button", { name: /asrModelSetDefault/ })).toBeNull();
  });

  it("设完立刻反映:从后端重新读整张列表,而不是只改本地那一个开关", async () => {
    const user = userEvent.setup();
    renderSection([
      { ...base, id: "funasr", engine: "funasr", label: "FunASR", status: "installed", runtime_ready: true },
      { ...base, id: "whisperx-large-v3", engine: "whisperx", label: "WhisperX Large v3", status: "installed", runtime_ready: true, is_default: true },
    ]);
    expect(reads).toHaveLength(1);

    await user.click(within(await rowOf("FunASR")).getByRole("button", { name: /asrModelSetDefault/ }));

    //: **再问一次后端**:默认只有一个,别的行(原来是默认的那一行)也得跟着改口。
    await waitFor(() => expect(reads.length).toBeGreaterThan(1));
    await waitFor(async () => {
      expect(within(await rowOf("FunASR")).getByText("asrModelIsDefault")).toBeInTheDocument();
      expect(within(await rowOf("WhisperX Large v3")).queryByText("asrModelIsDefault")).toBeNull();
    });
  });

  it("接口拒了要说清原因 —— 不是按钮点一下什么都不发生", async () => {
    rejectDefault = "「WhisperX Small」还没安装,不能设成默认 —— 先在右边点「下载」,装好之后再设。";
    const user = userEvent.setup();
    renderSection([
      { ...base, id: "whisperx-small", engine: "whisperx", label: "WhisperX Small", status: "installed" },
      { ...base, id: "whisperx-large-v3", engine: "whisperx", label: "WhisperX Large v3", status: "installed", runtime_ready: true },
    ]);

    await user.click(within(await rowOf("WhisperX Small")).getByRole("button", { name: /asrModelSetDefault/ }));

    await waitFor(() => expect(errors).toEqual([rejectDefault]));
  });
});
