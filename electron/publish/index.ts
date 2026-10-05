// 发布执行器的打包入口。esbuild 把这里连同 pageDriver/accountViews/adapters/... 打成
// 单个 CommonJS(electron/publish.bundle.cjs),供 electron/main.cjs require。
export {
  startPublishWorker,
  stopPublishWorker,
  openLogin,
  openPoolLogin,
  openComfyWorkflow,
  newComfyWorkflow,
  openPage,
  signOutAccount,
  clearPoolProfile,
  inspectAccount,
  navigateView,
  viewBack,
  viewForward,
  viewReload,
  switchViewPage,
  closeViewPage,
  reorderViewPages,
  newViewPage,
  setPagesInset,
  snapshotViewPage,
  coverViewPage,
  showFloat,
  focusViewPage,
  hideFloat,
  republishViewState,
  embeddedViewVisible,
  hidePublishView,
  setPanelLayout,
  closePanel,
  setPanelMuted,
} from "./publishWorker";
// 浏览器会话顶栏的页面工具:只作用于前台视图(见 pageTarget)。
export { capturePage, beginRegionCapture, finishRegionCapture } from "./pageCapture";
export { setToolsInset } from "./pageTarget";
export { probeVideos } from "./pageVideos";
export { listImages, fetchImages } from "./pageImages";
export { readPage } from "./pageRead";
export { saveDownload } from "./pageDownloads";
// 浏览器自动化 worker(RPA / 智能体):与发布 worker 并列的第二个拉取循环。
export { startBrowserWorker, stopBrowserWorker } from "./browserWorker";
// 界面语言:本 bundle 打包了自己那份 i18n.cjs,由主进程在语言变化时转告(见 main.cjs applyLocale)。
export { setLocale } from "../i18n.cjs";
