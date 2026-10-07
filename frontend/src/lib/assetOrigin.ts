import type { Asset } from "@/api/client";
import type { MessageKey } from "@/app/messages";

type Origin = Pick<Asset, "source" | "derived" | "ai_generated">;

/**
 * 素材卡片、详情和挑素材的网格(AssetGridPicker)上那个「来源」标签 —— 素材库和挑素材的地方都用,所以住在 lib。
 *
 * 此前 `source === "generated"` 一律写成「AI 生成」—— 而截一段、取一帧、切宫格登记的也是 generated,
 * 实拍视频截出来的一段被标成了 AI。现在 AI 看后端定下的 `ai_generated`(自己是,或出处里有),
 * 加工出来的(有出处,或是老的 generated 而不含 AI)写「加工」。
 */
export function assetOriginKey(asset: Origin): MessageKey {
  if (asset.source === "exported") return "mediaSourceExported";
  if (asset.derived || (asset.source === "generated" && !asset.ai_generated)) return "mediaSourceDerived";
  if (asset.ai_generated) return "mediaSourceGenerated";
  return "mediaSourceImported";
}

/** 来源标签说的不是 AI(导出、加工),而它含 AI 内容:另挂一枚「含 AI 生成内容」。 */
export function showsContainsAi(asset: Origin): boolean {
  return Boolean(asset.ai_generated) && assetOriginKey(asset) !== "mediaSourceGenerated";
}
