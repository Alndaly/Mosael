/** @vitest-environment jsdom */
/**
 * 后端说「这次请求建了任务」,请求层就广播一声,由 App 统一刷新任务列表。
 * 此前只有少数按钮自己记得刷新,其余的任务要等任务中心下一轮轮询(空闲 8 秒)才出现。
 */
import { afterEach, expect, it, vi } from "vitest";
import { JOBS_CREATED_EVENT, NEW_JOBS_HEADER, api } from "@/api/transport";

const originalFetch = globalThis.fetch;
afterEach(() => { globalThis.fetch = originalFetch; });

function reply(headers: Record<string, string>) {
  globalThis.fetch = vi.fn(async () => new Response("{}", { status: 200, headers: { "content-type": "application/json", ...headers } })) as never;
}

it("响应头说建了任务,就广播;没说就不广播", async () => {
  const heard = vi.fn();
  window.addEventListener(JOBS_CREATED_EVENT, heard);

  reply({ [NEW_JOBS_HEADER]: "1" });
  await api("/api/assets/a1/separate", { method: "POST" });
  expect(heard).toHaveBeenCalledTimes(1);

  reply({});
  await api("/api/assets/a1", { method: "PATCH", body: "{}" });
  expect(heard).toHaveBeenCalledTimes(1);
  window.removeEventListener(JOBS_CREATED_EVENT, heard);
});
