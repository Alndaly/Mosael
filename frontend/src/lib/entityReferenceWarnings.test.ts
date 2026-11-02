import { describe, expect, it } from "vitest";

import { entityReferenceWarnings, type EntityReferenceCandidate } from "./entityReferenceWarnings";

const candidate = (extra: Partial<EntityReferenceCandidate> & Pick<EntityReferenceCandidate, "id">): EntityReferenceCandidate => ({
  referenceCount: 1,
  role: "reference_image",
  ...extra,
});

describe("资产参考图名额", () => {
  it("第一个资产占掉唯一名额后，第二个资产一张都发不出去", () => {
    const warnings = entityReferenceWarnings(
      [candidate({ id: "pearl" }), candidate({ id: "pose", referenceCount: 2 })],
      () => ({ supported: true, limit: 1, used: 0 }),
      new Set(),
    );
    expect(warnings).toEqual([{ id: "pose", reason: "capacity", sent: 0, missing: 2 }]);
  });

  it("一个资产有多张图、名额不够时，按实际可发张数报部分发送", () => {
    const warnings = entityReferenceWarnings(
      [candidate({ id: "multi", referenceCount: 3 })],
      () => ({ supported: true, limit: 1, used: 0 }),
      new Set(),
    );
    expect(warnings).toEqual([{ id: "multi", reason: "partial", sent: 1, missing: 2 }]);
  });

  it("姿势入口不支持时，不把它误报成名额不足", () => {
    const warnings = entityReferenceWarnings(
      [candidate({ id: "pose", role: "pose_reference" })],
      () => ({ supported: false, limit: 0, used: 0 }),
      new Set(),
    );
    expect(warnings).toEqual([{ id: "pose", reason: "pose_unsupported", sent: 0, missing: 1 }]);
  });

  it("封面已经作为显式素材发送时，从待发张数里扣掉", () => {
    const warnings = entityReferenceWarnings(
      [candidate({ id: "pearl", referenceCount: 3, coverAssetId: "cover" })],
      () => ({ supported: true, limit: 1, used: 0 }),
      new Set(["cover"]),
    );
    expect(warnings).toEqual([{ id: "pearl", reason: "partial", sent: 2, missing: 1 }]);
  });
});
