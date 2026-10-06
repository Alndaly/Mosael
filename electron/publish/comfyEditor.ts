/**
 * 工作台(ADR 0038)里打开一张存着的工作流(工作流库「在工作台里打开」,ADR 0035 §4):在这个 ComfyUI 连接自己的内嵌视图里,
 * 把指定的那张打开;「新建」(ADR 0038 §8)在同一个视图里开一张新的。
 *
 * ComfyUI 前端(1.5x)的地址只认 `?template=` / `?share=` / `#<图 id>`,打不开一张存着的工作流。所以页面就绪之后由
 * 主进程执行一段**写死的**脚本:同步前端自己的工作流列表,按 `workflows/<路径>` 找到那一张,没载入就载入,交给画布打开
 * —— 和在 ComfyUI 左边「工作流」里点它走同一条路(已经开着、改过没存的,改动留着)。脚本里只有两个变量:路径和期望的
 * 来源,都经 JSON 编码嵌进去,渲染层送不进别的代码;来源对不上(视图停在别的站点)就什么都不做。新建只执行前端自己的
 * 「新建」命令,先探测有没有。
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

/** 新建的结果:开了一张新的 / 这版前端没有「新建」命令 / 视图不在这台 ComfyUI 上 / 前端一直没就绪。 */
export type ComfyNewOutcome = "created" | "unsupported" | "elsewhere" | "notReady";

/** ComfyUI 自己菜单里「工作流 → 新建」(和标签栏上的 +)执行的命令:一张空白的新工作流,开在新标签里。 */
export const NEW_WORKFLOW_COMMAND = "Comfy.NewBlankWorkflow";

/**
 * 新建一张工作流的脚本:和用户在 ComfyUI 里点「新建」走同一条命令(前端的命令仓库 `extensionManager.command`)。
 * 先探测这版前端有没有这条命令 —— 没有就什么都不做,说「不支持」,界面让用户自己在 ComfyUI 里点。开着的那几张
 * (可能有没存的改动)都留着:新建是开一个新标签。存盘照旧是 ComfyUI 自己的(Ctrl+S)。
 */
export function comfyNewWorkflowScript(origin: string): string {
  return `(async () => {
  if (location.origin !== ${JSON.stringify(origin)}) return "elsewhere";
  const commands = window.app && window.app.extensionManager && window.app.extensionManager.command;
  const listed = commands && Array.isArray(commands.commands) ? commands.commands : [];
  if (!commands || typeof commands.execute !== "function" ||
      !listed.some((one) => one && one.id === ${JSON.stringify(NEW_WORKFLOW_COMMAND)})) return "unsupported";
  await commands.execute(${JSON.stringify(NEW_WORKFLOW_COMMAND)});
  return "created";
})()`;
}

/** 视图亮出来之后:回到这台 ComfyUI、等前端就绪(见 openWorkflowInPage)。就绪了回 true。 */
async function readyInPage(driver: Pick<PageDriver, "evaluate" | "waitForFunction" | "goto">, url: string): Promise<boolean> {
  const origin = new URL(url).origin;
  const here = await driver.evaluate<string>("location.origin").catch(() => "");
  if (here && here !== "null" && here !== origin) await driver.goto(url);
  return driver.waitForFunction(comfyReady(origin), READY_TIMEOUT_MS);
}

/**
 * 视图已经亮出来之后的那一段:不在这台 ComfyUI 上(用户在这个视图里点去了别处)就先回来;刚建的视图还在载入
 * (`about:blank` 的来源是 `"null"`)就等它,不重复导航。前端就绪了才跑打开脚本。
 */
export async function openWorkflowInPage(
  driver: Pick<PageDriver, "evaluate" | "waitForFunction" | "goto">,
  request: { url: string; path: string },
): Promise<ComfyOpenOutcome> {
  if (!(await readyInPage(driver, request.url))) return "notReady";
  return driver.evaluate<ComfyOpenOutcome>(comfyOpenWorkflowScript(request.path, new URL(request.url).origin), OPEN_TIMEOUT_MS);
}

/** 同上,新建一张(见 comfyNewWorkflowScript)。 */
export async function newWorkflowInPage(
  driver: Pick<PageDriver, "evaluate" | "waitForFunction" | "goto">,
  request: { url: string },
): Promise<ComfyNewOutcome> {
  if (!(await readyInPage(driver, request.url))) return "notReady";
  return driver.evaluate<ComfyNewOutcome>(comfyNewWorkflowScript(new URL(request.url).origin), OPEN_TIMEOUT_MS);
}
