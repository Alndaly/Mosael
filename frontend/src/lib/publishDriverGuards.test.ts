/**
 * 页面驱动上「收文案」和「收选择器」两族方法不能混。
 *
 * 被测的是 Electron 主进程里的 PageDriver(与 deepLinkParse.test.ts 同因放在这里)。
 *
 * 驱动上几乎每个方法都收 CSS 选择器,只有 `waitButtonEnabled` 收的是**按钮文案** —— 于是它最容易
 * 被顺手传进一个选择器,而那样它只会去找"文本恰好等于 `#next-button` 的按钮",永远找不到,
 * **静默恒假**。TikTok 与 YouTube 两个适配器都这么写过:一处表现为"上传等满 10 分钟超时",另一处
 * 表现为"没走到可见性步骤",谁也看不出病根在参数上。所以宁可当场炸。
 */
import { describe, expect, it, vi } from "vitest";

vi.mock("electron", () => ({ app: { getPath: () => "/tmp" } }));

const { PageDriver } = await import("../../../electron/publish/pageDriver");

/** 守卫在碰 webContents 之前就该拦下来,所以这里给个空壳就够。 */
const driver = () => new PageDriver({} as never);

describe("waitButtonEnabled 的参数守卫", () => {
  it.each(["#next-button", "#done-button", '[data-e2e="post_video_button"]', ".submit-add"])(
    "把选择器 %s 传进来时当场抛,而不是静默找不到",
    async (selector) => {
      await expect(driver().waitButtonEnabled(selector, 10)).rejects.toThrow(/waitCssEnabled/);
    },
  );

  it("正常文案不被守卫拦下 —— 它照常走到「没找到」这个答案", async () => {
    // 空壳 webContents 让求值失败,而 waitForFunction 把求值失败当作"这一拍没命中",等满预算返回
    // false。**这正是要区分的两种结果**:守卫是抛错,找不到是 false;混在一起就看不出参数传错了。
    await expect(driver().waitButtonEnabled("发布", 10)).resolves.toBe(false);
  });

  it("以 # 开头的文案极少见,但守卫只看开头,所以要知道它会误伤", () => {
    // 记录既有取舍:平台按钮文案没有以 # . [ 开头的;真出现了就把它挪进 waitCssEnabled 的选择器写法。
    expect(/^[#.[]/.test("发布")).toBe(false);
    expect(/^[#.[]/.test("#话题")).toBe(true);
  });
});
