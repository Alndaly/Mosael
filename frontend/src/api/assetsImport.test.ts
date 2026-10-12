/**
 * `importAsset` 交出去的那个表单:**有出处才带 `derived_from`,而且带的是后端认的那个形状**。
 *
 * 这一条是编辑器那条路的线上契约 —— `MaskEditor` 那个只按调用参数断言的替身看不到它:
 * 后端收的是 JSON 文本、键是 `asset_id`(见 domain/assets/lineage.parse_derived_from),
 * 少一个下划线就是一次 422,而类型检查替这里兜不住(它是 FormData 里的一串字)。
 *
 * **不给就得与这条接口收出处之前逐字节相同**:没有这一栏,而不是一个空数组的 `"[]"`。
 */
import { beforeEach, describe, expect, it, vi } from "vitest";

const api = vi.fn();
const apiUpload = vi.fn();

vi.mock("@/api/transport", () => ({
  API_BASE: "http://api.test",
  ApiError: class ApiError extends Error {},
  api: (...args: unknown[]) => api(...args),
  apiUpload: (...args: unknown[]) => apiUpload(...args),
  getAuthToken: () => null,
}));

import { importAsset } from "./domains/assets";

const file = new File([new Uint8Array([1, 2, 3])], "mask.png", { type: "image/png" });

/** 这一次交出去的表单:`api` 收的是 `{ body }`,`apiUpload` 收的就是那张 FormData 本身。 */
function formOf(call: unknown[]): FormData {
  const second = call[1] as FormData | { body: FormData };
  return second instanceof FormData ? second : second.body;
}

beforeEach(() => {
  api.mockReset();
  apiUpload.mockReset();
});

describe("导入时带着出处", () => {
  it("给了出处:derived_from 是后端认的那串 JSON", async () => {
    api.mockResolvedValue({ id: "mask-1" });
    await importAsset({ workspaceId: "w1", file, derivedFrom: [{ asset_id: "src-1", op: "mask" }] });

    expect(formOf(api.mock.calls[0]).get("derived_from")).toBe('[{"asset_id":"src-1","op":"mask"}]');
  });

  it("带 signal 的那一趟(编辑器走的正是它)也是同一张表单", async () => {
    apiUpload.mockResolvedValue({ id: "mask-2" });
    const controller = new AbortController();
    await importAsset({
      workspaceId: "w1", file, derivedFrom: [{ asset_id: "src-1", op: "mask" }], signal: controller.signal,
    });

    expect(formOf(apiUpload.mock.calls[0]).get("derived_from")).toBe('[{"asset_id":"src-1","op":"mask"}]');
  });

  it("没给 / 空数组:这一栏根本不出现(与收出处之前逐字节相同)", async () => {
    api.mockResolvedValue({ id: "plain" });
    await importAsset({ workspaceId: "w1", file });
    expect(formOf(api.mock.calls[0]).has("derived_from")).toBe(false);

    await importAsset({ workspaceId: "w1", file, derivedFrom: [] });
    expect(formOf(api.mock.calls[1]).has("derived_from")).toBe(false);
  });
});
