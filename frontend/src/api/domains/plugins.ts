/** 插件:装了哪些包、接了哪几个实例、它们的凭据与调用记录。
 *
 * 路径只写在这里 —— 界面调的是有名字、有类型的函数。此前插件页自己拼了十九条路径,
 * 改一个接口要去界面里找字符串,而拼错一个只会在运行时变成一次 404。
 */
import type { components } from "@/api/generated/schema";
import type { Job } from "@/api/domains/jobs";
import { API_BASE, api, getAuthToken } from "@/api/transport";

export type PluginPackage = components["schemas"]["PluginPackageOut"];
export type PluginInstance = components["schemas"]["PluginInstanceOut"];
/** 新建一个连接要交的:名字、配置、建好时一起授予的权限;插件声明了本机服务时可以一开始就定下在本机哪种方式跑(ADR 0041)。 */
export type PluginInstanceCreate = components["schemas"]["PluginInstanceCreate"];
export type PluginInstanceLocalServiceCreate = components["schemas"]["PluginInstanceLocalServiceCreate"];
/** 连接往外连走哪条路:跟随 Mosael / 直连 / 走它自己的代理(见 backend domain/plugins/egress)。 */
export type PluginNetwork = components["schemas"]["PluginNetworkOut"];
export type PluginField = components["schemas"]["PluginFieldOut"];
export type PluginCapabilityStatus = components["schemas"]["PluginCapabilityStatusOut"];
export type PluginToolState = components["schemas"]["PluginToolStateOut"];
export type PluginTool = components["schemas"]["PluginToolOut"];
export type PluginInvocation = components["schemas"]["PluginInvocationOut"];
export type PluginPermissionGrant = components["schemas"]["PluginPermissionGrantOut"];
export type PluginCredential = components["schemas"]["PluginCredentialOut"];
export type PluginMarketEntry = components["schemas"]["PluginMarketEntry"];
export type PluginMarketListing = components["schemas"]["PluginMarketOut"];
export type PluginInstallPreview = components["schemas"]["PluginInstallPreview"];
export type PluginProvidedModel = components["schemas"]["PluginProvidedModelOut"];
/** 模型库(ADR 0034):认领 model_library 的连接上的模型文件、工作流缺的模型、下载走哪条路。 */
export type ModelLibrary = components["schemas"]["ModelLibraryOut"];
export type ModelFile = components["schemas"]["ModelFileOut"];
/** 文本编码器是哪一种、常配哪几种底模(它给好几种底模用,所以不贴底模)。 */
export type ModelEncoder = components["schemas"]["ModelEncoderOut"];
export type MissingModel = components["schemas"]["MissingModelOut"];
export type ModelDetail = components["schemas"]["ModelDetailOut"];
export type ModelResolved = components["schemas"]["ModelResolveOut"];
/** 按文件名找下载地址的结果:候选(同名的在前)和搜不了的站。 */
export type ModelSearch = components["schemas"]["ModelSearchOut"];
/** 一个模型的预览图算不算 NSFW、凭什么(ADR 0038 §9):手动标记压过自动的几条依据。 */
export type ModelNsfw = components["schemas"]["ModelNsfwOut"];
export type ModelNsfwReason = components["schemas"]["ModelNsfwReasonOut"];
/** 一个模型文件的出处(原站上那一页)和怎么知道的。 */
export type ModelSource = components["schemas"]["ModelSourceOut"];
/** 这台服务器上找预览图、写回预览图的路。 */
export type ModelPreviewTools = components["schemas"]["ModelPreviewToolsOut"];
/** 一个「在 Civitai 上找」任务现在怎样:做完了带上它交回的,对上的那几条现在的样子在 `result.found` 里。 */
export type ModelLookupJob = components["schemas"]["ModelLookupJobOut"];
export type ModelLookupFound = components["schemas"]["ModelLookupFoundOut"];
/**
 * 那台服务器上没有预览图、用别处(Civitai)的示例图时挑哪一张:`safest` 分级最低的(缺省),`cover` 作者排在最前的。
 * 界面按「NSFW 预览」那组设置要(照常 → cover,别的 → safest);预览图从哪来、NSFW 的判断都照它。
 */
export type ModelPreviewPick = "safest" | "cover";
/** 工作流库(ADR 0035):认领 workflow_library 的连接上存着的工作流、回收目录里的。 */
export type WorkflowLibrary = components["schemas"]["WorkflowLibraryOut"];
export type WorkflowFile = components["schemas"]["WorkflowFileOut"];
export type WorkflowFileGraph = components["schemas"]["WorkflowGraphOut"];
export type WorkflowTrashed = components["schemas"]["WorkflowTrashedOut"];
export type WorkflowNodePack = components["schemas"]["WorkflowNodePackOut"];
export type WorkflowImport = components["schemas"]["WorkflowLibraryImportOut"];
/** 应用表单(ADR 0038):一张工作流能填的项、文件里的标记、要写进去的样子。 */
export type WorkflowApp = components["schemas"]["WorkflowAppOut"];
export type WorkflowAppSummary = components["schemas"]["WorkflowAppSummaryOut"];
export type WorkflowFillable = components["schemas"]["WorkflowFillableOut"];
export type WorkflowAppOutput = components["schemas"]["WorkflowAppOutputOut"];
export type WorkflowAnnotate = components["schemas"]["WorkflowAnnotateRequest"];
/** 工作台(ADR 0038 §3、§6):写进画布的标记、跑画布上的图。 */
export type WorkflowCanvasMarks = components["schemas"]["WorkflowCanvasMarksOut"];
export type WorkflowCanvasRun = components["schemas"]["WorkflowCanvasRunRequest"];

export const listPluginPackages = () => api<PluginPackage[]>("/api/plugins");
export const pluginDir = () => api<{ path: string }>("/api/plugins/dir");
export const rescanPlugins = () => api<PluginPackage[]>("/api/plugins/scan", { method: "POST" });
/**
 * 卸载插件。它的连接在 Mosael 数据目录里留着本机服务的安装目录时要说怎么处置(不说后端回 409):`remove` 一起删
 * (`keep_models` 先把模型挪到 kept-models)、`keep` 留在磁盘上。
 */
export const removePluginPackage = (packageId: string, localServices?: { choice: "keep" | "remove"; keepModels: boolean }) =>
  api(`/api/plugins/${packageId}${localServices ? `?local_services=${localServices.choice}&keep_models=${localServices.keepModels}` : ""}`, {
    method: "DELETE",
  });

/**
 * 新建连接。带 `local_service` 就一开始用本机服务(要部署管理员):连接、本机服务那一行、端口、写进 `server_url` 的地址在后端
 * 同一个事务里建好,哪一步不成连接也不留下;地址由宿主分,不用交。顶层几项都有缺省(名字空着按清单的模板起)。
 */
export const createPluginInstance = (packageId: string, body: Partial<PluginInstanceCreate>) =>
  api<PluginInstance>(`/api/plugins/${packageId}/instances`, { method: "POST", body: JSON.stringify(body) });
export const updatePluginInstance = (instanceId: string, body: Record<string, unknown>) =>
  api<PluginInstance>(`/api/plugins/instances/${instanceId}`, { method: "PATCH", body: JSON.stringify(body) });
/** 删连接。背后的本机服务的安装目录缺省留着;`remove` 一起删(部署管理员),`keepModels` 先把模型挪到 kept-models。 */
export const removePluginInstance = (instanceId: string, install?: { choice: "keep" | "remove"; keepModels: boolean }) =>
  api(`/api/plugins/instances/${instanceId}${install ? `?install=${install.choice}&keep_models=${install.keepModels}` : ""}`, {
    method: "DELETE",
  });
export const refreshPluginInstance = (instanceId: string) =>
  api<PluginInstance>(`/api/plugins/instances/${instanceId}/refresh`, { method: "POST" });
/** 替宿主做生成的连接**提供的模型**(缓存的那一份;要最新的先 refresh)。 */
export const listPluginInstanceModels = (instanceId: string) =>
  api<PluginProvidedModel[]>(`/api/plugins/instances/${instanceId}/models`);
export const setPluginCapabilities = (instanceId: string, body: Record<string, unknown>) =>
  api<PluginInstance>(`/api/plugins/instances/${instanceId}/capabilities`, { method: "PATCH", body: JSON.stringify(body) });

export const listPluginPermissions = (instanceId: string) =>
  api<PluginPermissionGrant[]>(`/api/plugins/instances/${instanceId}/permissions`);
export const setPluginPermissions = (instanceId: string, body: Record<string, unknown>) =>
  api<PluginPermissionGrant[]>(`/api/plugins/instances/${instanceId}/permissions`, { method: "PATCH", body: JSON.stringify(body) });

export const startPluginOauth = (instanceId: string) =>
  api<{ authorize_url: string }>(`/api/plugins/instances/${instanceId}/oauth`);
export const finishPluginOauth = (instanceId: string, code: string) =>
  api(`/api/plugins/instances/${instanceId}/oauth`, { method: "POST", body: JSON.stringify({ code }) });

/** 一条连接要填的凭据。`filled` 说的是「后端手里有」,`value` 永远是空或掩码 —— 密钥不回传。 */
export type PluginCredentialRow = { key: string; label: string; help: string; secret: boolean; filled: boolean; value: string };
export const listPluginCredentials = (instanceId: string) =>
  api<PluginCredentialRow[]>(`/api/plugins/instances/${instanceId}/credentials`);
export const savePluginCredentials = (instanceId: string, values: Record<string, string>) =>
  api<PluginCredentialRow[]>(`/api/plugins/instances/${instanceId}/credentials`, { method: "PATCH", body: JSON.stringify({ values }) });

export const invokePluginTool = (instanceId: string, tool: string, body: Record<string, unknown>) =>
  api<PluginInvocation>(`/api/plugins/instances/${instanceId}/tools/${tool}/invoke`, { method: "POST", body: JSON.stringify(body) });
export const listPluginInvocations = (instanceId: string) =>
  api<PluginInvocation[]>(`/api/plugins/invocations?instance_id=${encodeURIComponent(instanceId)}`);
export const clearPluginInvocations = (instanceId: string) =>
  api(`/api/plugins/invocations?instance_id=${encodeURIComponent(instanceId)}`, { method: "DELETE" });
export const removePluginInvocation = (invocationId: string) =>
  api(`/api/plugins/invocations/${invocationId}`, { method: "DELETE" });

export const listPluginMarket = () => api<PluginMarketListing>("/api/plugins/market");
/**
 * `advertisedVersion`:从市场点的时候,索引给这一条写的版本(从链接装时留空)。有它,后端才认得出
 * 「从市场更新、而包里其实不比装着的新」—— 那时不装、也不报「已更新」,而是说新版本还没发布。
 */
export const previewPluginInstall = (url: string, advertisedVersion = "", sha256 = "") =>
  api<PluginInstallPreview>("/api/plugins/install/preview", {
    method: "POST",
    body: JSON.stringify({ url, advertised_version: advertisedVersion, sha256 }),
  });
/** `sha256`:市场索引给这个包写的摘要,后端下载后核对,对不上不装。从链接装时留空。 */
export const installPlugin = (url: string, overwrite: boolean, advertisedVersion = "", sha256 = "") =>
  api("/api/plugins/install", {
    method: "POST",
    body: JSON.stringify({ url, overwrite, advertised_version: advertisedVersion, sha256 }),
  });


// --- 模型库(ADR 0034) ---------------------------------------------------------

/** 现问插件:这个连接上的全部模型文件(第一次要读文件头,几百个文件要几秒)。 */
export const getModelLibrary = (instanceId: string, pick: ModelPreviewPick = "safest") =>
  api<ModelLibrary>(`/api/plugins/instances/${instanceId}/model-library?${new URLSearchParams({ pick })}`);

export const getModelDetail = (instanceId: string, folder: string, name: string) =>
  api<ModelDetail>(`/api/plugins/instances/${instanceId}/model-library/detail?${new URLSearchParams({ folder, name })}`);

/** 一个链接(HuggingFace 文件、Civitai 页面或下载链接、ModelScope 的模型页或文件、别的直链)指的是哪个文件。 */
export const resolveModelLink = (instanceId: string, url: string) =>
  api<ModelResolved>(`/api/plugins/instances/${instanceId}/model-library/resolve`, {
    method: "POST",
    body: JSON.stringify({ url }),
  });

/** 按文件名去 HuggingFace / ModelScope / Civitai 找下载地址(工作流里只写了文件名的模型)。每个候选的 `url` 交给
 * `resolveModelLink` 正好解析到那个文件;一个站搜不了只进 `failed`。`folder`:要放进的模型目录(排序用)。 */
export const searchModelSources = (instanceId: string, filename: string, folder = "") =>
  api<ModelSearch>(`/api/plugins/instances/${instanceId}/model-library/search`, {
    method: "POST",
    body: JSON.stringify({ filename, folder }),
  });

/** 下到这个连接的那台服务器上:一个后台任务(进度、取消都在任务上)。 */
export const startModelDownload = (
  instanceId: string,
  body: { workspace_id: string; url: string; folder: string; filename: string },
) => api<Job>(`/api/plugins/instances/${instanceId}/model-library/downloads`, { method: "POST", body: JSON.stringify(body) });

/**
 * 在 Civitai 上找这几个文件(不给 `files` 是这台服务器上没有预览图的全部),`save` 时找到的顺手存成预览图:一个后台任务
 * (按哈希找要那台机器把整个文件读一遍)。
 */
export const startModelLookup = (
  instanceId: string,
  body: { workspace_id: string; files?: { folder: string; name: string }[] | null; save?: boolean; pick?: ModelPreviewPick;
          refresh?: boolean },
) => api<Job>(`/api/plugins/instances/${instanceId}/model-library/lookups`, { method: "POST", body: JSON.stringify(body) });

/** 一个找、补预览图任务现在怎样(界面轮询它):做完了带上对上的那几条现在的样子,当场改模型库里那几条,不等整份重列。 */
export const getModelLookup = (instanceId: string, jobId: string) =>
  api<ModelLookupJob>(`/api/plugins/instances/${instanceId}/model-library/lookups/${jobId}`);

/** 把 Mosael 里显示的那张 Civitai 示例图存成这个文件在那台服务器上的预览图。按文件名对上的要 `confirmed`。 */
export const saveModelPreview = (
  instanceId: string,
  body: { folder: string; name: string; pick: ModelPreviewPick; confirmed?: boolean },
) => api<{ folder: string; name: string; saved: string }>(`/api/plugins/instances/${instanceId}/model-library/save-preview`, {
  method: "POST",
  body: JSON.stringify(body),
});

/** 手动标一个模型文件的预览图是不是 NSFW(`nsfw: null` 去掉标记,回到自动判断)。只记在 Mosael 这边。 */
export const markModelNsfw = (instanceId: string, body: { folder: string; name: string; nsfw: boolean | null }) =>
  api<ModelNsfw>(`/api/plugins/instances/${instanceId}/model-library/nsfw`, { method: "PUT", body: JSON.stringify(body) });

/** 本机识别 NSFW 预览图(ADR 0038 §9):权重下了没有、识别的进度。全部连接共用一份。 */
export type ModelLocalNsfw = components["schemas"]["ModelLocalNsfwOut"];
export const getLocalNsfw = () => api<ModelLocalNsfw>("/api/model-library/local-nsfw");
/** 下载本机识别的权重(只给部署管理员;后台下,回当时的状态)。 */
export const installLocalNsfw = () => api<ModelLocalNsfw>("/api/model-library/local-nsfw/install", { method: "POST" });

/**
 * 选文本编码器的那一格:这种节点**每一种** type 配哪几种编码器(`by_type`),和节点上选 type 的那一格(`type_widget`;
 * 没有 type 可选的加载节点是 null,`by_type` 只有一项)。界面照节点现在的 type 自己挑(见 workbenchLogic.pickRecipe)。
 */
export type NodeEncoders = components["schemas"]["ModelNodeEncodersOut"];
/** 挑出来的那一份:节点现在的 type、在它配方里的几种(`fits`)、ComfyUI 不看 type 的几种(`any_type`)。 */
export type EncoderRecipe = components["schemas"]["ModelEncoderRecipeOut"] & { type: string };
/**
 * 工作台的「模型库」面板:画布上选中的节点那几格(节点类型 + 输入名)各选的是哪个模型目录的文件(不是的为空串),选文本
 * 编码器的那一格再带上 `encoders`(其余为 null)。**答案只看这两样**:节点上填了什么、type 选了什么都不问 —— 按它们缓存,
 * 填一个模型、换一个节点(同一种)都不再问。
 */
export const getNodeFolders = (instanceId: string, nodes: components["schemas"]["ModelNodeFolderIn"][]) =>
  api<components["schemas"]["ModelNodeFoldersOut"]>(`/api/plugins/instances/${instanceId}/model-library/node-folders`, {
    method: "POST",
    body: JSON.stringify({ nodes }),
  });

// --- 工作流库(ADR 0035) -------------------------------------------------------

/** 现问插件:这个连接上存着的全部工作流;给了工作区就带上那个工作区里最近一次用它生成的产出、谁在用它。 */
export const getWorkflowLibrary = (instanceId: string, workspaceId: string) =>
  api<WorkflowLibrary>(`/api/plugins/instances/${instanceId}/workflow-library?${new URLSearchParams({ workspace_id: workspaceId })}`);

/** 一张工作流的原文(导出)。 */
export const getWorkflowContent = (instanceId: string, path: string) =>
  api<{ path: string; content: Record<string, unknown> }>(
    `/api/plugins/instances/${instanceId}/workflow-library/content?${new URLSearchParams({ path })}`,
  );

const workflowWrite = (
  instanceId: string,
  op: "copy" | "rename" | "trash" | "restore" | "save" | "folders" | "folders/rename" | "folders/trash",
  body: Record<string, unknown>,
) =>
  api<{ path: string }>(`/api/plugins/instances/${instanceId}/workflow-library/${op}`, {
    method: "POST",
    body: JSON.stringify(body),
  });

/** 在那台服务器上复制一张。撞名回 409(`detail.suggestion` 是一个建议名),不覆盖。 */
export const copyWorkflow = (instanceId: string, path: string, newPath: string) =>
  workflowWrite(instanceId, "copy", { path, new_path: newPath });
/** 改名 / 挪目录。撞名同上。 */
export const renameWorkflow = (instanceId: string, path: string, newPath: string) =>
  workflowWrite(instanceId, "rename", { path, new_path: newPath });
/** 「删除」:挪进那台服务器上的回收目录,能恢复。 */
export const trashWorkflow = (instanceId: string, path: string) => workflowWrite(instanceId, "trash", { path });
/** 从回收目录挪回去;不给新名字就回原处(被占了回 409)。 */
export const restoreWorkflow = (instanceId: string, path: string, newPath = "") =>
  workflowWrite(instanceId, "restore", { path, new_path: newPath });

/** 在那台服务器的 workflows/ 里新建一个文件夹(相对 workflows/,可以带上级)。已经有了回 409(带建议名)。 */
export const createWorkflowFolder = (instanceId: string, path: string) => workflowWrite(instanceId, "folders", { path });
/** 文件夹改名 / 挪到别的文件夹里:里面的工作流跟着换路径。目标已经有了回 409(带建议名)。 */
export const renameWorkflowFolder = (instanceId: string, path: string, newPath: string) =>
  workflowWrite(instanceId, "folders/rename", { path, new_path: newPath });
/** 删除一个文件夹:只删空的,挪进回收目录。里面还有文件回 409(`detail.code` 是 `not_empty`,带着几个)。 */
export const trashWorkflowFolder = (instanceId: string, path: string) => workflowWrite(instanceId, "folders/trash", { path });

/** 导入前先让插件认一遍(不改那台机器):一段文字(JSON 或链接)、一个文件(base64 带文件名)、一个链接,只给一样。 */
export const inspectWorkflowImport = (
  instanceId: string,
  body: { text?: string; data?: string; filename?: string; url?: string },
) =>
  api<WorkflowImport>(`/api/plugins/instances/${instanceId}/workflow-library/inspect`, {
    method: "POST",
    body: JSON.stringify(body),
  });
/** 把导入的那张(界面格式)存进那台服务器的 workflows/。撞名回 409(带建议名),不覆盖。 */
export const saveImportedWorkflow = (instanceId: string, path: string, content: Record<string, unknown>) =>
  workflowWrite(instanceId, "save", { path, content });

/** 一张工作流的应用表单(ADR 0038):全部能填的项、交回结果的输出节点、文件里的标记、读到时的改动时间。 */
export const getWorkflowApp = (instanceId: string, path: string) =>
  api<WorkflowApp>(`/api/plugins/instances/${instanceId}/workflow-library/app?${new URLSearchParams({ path })}`);
/**
 * 改那台服务器上一张工作流的应用表单和结果标记:只改 `mosael` 那几处,**覆盖写**(调之前界面上确认过)。带着读到时的
 * 改动时间(`modified`);那张在这之间被改过就不写,回 409(`detail.code === "stale"`)。
 */
export const annotateWorkflow = (instanceId: string, body: WorkflowAnnotate) =>
  api<{ path: string; modified?: number | null }>(`/api/plugins/instances/${instanceId}/workflow-library/annotate`, {
    method: "POST",
    body: JSON.stringify(body),
  });

/** 工作台的「应用」面板:画布上现在这张(界面格式,含没存的改动)的应用表单。没有路径和改动时间 —— 改的是画布。 */
export const getCanvasApp = (instanceId: string, content: Record<string, unknown>) =>
  api<WorkflowApp>(`/api/plugins/instances/${instanceId}/workflow-library/app/live`, {
    method: "POST",
    body: JSON.stringify({ content }),
  });
/** 应用表单和结果标记写进画布要改成的样子(界面经桥改画布上的节点;存盘是 ComfyUI 自己的保存)。不写文件。 */
export const getCanvasMarks = (
  instanceId: string,
  body: { content: Record<string, unknown>; app: WorkflowAnnotate["app"]; results: string[] },
) =>
  api<WorkflowCanvasMarks>(`/api/plugins/instances/${instanceId}/workflow-library/app/marks`, {
    method: "POST",
    body: JSON.stringify(body),
  });
/** 工作台的「运行」:跑画布上现在这张,建一个普通的生成任务(模型是 `path` 那张工作流;新建的要先存一次)。 */
export const runCanvas = (instanceId: string, body: WorkflowCanvasRun) =>
  api<{ generation: { id: string; job_id?: string | null; kind: string }; job: Job }>(
    `/api/plugins/instances/${instanceId}/workflow-library/run`,
    { method: "POST", body: JSON.stringify(body) },
  );

/** 经这个连接(ComfyUI-Manager)装缺的节点包:一个后台任务,装完要重启 ComfyUI 才加载。 */
export const startNodeInstall = (instanceId: string, body: { workspace_id: string; packs: string[] }) =>
  api<Job>(`/api/plugins/instances/${instanceId}/workflow-library/install-nodes`, { method: "POST", body: JSON.stringify(body) });
/** 经这个连接(ComfyUI-Manager)重启那台 ComfyUI,等它回来。 */
export const rebootWorkflowServer = (instanceId: string) =>
  api<{ back: boolean }>(`/api/plugins/instances/${instanceId}/workflow-library/reboot`, { method: "POST" });

function modelImageUrl(variant: "preview" | "thumbnail", instanceId: string, folder: string, name: string,
                       pick: ModelPreviewPick): string {
  const params = new URLSearchParams({ folder, name, pick });
  const token = getAuthToken();
  if (token) params.set("token", token);
  return `${API_BASE}/api/plugins/instances/${instanceId}/model-library/${variant}?${params}`;
}

/** 预览图原图(详情页的大图)。`<img>` 带不了请求头,凭据走 `?token=`(和素材的图同一条旁路)。 */
export const modelPreviewUrl = (instanceId: string, folder: string, name: string, pick: ModelPreviewPick = "safest") =>
  modelImageUrl("preview", instanceId, folder, name, pick);

/** 预览图的缩略图(长边不超过 512):卡片、列表行、选模型的下拉用它 —— 一屏几十张不解原图。 */
export const modelThumbnailUrl = (instanceId: string, folder: string, name: string, pick: ModelPreviewPick = "safest") =>
  modelImageUrl("thumbnail", instanceId, folder, name, pick);
