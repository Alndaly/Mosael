/**
 * 画质档位。
 *
 * 起因:实测发现不带登录态的 YouTube 现在只给到 **360p**(android 客户端是唯一能取到流的,
 * 而它只返回低清格式)。这时摆一个「2160p」让人选、下回来一个 360p,是让界面替站点撒谎。
 *
 * 所以档位来自**这条链接真有的画质**;拿不到时(播放列表只做浅层探测)才给通用档位 ——
 * 那时"未知"是诚实的,而"只有这几档"是编的。
 */
import { describe, expect, it } from "vitest";

import { knownBestHeight, qualityHint, qualityOptions, QUALITY_STEPS } from "./urlImportQuality";

describe("画质档位", () => {
  it("知道实际画质时,不列比它更高的档 —— 选了也只会拿到同一个流", () => {
    expect(qualityOptions([1080, 720, 480, 360])).toEqual([0, 720, 480, 360]);
  });

  it("只有 360p 时就只剩「不限」—— 而不是摆一排选了没用的档位", () => {
    expect(qualityOptions([360, 180, 90])).toEqual([0]);
  });

  it("不知道画质时给通用档位 —— 播放列表只做浅层探测,这时「未知」是诚实的", () => {
    expect(qualityOptions([])).toEqual([0, ...QUALITY_STEPS]);
  });

  it("「不限」永远在第一位:多数人要的就是最好的那一档", () => {
    expect(qualityOptions([1080])[0]).toBe(0);
    expect(qualityOptions([])[0]).toBe(0);
  });

  it("一批里能确证的最高画质:有一条给出就算数,一条都没有才是未知", () => {
    expect(knownBestHeight([{ heights: [360] }, { heights: [1080, 720] }])).toBe(1080);
    expect(knownBestHeight([{ heights: [] }, {}])).toBe(0);
  });
});

describe("上限提示说哪一句", () => {
  it("还没挑登录身份时,劝他挑一个", () => {
    expect(qualityHint(1080, "")).toEqual({ key: "urlImportQualityKnown", n: 1080 });
  });

  it("已经挑了就别再劝 —— 换成「这已经是那个身份看到的上限」", () => {
    // 挑过身份的人读到「选一个登录身份再试」只会困惑:我不是选了吗。真界面上撞见的:
    // 登录身份是 BiliBili,下面那行还在让他去选一个。
    expect(qualityHint(1080, "BiliBili")).toEqual({
      key: "urlImportQualityKnownSignedIn",
      n: 1080,
      name: "BiliBili",
    });
  });

  it("不知道上限就什么都不说 —— 空占一行比不说更糟", () => {
    expect(qualityHint(0, "BiliBili")).toBeNull();
    expect(qualityHint(0, "")).toBeNull();
  });
});
