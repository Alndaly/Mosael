// 发布执行器的打包入口。esbuild 把这里连同 pageDriver/accountViews/adapters/... 打成
// 单个 CommonJS(electron/publish.bundle.cjs),供 electron/main.cjs require。
export {
  startPublishWorker,
  stopPublishWorker,
  openLogin,
  openPoolLogin,
  openPage,
  inspectAccount,
  navigateView,
  viewBack,
  viewForward,
  viewReload,
  hidePublishView,
} from "./worker";
// 浏览器自动化 worker(RPA / 智能体):与发布 worker 并列的第二个拉取循环。
export { startBrowserWorker, stopBrowserWorker } from "./browserWorker";
// 语言切换占位:i18n 模块 v1 中文直出。
export { setLocale } from "./i18n";
