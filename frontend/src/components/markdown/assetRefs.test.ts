/**
 * 回复正文里的素材引用:`![说明](mosael-asset:<id>)` → 带 token 的素材地址(媒体元素加不了请求头)。
 */
import { describe, expect, it } from "vitest";

import { rewriteAssetRefs } from "./assetRefs";

const urlFor = (id: string) => `https://api.test/api/assets/${id}/preview?token=t`;

describe("正文里的素材引用", () => {
  it("markdown 图片写法换成真地址,说明文字原样保留", () => {
    expect(rewriteAssetRefs("看这张 ![猫](mosael-asset:a1) 怎么样", urlFor)).toBe(
      "看这张 ![猫](https://api.test/api/assets/a1/preview?token=t) 怎么样",
    );
  });

  it("内嵌 HTML 的 src 也认", () => {
    expect(rewriteAssetRefs('<img src="mosael-asset:a1" width="120">', urlFor)).toBe(
      '<img src="https://api.test/api/assets/a1/preview?token=t" width="120">',
    );
    expect(rewriteAssetRefs("<img src='mosael-asset:a1'>", urlFor)).toBe(
      "<img src='https://api.test/api/assets/a1/preview?token=t'>",
    );
  });

  it("别的地址一律不动:外链、data:、已经带 token 的地址", () => {
    const text = "![网图](https://example.test/a.png) ![内联](data:image/png;base64,AAA)";
    expect(rewriteAssetRefs(text, urlFor)).toBe(text);
    const plain = "没有素材引用的一段话";
    expect(rewriteAssetRefs(plain, urlFor)).toBe(plain);
  });
});
