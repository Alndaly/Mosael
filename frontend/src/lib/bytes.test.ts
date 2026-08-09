import { describe, expect, it } from "vitest";

import { formatBytes, formatSpeed } from "./bytes";

describe("formatBytes", () => {
  it("小文件不再显示成 0 MB —— 参考音频就是几百 KB 的量级", () => {
    expect(formatBytes(320_000)).toBe("320 KB");
    expect(formatBytes(1_200)).toBe("1 KB");
  });

  it("MB / GB 的写法和原来一致 —— 设置页的下载进度靠它", () => {
    expect(formatBytes(1_500_000_000)).toBe("1.5 GB");
    expect(formatBytes(250_000_000)).toBe("250 MB");
  });

  it("零和负数不崩", () => {
    expect(formatBytes(0)).toBe("0 MB");
    expect(formatBytes(-1)).toBe("0 MB");
  });
});

describe("formatSpeed", () => {
  it("停着的时候不显示速度,而不是显示 0", () => {
    expect(formatSpeed(0)).toBe("");
  });

  it("按量级换单位", () => {
    expect(formatSpeed(2_500_000)).toBe("2.5 MB/s");
    expect(formatSpeed(120_000)).toBe("120 KB/s");
  });
});
