/**
 * 工作流库「在编辑器里打开」(ADR 0035 §4):在这个 ComfyUI 连接自己的内嵌视图里,把指定的那张存着的工作流打开。
 *
 * ComfyUI 前端(1.5x)的地址只认 `?template=` / `?share=` / `#<图 id>`,打不开一张存着的工作流。所以页面就绪之后由
 * 主进程执行一段**写死的**脚本:同步前端自己的工作流列表,按 `workflows/<路径>` 找到那一张,没载入就载入,交给画布打开
 * —— 和在 ComfyUI 左边「工作流」里点它走同一条路(已经开着、改过没存的,改动留着)。脚本里只有两个变量:路径和期望的
 * 来源,都经 JSON 编码嵌进去,渲染层送不进别的代码;来源对不上(视图停在别的站点)就什么都不做。
 */
import type { PageDriver } from "./pageDriver";

/** 打开的结果:打开了 / 那台机器上没有这一张 / 视图不在这台 ComfyUI 上 / 前端一直没就绪(比如要先登录)。 */
export type ComfyOpenOutcome = "opened" | "missing" | "elsewhere" | "notReady";

//: 前端起来要多久:第一次打开要下整套前端、装好扩展,慢的机器上要好几十秒
const READY_TIMEOUT_MS = 60_000;
//: 同步列表 + 取这一张 + 画布载入(大图、缺模型的扫描)
const OPEN_TIMEOUT_MS = 60_000;

/** 页面就绪的判据:来源对得上,前端的工作区(工作流仓库)和 loadGraphData 都在。 */
export function comfyReady(origin: string): string {
  return `location.origin === ${JSON.stringify(origin)} && Boolean(window.app && window.app.extensionManager &&
    window.app.extensionManager.workflow && typeof window.app.loadGraphData === "function")`;
}

/** 打开 `workflows/<path>` 那一张的脚本。交给画布的是一份拷贝,前端工作流仓库里的那份不被画布改动。 */
export function comfyOpenWorkflowScript(path: string, origin: string): string {
  return `(async () => {
  if (location.origin !== ${JSON.stringify(origin)}) return "elsewhere";
  const app = window.app;
  const store = app.extensionManager.workflow;
  if (typeof store.syncWorkflows === "function") await store.syncWorkflows();
  const workflow = store.getWorkflowByPath(${JSON.stringify(`workflows/${path}`)});
  if (!workflow) return "missing";
  if (!workflow.isLoaded) await workflow.load();
  await app.loadGraphData(JSON.parse(JSON.stringify(workflow.activeState)), true, true, workflow);
  return "opened";
})()`;
}

/**
 * 视图已经亮出来之后的那一段:不在这台 ComfyUI 上(用户在这个视图里点去了别处)就先回来;刚建的视图还在载入
 * (`about:blank` 的来源是 `"null"`)就等它,不重复导航。前端就绪了才跑打开脚本。
 */
export async function openWorkflowInPage(
  driver: Pick<PageDriver, "evaluate" | "waitForFunction" | "goto">,
  request: { url: string; path: string },
): Promise<ComfyOpenOutcome> {
  const origin = new URL(request.url).origin;
  const here = await driver.evaluate<string>("location.origin").catch(() => "");
  if (here && here !== "null" && here !== origin) await driver.goto(request.url);
  if (!(await driver.waitForFunction(comfyReady(origin), READY_TIMEOUT_MS))) return "notReady";
  return driver.evaluate<ComfyOpenOutcome>(comfyOpenWorkflowScript(request.path, origin), OPEN_TIMEOUT_MS);
}
