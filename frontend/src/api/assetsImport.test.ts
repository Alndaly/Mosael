/**
 * 素材入库那两张表单的线上契约(ADR 0057 决定 2)。
 *
 * - `savePaintedMask` 走 `POST /api/assets/masks`:键是后端认的 `workspace_id` / `source_asset_id` / `project_id` / `file`,
 *   少一个下划线就是一次 422,而类型检查替这里兜不住(它是 FormData 里的一串字)。`MaskEditor` 那个只按调用参数
 *   断言的替身看不到这一层。
 * - `importAsset` **不再带出处**:那一栏是为蒙版加到通用导入上的后门,蒙版有了自己的出口之后撤掉。
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

import { importAsset, savePaintedMask } from "./domains/assets";

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

describe("画出来的蒙版走自己的出口", () => {
  it("在一张图上画的:带着源图,发到 /api/assets/masks", async () => {
    apiUpload.mockResolvedValue({ id: "mask-1" });
    const controller = new AbortController();
    await savePaintedMask({ workspaceId: "w1", sourceAssetId: "src-1", projectId: "p1", file, signal: controller.signal });

    const [path, form, options] = apiUpload.mock.calls[0] as [string, FormData, { signal?: AbortSignal }];
    expect(path).toBe("/api/assets/masks");
    expect(form.get("workspace_id")).toBe("w1");
    expect(form.get("source_asset_id")).toBe("src-1");
    expect(form.get("project_id")).toBe("p1");
    expect(form.get("file")).toBeInstanceOf(Blob);
    expect(options.signal).toBe(controller.signal);
  });

  it("空白蒙版:不带源图这一栏(后端据此不记出处、名字写「空白」)", async () => {
    apiUpload.mockResolvedValue({ id: "mask-2" });
    await savePaintedMask({ workspaceId: "w1", file });
    const form = formOf(apiUpload.mock.calls[0]);
    expect(form.has("source_asset_id")).toBe(false);
    expect(form.has("project_id")).toBe(false);
  });
});

describe("普通导入不带出处", () => {
  it("表单里没有 derived_from 这一栏", async () => {
    api.mockResolvedValue({ id: "plain" });
    await importAsset({ workspaceId: "w1", file });
    expect(formOf(api.mock.calls[0]).has("derived_from")).toBe(false);
  });
});
