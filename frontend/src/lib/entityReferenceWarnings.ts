/**
 * 正文 `@` 的资产参考图，按当前模型的角色名额能发几张。
 *
 * 规则和后端 `entities.mentions.attach_entities` 一致：先占显式素材槽，再按资产在正文里的先后
 * 轮流挑图（甲一张、乙一张、甲第二张……）。所以第二个资产能不能发，必须把前面的资产已经占掉的
 * 名额算进去；只看“模型上限 − 显式槽位”会把第二个资产误报成“还能发一张”。
 */

export type EntityReferenceRole = "reference_image" | "pose_reference";

export interface EntityReferenceCandidate {
  id: string;
  /** 这个资产自己的参考图张数（不含变体继承，后端可能还会补）。 */
  referenceCount: number;
  /** 已作为显式素材发出去的封面；有它就从待发张数里扣一张。 */
  coverAssetId?: string | null;
  role: EntityReferenceRole;
}

export interface EntityReferenceCapacity {
  supported: boolean;
  limit: number;
  /** 显式素材槽里已经占用的张数。 */
  used: number;
}

export interface EntityReferenceWarning {
  id: string;
  reason: "pose_unsupported" | "role_unsupported" | "capacity" | "partial";
  /** 最多能发几张（含已经作为封面发出的那张）。 */
  sent: number;
  /** 还有几张没发。 */
  missing: number;
}

const EMPTY_CAPACITY: EntityReferenceCapacity = { supported: false, limit: 0, used: 0 };

/**
 * `capacity(role)` 由调用方按当前模型给；`sentAssetIds` 是显式素材槽里已经有的 asset id，
 * 用来避免资产封面已经发出、还提示“没发送”。
 */
export function entityReferenceWarnings(
  candidates: readonly EntityReferenceCandidate[],
  capacity: (role: EntityReferenceRole) => EntityReferenceCapacity,
  sentAssetIds: ReadonlySet<string>,
): EntityReferenceWarning[] {
  const byRole = new Map<EntityReferenceRole, EntityReferenceCandidate[]>();
  for (const candidate of candidates) {
    const list = byRole.get(candidate.role) ?? [];
    list.push(candidate);
    byRole.set(candidate.role, list);
  }

  const warnings: EntityReferenceWarning[] = [];
  for (const [role, group] of byRole) {
    const cap = capacity(role) ?? EMPTY_CAPACITY;
    const coverSent = group.map((one) => Boolean(one.coverAssetId && sentAssetIds.has(one.coverAssetId)));
    const needed = group.map((one, index) => Math.max(0, one.referenceCount - (coverSent[index] ? 1 : 0)));
    const attached = group.map(() => 0);
    if (!cap.supported) {
      group.forEach((candidate, index) => {
        if (needed[index] <= 0) return;
        warnings.push({
          id: candidate.id,
          reason: role === "pose_reference" ? "pose_unsupported" : "role_unsupported",
          sent: coverSent[index] ? 1 : 0,
          missing: needed[index],
        });
      });
      continue;
    }

    let budget = Math.max(0, cap.limit - cap.used);
    //: 和后端同一条顺序：每轮每个资产各取一张，直到名额用完。
    while (budget > 0 && needed.some((one, index) => one > attached[index])) {
      let progressed = false;
      for (let index = 0; index < group.length && budget > 0; index += 1) {
        if (attached[index] >= needed[index]) continue;
        attached[index] += 1;
        budget -= 1;
        progressed = true;
      }
      if (!progressed) break;
    }

    group.forEach((candidate, index) => {
      if (attached[index] >= needed[index]) return;
      const sent = attached[index] + (coverSent[index] ? 1 : 0);
      warnings.push({
        id: candidate.id,
        reason: sent === 0 ? "capacity" : "partial",
        sent,
        missing: needed[index] - attached[index],
      });
    });
  }
  return warnings;
}
