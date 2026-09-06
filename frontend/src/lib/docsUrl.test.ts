import { describe, expect, it } from "vitest";

import { docsUrl } from "@/lib/deepLink";

/**
 * 「文档」按钮此前指向的是**插件作者的站点**(百度网盘的 API 文档)。而这一页上的问题是
 * "连接是什么、凭据填哪儿、权限为什么要授" —— 那些是 Mosael 自己的概念,百度的文档里
 * 一个字都没有。所以文档指向官网,作者的站点单独给,并标明是它自己的主页。
 */
describe("官网文档链接", () => {
  it("按界面语言分段", () => {
    expect(docsUrl("guides/plugins", "zh-CN")).toBe("https://mosael.com/zh/docs/guides/plugins");
    expect(docsUrl("guides/plugins", "en-US")).toBe("https://mosael.com/en/docs/guides/plugins");
  });

  it("认不出的语言退到英文", () => {
    // 站点只有这两段;猜错的代价是 404,而英文那份一定存在。
    expect(docsUrl("guides/plugins", "de-DE")).toBe("https://mosael.com/en/docs/guides/plugins");
  });

  it("路径带不带前导斜杠都一样", () => {
    // 调用点写哪一种都合理,而拼出 `docs//guides` 的话某些站点会 404。
    expect(docsUrl("/guides/plugins", "zh-CN")).toBe(docsUrl("guides/plugins", "zh-CN"));
  });
});
