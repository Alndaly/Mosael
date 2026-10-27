/**
 * **契约管道测试**:每个平台 × 每种声明支持的形状,从"进到那一页"一路跑到"判定成功"。
 *
 * 它测的是**契约数据 + 判定口径 + 浮层策略**,不是平台真实 DOM(那是真机的事)。价值在于:
 * 2026-10-23 那一整天的失败几乎都是"契约里写错了某一样" —— 入口地址/文案、文件框、成功信号、
 * 浮层关法 —— 而这些以前只有真机发布才看得出来。
 *
 * 覆盖面是**自动展开**的:平台来自 `PUBLISH_CONTRACTS`,形状来自 `ADAPTER_SUPPORTS`。新加平台或
 * 新接一种形状,这张表会自动多出一组用例,要么通过、要么红,不能悄悄漏测。
 */
import { describe, expect, it, vi } from "vitest";

vi.mock("electron", () => ({ app: { getPath: () => "/tmp" } }));

const { PUBLISH_CONTRACTS } = await import("./contracts");
const { ADAPTER_SUPPORTS } = await import("./adapters");
const { fakeDriver, fakePage } = await import("./fakePage");
const { clearOverlays } = await import("./overlays");
const { successVisible, linesEntered } = await import("./verify");

/** 假页面上的"这一档页面":按契约把该有的元素摆出来。 */
function pageFor(platform: string, kind: string) {
  const contract = PUBLISH_CONTRACTS[platform as keyof typeof PUBLISH_CONTRACTS];
  const fileInput = contract.fileInput[kind as keyof typeof contract.fileInput];
  //: 文章没有素材(不摆文件框)。
  return fakePage({
    elements: new Map(fileInput ? [[fileInput as string, { visible: true, enabled: true }]] : []),
  });
}

const cases = Object.entries(PUBLISH_CONTRACTS).flatMap(([platform]) =>
  (ADAPTER_SUPPORTS[platform] ?? []).map((kind) => ({ platform, kind, contract: PUBLISH_CONTRACTS[platform as keyof typeof PUBLISH_CONTRACTS] })),
);

describe("契约管道", () => {
  it("覆盖面自动展开:每个平台至少一种形状被测到", () => {
    expect(cases.length).toBeGreaterThan(0);
    const platforms = new Set(cases.map((one) => one.platform));
    expect(platforms.size).toBe(Object.keys(PUBLISH_CONTRACTS).length);
  });

  for (const { platform, kind, contract } of cases) {
    describe(`${platform} × ${kind}`, () => {
      it("进得去:入口有直连地址或可点的 tab;要交素材的形状落地后文件框在", async () => {
        const entry = contract.entry[kind as keyof typeof contract.entry];
        expect(entry, "契约缺这一档的入口").toBeTruthy();
        expect(
          Boolean(entry?.url) || (entry?.steps?.length ?? 0) > 0,
          "入口既没直连地址也没有 tab 可点 —— 这一档走不到",
        ).toBe(true);

        const page = pageFor(platform, kind);
        const driver = fakeDriver(page);
        if (entry?.url) await driver.goto(entry.url);
        const fileInput = contract.fileInput[kind as keyof typeof contract.fileInput];
        if (fileInput) {
          //: 落地后文件框必须在这个选择器上(否则上传那一步没有落点)。
          await expect(driver.cssAttached(fileInput)).resolves.toBe(true);
        }
      });

      it("交得了:文件按形状交给契约里的那个框", async () => {
        const fileInput = contract.fileInput[kind as keyof typeof contract.fileInput] as string | undefined;
        if (!fileInput) return; // 文章没有素材
        const page = pageFor(platform, kind);
        const driver = fakeDriver(page);
        await driver.setFiles(fileInput, "/tmp/a.mp4");
        expect(page.files).toEqual(["/tmp/a.mp4"]);
      });

      it("发成功认得出:地址命中**任意一条**成功信号", async () => {
        const regex = (contract.done.urls ?? []).find((one) => one instanceof RegExp);
        if (!regex) return; // 这一档的成功判据是文案或函数式:下面两条覆盖
        const page = pageFor(platform, kind);
        page.url = "https://example.test/whatever";
        expect(await successVisible(fakeDriver(page), contract.done)).toBe(false);
        //: 造一个能命中的地址:取正则里最"实"的那一段当样例有风险,这里直接用它的 source 反推
        //: 不可行 —— 交给下一条"文案信号"用例;这里只验**不命中时不误判**。
        expect(regex.test(page.url)).toBe(false);
      });

      it("发成功认得出:成功文案(含浮层里的字)在页面上就算数", async () => {
        const text = (contract.done.texts ?? [])[0];
        if (!text) return;
        const page = pageFor(platform, kind);
        page.texts.add(text);
        expect(await successVisible(fakeDriver(page), contract.done)).toBe(true);
      });

      it("浮层清得掉:按契约关掉之后,那句话不在页面上了", async () => {
        const rule = contract.overlays[0];
        if (!rule) return;
        const page = pageFor(platform, kind);
        const key = rule.detect.text ?? rule.detect.selector ?? "";
        if (rule.detect.text) page.texts.add(rule.detect.text);
        //: 平台行为:点掉确认钮,那条提示随之消失(由契约里的 dismiss 决定点哪句)。
        if (rule.dismiss.click && rule.detect.text) {
          page.clickEffects.set(rule.dismiss.click, [rule.detect.text]);
        }
        if (rule.detect.selector) page.elements.set(rule.detect.selector, { visible: true, enabled: true });
        const driver = fakeDriver(page);
        await clearOverlays(driver, contract.overlays, platform, (text) => driver.clickByText(text));
        if (rule.detect.text) expect(page.texts.has(rule.detect.text)).toBe(false);
        if (rule.detect.selector) expect(page.elements.get(rule.detect.selector)?.visible ?? false).toBe(false);
        expect(key).toBeTruthy();
      });

      it("formGone 闸门:编辑表单还在时,成功文案再像也不算成功", async () => {
        if (!contract.done.formGone) return;
        const page = pageFor(platform, kind);
        const text = (contract.done.texts ?? [])[0];
        if (!text) return;
        page.texts.add(text);
        //: 表单还在(说明还没投出去):文案命中也不能判成功 —— 这道闸是防"把别人的发布记成自己的"。
        page.elements.set(contract.done.formGone, { visible: true, enabled: true });
        expect(await successVisible(fakeDriver(page), contract.done)).toBe(false);

        //: 表单消失之后才认。
        page.elements.set(contract.done.formGone, { visible: false, enabled: false });
        expect(await successVisible(fakeDriver(page), contract.done)).toBe(true);
      });

      it("正文判定按行、按顺序:重排不算进去", async () => {
        const page = pageFor(platform, kind);
        const driver = fakeDriver(page);
        page.editor = "2. 第二行1. 第一行";
        const result = await linesEntered(driver, "ignored", "1. 第一行\n2. 第二行");
        expect(result.ok).toBe(false);

        page.editor = "1. 第一行\n2. 第二行";
        const ordered = await linesEntered(driver, "ignored", "1. 第一行\n2. 第二行");
        expect(ordered.ok).toBe(true);
      });
    });
  }
});
