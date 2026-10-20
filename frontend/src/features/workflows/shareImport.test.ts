/**
 * 社区分享导入在渲染层这一小段:分享 id 从 `share:` 标记里认出来,以及**导入成功后真的选中刚导入的那一条**。
 *
 * 后半条是源码断言:工作流页的选中状态住在它自己的 `usePersistentSelection` 里,没有一条能从外面
 * 「打开某条工作流」的公共函数(现有的是信箱事件 `mosael:open-workflow`,导入本来就在这一页上)。
 * 所以钉住装配:导入回调里必须 `setSelectedId(workflow.id)` —— 只弹一句「已导入」而把人留在列表上,
 * 正是这一笔要避免的。
 */
import { describe, expect, it } from "vitest";

import { readSource } from "@/design/jsxSource";
//: 前缀只有一份来源:主进程解析器怎么写,渲染层就怎么认(这里钉住,避免两边各改各的)。
import { SHARE_IMPORT_TEMPLATE_PREFIX } from "../../../../electron/system/deepLink";

import { SHARE_IMPORT_PREFIX, shareFromTemplate } from "./shareImport";

describe("社区分享 id 的识别", () => {
  it("`share:` 前缀和主进程解析器一致", () => {
    expect(SHARE_IMPORT_PREFIX).toBe(SHARE_IMPORT_TEMPLATE_PREFIX);
  });
  it("认 `share:<id>`;真模板 id、注入、超长一律不认", () => {
    expect(shareFromTemplate("share:abc")).toBe("abc");
    expect(shareFromTemplate("share:Ab_c-123")).toBe("Ab_c-123");
    expect(shareFromTemplate("full_video_generation")).toBeNull();
    expect(shareFromTemplate("share:../../etc/passwd")).toBeNull();
    expect(shareFromTemplate("share:has spaces")).toBeNull();
    expect(shareFromTemplate("share:")).toBeNull();
    expect(shareFromTemplate(`share:${"a".repeat(65)}`)).toBeNull();
    expect(shareFromTemplate("Share:abc")).toBeNull();
  });
});

describe("工作流页的装配", () => {
  const view = readSource("features/workflows/WorkflowsView.tsx");

  it("模板通道里带 share: 的走导入,真模板 id 照旧打开社区", () => {
    expect(view).toMatch(/shareFromTemplate\(templateId\)/);
    expect(view).toMatch(/setImportShare\(share\)/);
    expect(view).toMatch(/setCommunityFocus\(templateId\);\s*\n\s*setCommunityOpen\(true\)/);
  });

  it("导入成功后选中刚导入的那一条(不只是弹一句提示)", () => {
    expect(view).toMatch(/onImported=\{\(workflow\) => \{[\s\S]{0,200}?setSelectedId\(workflow\.id\)/);
  });
});
