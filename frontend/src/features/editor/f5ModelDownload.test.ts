import { describe, expect, it } from "vitest";

import type { F5Model } from "@/api/domains/speech";

import { f5DownloadPercent, f5DownloadPhase, f5ModelsPollMs } from "./f5ModelDownload";

function model(patch: Partial<F5Model> = {}): F5Model {
  return {
    id: "ja",
    label: "日语模型",
    languages: ["ja"],
    note: "",
    expected_bytes: 5_400_000_000,
    total_is_estimate: false,
    installed: false,
    status: "missing",
    progress: 0,
    downloaded_bytes: 0,
    total_bytes: null,
    speed_bps: 0,
    eta_seconds: null,
    message: "",
    error: "",
    failed_at: "",
    ...patch,
  };
}

describe("权重下载那一行的状态", () => {
  it("百分比按字节算,不按后端那个可能停在 0 的分数 —— 截图里的「0%」就是照分数画出来的", () => {
    const row = model({ status: "downloading", downloaded_bytes: 1_200_000_000, total_bytes: 5_400_000_000, progress: 0 });
    expect(f5DownloadPercent(row)).toBe(22);
  });

  it("总量未知就是 null:不编一个 0%(那和「卡住了」长得一模一样)", () => {
    expect(f5DownloadPercent(model({ status: "downloading", downloaded_bytes: 500_000_000, total_bytes: null }))).toBeNull();
    expect(f5DownloadPercent(model({ status: "downloading", downloaded_bytes: 500_000_000, total_bytes: 0 }))).toBeNull();
  });

  it("1% 以下保留一位小数 —— 5.4 GB 在慢网络下,整数百分比会一直是 0", () => {
    expect(f5DownloadPercent(model({ status: "downloading", downloaded_bytes: 20_000_000, total_bytes: 5_400_000_000 }))).toBe(0.4);
  });

  it("量到的字节到顶也不报 100 —— 100% 由「检查点在盘上」说", () => {
    expect(f5DownloadPercent(model({ status: "downloading", downloaded_bytes: 5_400_000_000, total_bytes: 5_400_000_000 }))).toBe(99);
  });

  it("「查不到状态」压过手里那份旧数据:轮询失败时不能当成还在下 / 已经不在下", () => {
    expect(f5DownloadPhase(model({ status: "downloading" }), true)).toBe("unknown");
    expect(f5DownloadPhase(model({ status: "failed" }), true)).toBe("unknown");
    expect(f5DownloadPhase(model({ status: "downloading" }), false)).toBe("downloading");
    expect(f5DownloadPhase(model({ status: "failed" }), false)).toBe("failed");
    expect(f5DownloadPhase(model(), false)).toBe("missing");
  });

  it("还在下就 1.5 秒问一次,都结束了 8 秒 —— 失败了也不停,否则下一次变化永远看不到", () => {
    expect(f5ModelsPollMs([model({ status: "installed" }), model({ status: "downloading" })])).toBe(1500);
    expect(f5ModelsPollMs([model({ status: "failed" })])).toBe(8000);
    expect(f5ModelsPollMs([model()])).toBe(8000);
    expect(f5ModelsPollMs(undefined)).toBe(8000);
  });
});
