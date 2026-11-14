/**
 * 回复正文里引用 Mosael 素材的写法:`![说明](mosael-asset:<asset_id>)`。
 *
 * 为什么需要这一层:媒体元素(`<img src>`)**加不了请求头**,而素材接口要登录态 —— 后端给
 * `/api/assets/{id}/file?token=…` 这种带 token 的地址(见 api/domains/assets 的 `assetUrl`),
 * 模型不可能知道 token,所以它在正文里只写 `mosael-asset:<id>`,渲染前在这里换成真地址。
 *
 * 只认这一种前缀,别的一律不动:外链、data:、已经带 token 的地址照原样走(模型的正文里也可能直接
 * 贴一张网上的图)。
 */
const MARKDOWN_ASSET_REF = /(]\()mosael-asset:([A-Za-z0-9_-]+)(\s*\))/g;
//: 内嵌 HTML 的 src:按标签取 —— `<img>` 要预览图(HEIC 转成浏览器认得的),`<video>` / `<audio>` / `<source>` 要原文件
//: (预览图那一路给不出视频的字节;此前一律换成预览地址,`<video src="mosael-asset:…">` 放不出来)。
const HTML_ASSET_REF = /(<(img|video|audio|source)\b[^>]*?\bsrc\s*=\s*["'])mosael-asset:([A-Za-z0-9_-]+)(["'])/gi;

/**
 * `previewUrl`:Markdown 图片语法和 `<img>` 用的地址(MarkdownImage 认出它是本机素材后按种类画);
 * `fileUrl`:`<video>` / `<audio>` / `<source>` 用的原文件地址。
 */
export function rewriteAssetRefs(markdown: string, previewUrl: (assetId: string) => string,
                                 fileUrl: (assetId: string) => string): string {
  if (!markdown.includes("mosael-asset:")) return markdown;
  return markdown
    .replace(MARKDOWN_ASSET_REF, (_match, head: string, id: string, tail: string) => `${head}${previewUrl(id)}${tail}`)
    .replace(HTML_ASSET_REF, (_match, head: string, tag: string, id: string, tail: string) =>
      `${head}${tag.toLowerCase() === "img" ? previewUrl(id) : fileUrl(id)}${tail}`);
}
