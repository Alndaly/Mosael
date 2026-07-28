import type { Asset } from "@/api/client";

/**
 * 一个素材此刻能不能被合成器画出来。
 *
 * 预览**只走** WebCodecs + 代理这一条路——没有 `<video>` 元素兜底了(见
 * docs/adr/0004-preview-export-parity-by-contract.md 与 compositorFlag.ts)。少了兜底,
 * 「画不出来」就必须变成一个**说得清的状态**摆给用户看,而不是悄悄退化成另一条画得不一样的路。
 *
 * 纯函数,不碰 React/网络,所以这套判定可以直接单测。
 */
export type AssetPreviewState =
  /** 可以画:图片,或代理已就绪且本机解得动。 */
  | "ready"
  /** 代理还在转(或还没排上队)——等一会儿就好,可自愈。 */
  | "transcoding"
  /** 后端转码失败——需要用户点重试。 */
  | "failed"
  /** 代理在,但**本机**解不了(缺编解码器 / 文件截断)。重新生成代理是唯一的自救手段。 */
  | "undecodable";

function proxyStatus(asset: Asset): string {
  return String((asset.media_info as { proxy_status?: string } | undefined)?.proxy_status ?? "");
}

export function assetPreviewState(asset: Asset, undecodable: ReadonlySet<string>): AssetPreviewState {
  // 图片直接用原图,不经代理与解码器。
  if (asset.kind === "image") return "ready";
  // 本机解不动优先于后端状态:后端说 ready 只代表**文件在**,不代表这台机器放得了。
  if (undecodable.has(asset.id)) return "undecodable";
  const status = proxyStatus(asset);
  if (status === "ready") return "ready";
  if (status === "failed") return "failed";
  // "pending"、空、以及任何没见过的值都当作「还在转」——把未知状态显示成错误会让用户去点
  // 一个其实不需要的重试;显示成「转码中」最多是多等一会儿,而轮询会自己纠正。
  return "transcoding";
}

/** 优先级:能动手的错误 > 只需等待。同为错误时 undecodable 更具体,优先报它。 */
const SEVERITY: Record<AssetPreviewState, number> = { ready: 0, transcoding: 1, failed: 2, undecodable: 3 };

/**
 * 这一组素材里最该被报出来的那个状态;全部就绪时返回 null。
 *
 * 调用方只传**当前播放头下真正要画的**素材——按整条序列判定的话,时间线末尾一个还在转码的
 * 片段会把开头已经能放的部分一起挡住。
 */
export function blockingPreviewState(
  assets: readonly Asset[],
  undecodable: ReadonlySet<string>,
): { state: Exclude<AssetPreviewState, "ready">; assets: Asset[] } | null {
  let worst: AssetPreviewState = "ready";
  for (const asset of assets) {
    const state = assetPreviewState(asset, undecodable);
    if (SEVERITY[state] > SEVERITY[worst]) worst = state;
  }
  if (worst === "ready") return null;
  return {
    state: worst,
    assets: assets.filter((asset) => assetPreviewState(asset, undecodable) === worst),
  };
}
