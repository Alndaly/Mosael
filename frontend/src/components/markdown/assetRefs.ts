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
const HTML_ASSET_REF = /(\bsrc\s*=\s*["'])mosael-asset:([A-Za-z0-9_-]+)(["'])/g;

export function rewriteAssetRefs(markdown: string, urlFor: (assetId: string) => string): string {
  if (!markdown.includes("mosael-asset:")) return markdown;
  return markdown
    .replace(MARKDOWN_ASSET_REF, (_match, head: string, id: string, tail: string) => `${head}${urlFor(id)}${tail}`)
    .replace(HTML_ASSET_REF, (_match, head: string, id: string, tail: string) => `${head}${urlFor(id)}${tail}`);
}
