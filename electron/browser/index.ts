// 内嵌浏览器的打包入口。esbuild 把这里连同它引到的一切打成单个 CommonJS(electron/browser.bundle.cjs),
// 供 electron/main.cjs require。分层见 browser/layering.test.ts:driver → views → page / pool / comfy / publish。
//
// 启动顺序:先 startViewHost(视图、浮层),再 startComfyHost、startPublishWorker、startBrowserWorker(都借宿主的视图);
// 停的时候反过来,最后 stopViewHost。
export {
  startViewHost,
  stopViewHost,
  openPoolLogin,
  clearPoolProfile,
  navigateView,
  viewBack,
  viewForward,
  viewReload,
  switchViewPage,
  closeViewPage,
  reorderViewPages,
  newViewPage,
  snapshotViewPage,
  showFloat,
  focusViewPage,
  focusHostWindow,
  copyHostSelectionIfAny,
  hideFloat,
  showToasts,
  hideToasts,
  republishViewState,
  hostZoomChanged,
  embeddedViewVisible,
  hideEmbeddedView,
  setPanelLayout,
  closePanel,
  setPanelMuted,
  setPanelsHidden,
  setHostLayer,
  clearHostLayer,
} from "./views/viewHost";
// ComfyUI 工作台(ADR 0038 §3):借宿主的视图开工作台会话。
export {
  startComfyHost,
  stopComfyHost,
  setComfyViewNavigation,
  openComfyWorkbench,
  comfyWorkbenchCall,
  releaseWorkbenchView,
} from "./comfy/comfyHost";
// 发布执行器:轮询后端认领发布任务、账号登录与复检。
export {
  startPublishWorker,
  stopPublishWorker,
  openLogin,
  openPage,
  signOutAccount,
  inspectAccount,
} from "./publish/publishWorker";
// 浏览器会话顶栏的页面工具:只作用于前台视图(见 pageTarget)。
export { capturePage, beginRegionCapture, finishRegionCapture } from "./page/pageCapture";
export { probeVideos } from "./page/pageVideos";
export { listImages, fetchImages } from "./page/pageImages";
export { readPage } from "./page/pageRead";
export { saveDownload } from "./page/pageDownloads";
// 浏览器自动化 worker(RPA / 智能体):与发布 worker 并列的第二个拉取循环。
export { startBrowserWorker, stopBrowserWorker } from "./pool/browserWorker";
// 界面语言:本 bundle 打包了自己那份 i18n.cjs,由主进程在语言变化时转告(见 main.cjs applyLocale)。
export { setLocale } from "../i18n.cjs";
