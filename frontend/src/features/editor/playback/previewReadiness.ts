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
  | "undecodable"
  /** 这台后端**不生成代理**——等和重试都没有意义,得改部署配置。 */
  | "proxies-disabled";

function proxyStatus(asset: Asset): string {
  return String((asset.media_info as { proxy_status?: string } | undefined)?.proxy_status ?? "");
}

export function assetPreviewState(asset: Asset, undecodable: ReadonlySet<string>): AssetPreviewState {
  // 图片直接用原图,不经代理与解码器。
  if (asset.kind === "image") return "ready";
  const status = proxyStatus(asset);
  // 「本机解不动」**只有代理确实在盘上时才成立**。合成器对任何视频片段都会去取代理 URL,
  // 代理还没转好时那就是一个 404 —— 而 404 说的是"文件还没生成",不是"这台机器缺编解码器"。
  // 此前这一条排在状态判断之前,于是新导入的素材一拖进时间线就报「本机无法解码这个素材」,
  // 配一个「重新生成代理」的按钮 —— 让用户去重做一件正在做的事,而它其实只需要等。
  //
  // 后端说 ready 仍然只代表**文件在**,不代表这台机器放得了 —— 那一层判断保留在下面。
  if (status === "ready") return undecodable.has(asset.id) ? "undecodable" : "ready";
  if (status === "failed") return "failed";
  // 这台后端根本不生成代理(`generate_proxies` 关掉,或这份素材没有 file_key)。
  // **这一条必须排在「还在转」前面,也必须排在 ready 后面**:已经转好的代理照样能放,
  // 开关是之后才关的也不影响它。
  //
  // 没有这一条时,前端读到的是空的 `proxy_status`,落进下面那个「未知一律当作还在转」——
  // 于是遮罩上写着「转码中,等一会儿就好」,而那是一件**永远不会发生的事**,外加每 2 秒
  // 轮询一次素材。那一档的设计理由(把未知显示成错误会让用户去点一个不需要的重试)在这里
  // 刚好反过来:用户需要知道的恰恰是"这台后端不生成代理"。
  //
  // 答案由后端算(`AssetOut.proxy_expected`)——`generate_proxies` 是后端才知道的开关,
  // **前端不该用缺省值去猜后端的配置**。
  if (asset.proxy_expected === false) return "proxies-disabled";
  // "pending"、空、以及任何没见过的值都当作「还在转」——把未知状态显示成错误会让用户去点
  // 一个其实不需要的重试;显示成「转码中」最多是多等一会儿,而轮询会自己纠正。
  return "transcoding";
}

/**
 * 监视器上可能报出来的状态:素材级的那几档,加上「这个环境根本没有 WebCodecs」——
 * 后者不属于任何一份素材,所以它不在 `AssetPreviewState` 里,但遮罩和轮询判断都要认它。
 */
export type PreviewBlockState = Exclude<AssetPreviewState, "ready"> | "unsupported";

/**
 * 这个状态会不会**自己**好起来 —— 监视器据此决定要不要每 2 秒轮询一次素材。
 *
 * 判据写在状态定义旁边,而不是在监视器里写一句 `state === "transcoding"`:
 * 加一档新状态时,该不该轮询是这里就要回答的问题。原先那句散在 Monitor 里,于是
 * 「后端不生成代理」这一档一旦落进 transcoding,轮询就永远停不下来。
 */
export function resolvesOnItsOwn(state: AssetPreviewState | PreviewBlockState): boolean {
  return state === "transcoding";
}

/** 优先级:能动手的错误 > 只需等待。同为错误时 undecodable 更具体,优先报它。 */
const SEVERITY: Record<AssetPreviewState, number> = {
  ready: 0,
  transcoding: 1,
  // 「这台后端不生成代理」比「还在转」更该报:后者会自愈,前者永远不会。
  "proxies-disabled": 2,
  failed: 3,
  undecodable: 4,
};

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
