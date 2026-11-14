/**
 * 回复正文里的素材引用:`![说明](mosael-asset:<id>)` → 带 token 的素材地址(媒体元素加不了请求头)。
 */
import { describe, expect, it } from "vitest";

import { rewriteAssetRefs } from "./assetRefs";

const urlFor = (id: string) => `https://api.test/api/assets/${id}/preview?token=t`;
const fileFor = (id: string) => `https://api.test/api/assets/${id}/file?token=t`;

describe("正文里的素材引用", () => {
  it("markdown 图片写法换成真地址,说明文字原样保留", () => {
    expect(rewriteAssetRefs("看这张 ![猫](mosael-asset:a1) 怎么样", urlFor, fileFor)).toBe(
      "看这张 ![猫](https://api.test/api/assets/a1/preview?token=t) 怎么样",
    );
  });

  it("内嵌 HTML 的 src 也认", () => {
    expect(rewriteAssetRefs('<img src="mosael-asset:a1" width="120">', urlFor, fileFor)).toBe(
      '<img src="https://api.test/api/assets/a1/preview?token=t" width="120">',
    );
    expect(rewriteAssetRefs("<img src='mosael-asset:a1'>", urlFor, fileFor)).toBe(
      "<img src='https://api.test/api/assets/a1/preview?token=t'>",
    );
  });

  it("内嵌的 <video> / <audio> / <source> 取原文件:预览图那一路给不出视频的字节", () => {
    expect(rewriteAssetRefs('<video controls src="mosael-asset:v1"></video>', urlFor, fileFor)).toBe(
      '<video controls src="https://api.test/api/assets/v1/file?token=t"></video>',
    );
    expect(rewriteAssetRefs('<audio src="mosael-asset:a2"></audio><source src=\'mosael-asset:s3\'>', urlFor, fileFor)).toBe(
      '<audio src="https://api.test/api/assets/a2/file?token=t"></audio><source src=\'https://api.test/api/assets/s3/file?token=t\'>',
    );
  });

  it("别的地址一律不动:外链、data:、已经带 token 的地址", () => {
    const text = "![网图](https://example.test/a.png) ![内联](data:image/png;base64,AAA)";
    expect(rewriteAssetRefs(text, urlFor, fileFor)).toBe(text);
    const plain = "没有素材引用的一段话";
    expect(rewriteAssetRefs(plain, urlFor, fileFor)).toBe(plain);
  });
});
