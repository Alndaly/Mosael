import type { QueryClient } from "@tanstack/react-query";

import { refreshPluginInstance } from "@/api/client";
import type { PluginPackage } from "@/api/domains/plugins";
import { boardKeys, generationKeys, providerKeys } from "@/api/queryKeys";
import { invalidateResources } from "@/api/resourceKeys";

/**
 * **跟着插件连接走的那些缓存**:装、卸、建连接、改配置、启停、授权、刷新之后都要失效。
 *
 * 插件不只出现在插件页。一条生成插件连接(ComfyUI)就是 AI 工作台里的一家供应商和一串模型,暴露出来的
 * 工具是工作流的节点、画板上一格的能力 / 空格子的生成器、节点表单里「用哪个连接」的下拉。此前插件页只失效了自己那几份,
 * 于是在插件页启用 ComfyUI、点「刷新模型」之后回到 AI 工作台,模型选择器还是旧的那一份,要等一分钟
 * (默认 staleTime)或者刷新整页才出现 —— 用户以为刷新没成功。
 *
 * 前缀匹配(见 api/queryKeys):键写到最短,每一份细分的缓存都能匹配到。
 */
export const PLUGIN_DEPENDENT_KEYS = [
  ["plugins"],
  ["plugin-models"],
  // 工作流 / 画板:插件工具是节点和格子的能力;「用哪个连接」的下拉从插件连接列出。
  ["workflow-node-types"],
  // 插件节点为什么用不了(没接、停用、工具没勾选):连接一变原因就变,不该等 30 秒的 staleTime。
  ["workflow-node-unusable"],
  ["workflow-field-options"],
  ["board-producers"],
  // 生成:插件生成连接是一家供应商,模型行是插件目录的缓存(ADR 0020)。
  generationKeys.options(),
  providerKeys.profiles(),
  providerKeys.defaults(),
  providerKeys.models(),
  providerKeys.capabilityModels(),
  // 存着 (连接, 模型) 或插件工具名的那几处:目录重拉时插件报的改名(`moved`,ADR 0045 §6)、在工作流库里改名挪目录
  // (修订之二)都会在后端当场改写它们 —— 生成会话、生成记录、画板格子、工作流节点、定时任务。只失效选项的话,
  // 界面拿着改名前的那一份:刚升级完的会话还指着完整工作流、刚改了名的画板格子说「用不了」,要等一分钟的 staleTime。
  ["generation-sessions"],
  ["generation-jobs"],
  boardKeys.everywhere(),
  ["workflows"],
  ["scheduled-tasks"],
] as const;

export function invalidatePluginDependents(qc: QueryClient): void {
  for (const queryKey of PLUGIN_DEPENDENT_KEYS) void qc.invalidateQueries({ queryKey });
}

/** 正在重拉目录的连接:同一时刻几处都要它重拉(工作台存了一张、工作台关了、工作流库回来)时只拉一次。 */
const refreshing = new Map<string, Promise<void>>();

/**
 * **这个连接上的工作流变了**(存了精简表单、改了名、在工作台里存了一张):先让后端重拉这个连接的目录,再让依赖它的
 * 查询重问。精简表单、工作流的名字都住在那张图里,AI 工作台的「引擎参数」、画板的提示词面板、工作流节点读的是后端按
 * 连接存着的那份目录(ADR 0020)—— 只让界面重问,拿到的还是旧的。
 *
 * **工作流库那份列表也在这里作废**(`workflows` → api/resourceKeys 那张表,ADR 0053):库详情里的「表单」「能填什么」
 * 「能调什么」「交出什么」「用到的模型」全从 `["workflow-library", 连接, 工作区]` 那一份来,而写这张图的路不止一条
 * —— 库里存表单、导入、改名、复制、恢复、升级旧格式标记,以及**工作台里 ComfyUI 自己存盘**(桥报的 `modified` 从有
 * 到无,见 ComfyWorkbench 的 useCatalogFollowsWorkbench)。此前这条路上只有目录重拉:在工作台改完表单回到库详情,
 * 数字和列表还是改之前那一份(维护者报的) —— 那一份 staleTime 30 秒、又不在获焦时重拉,弹窗挂着就一直是旧的。
 * 写在**等目录回来之前**:那次要问插件把每张工作流拉一遍,等它回来再失效,回来的人先看到的还是旧数字。
 * 换成键只有那张表,这里不逐个 key 地拼。
 *
 * 同一个连接正在拉的,后来的那一处接着等同一次,不再叫一遍(插件一次要把那台机器上的每张工作流拉一遍)。拉不成也照样让
 * 界面重问:目录留着上一份,原因在插件页上。
 */
export function refreshConnectionCatalog(qc: QueryClient, instanceId: string): Promise<void> {
  invalidateResources(qc, ["workflows"]);
  const running = refreshing.get(instanceId);
  if (running) return running;
  const done = Promise.resolve()
    .then(() => refreshPluginInstance(instanceId))
    .then(() => undefined, () => undefined)
    .finally(() => {
      refreshing.delete(instanceId);
      invalidatePluginDependents(qc);
    });
  refreshing.set(instanceId, done);
  return done;
}

/** 连接列表住在插件目录那一份缓存里(`["plugins"]`,每个包里一串 `instances`)。 */
export const PLUGIN_PACKAGES_KEY = ["plugins"] as const;

/**
 * 把一个连接的改动**当场**写进插件目录那份缓存,返回改动前的数据(失败时回滚用)。
 *
 * 启停此前只有「成功之后再失效、重问一遍」:而那份缓存重问要走一趟插件(能力、状态、目录)——
 * 用户点一下开关,要等它回来才动(维护者:「点击会有很久的卡顿」)。乐观更新让开关先动;
 * 服务器那一份回来照旧覆盖它(两边说的是同一件事,看不出差别)。
 */
export function patchPluginInstance(
  qc: QueryClient,
  instanceId: string,
  body: Record<string, unknown>,
): PluginPackage[] | undefined {
  const previous = qc.getQueryData<PluginPackage[]>(PLUGIN_PACKAGES_KEY);
  if (!previous) return undefined;
  qc.setQueryData<PluginPackage[]>(
    PLUGIN_PACKAGES_KEY,
    previous.map((pkg) => {
      const instances = pkg.instances ?? [];
      if (!instances.some((instance) => instance.id === instanceId)) return pkg;
      return {
        ...pkg,
        instances: instances.map((instance) =>
          instance.id === instanceId
            //: 开了的时候那颗「需要处理」要一起放掉:服务端那句 `blocked_reason`(未启用)说的是**上一态**,
            //: 留着它就会出现「开关是开的、左边写着未启用」那种自相矛盾(维护者报的)。真还有别的堵着
            //: (缺配置、没授权),重问回来的那一份会照实说 —— 请求在飞的那一段由卡片上的「正在启用…」顶着。
            ? { ...instance, ...body, ...(body.enabled === true ? { blocked_reason: "" } : {}) }
            : instance,
        ),
      };
    }),
  );
  return previous;
}
