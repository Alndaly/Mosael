/**
 * 整页宽面板里的「节说明」不设宽度上限。
 *
 * 设置页、管理页各自的节说明已经统一成「不限宽」—— 面板是整页宽、下面紧跟满宽的行/卡片,
 * 说明被 42rem(`max-w-2xl`)截住时右边会空出一大块。同一类还有两处(这次顺带收掉):
 *
 * - `components/layout/StudioPage.tsx` 的 `PageHeading` 说明:列表页的页头,下面紧跟满宽卡片网格;
 * - `features/entities/EntityDetail.tsx` 的变体页签提示:挂在资产详情的宽面板里。
 *
 * **弹窗 / 窄容器里的 `max-w-*` 一律不动** —— 那里的行长本来就短,不是同一类(见下面第二条)。
 */
import { readFileSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

const SRC = join(import.meta.dirname, "..", "..");
const read = (rel: string) => readFileSync(join(SRC, rel), "utf8");

/** 某一段里含某个片段的那些行(测试要钉的是「那一行」,不是整个文件)。 */
function lines(rel: string, includes: string): string[] {
  return read(rel).split("\n").filter((one) => one.includes(includes));
}

describe("宽面板里的节说明不设宽度上限", () => {
  it("页面标题的说明(StudioPage 的 PageHeading)没有 42rem 的天花板", () => {
    const found = lines("components/layout/StudioPage.tsx", "{description && <p");
    expect(found).toHaveLength(1);
    expect(found[0]).not.toContain("max-w-");
  });

  it("资产详情的变体页签提示没有 42rem 的天花板", () => {
    const found = lines("features/entities/EntityDetail.tsx", "entityVariantsHint");
    expect(found).toHaveLength(1);
    expect(found[0]).not.toContain("max-w-");
  });

  it("窄容器里的宽度上限不动:封面缩略图仍是 max-w-[180px]", () => {
    expect(read("features/entities/EntityDetail.tsx")).toContain("aspect-[4/5] w-full max-w-[180px]");
  });
});
