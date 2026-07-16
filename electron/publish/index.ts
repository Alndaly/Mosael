// 发布执行器的打包入口。esbuild 把这里连同 pageDriver/accountViews/adapters/... 打成
// 单个 CommonJS(electron/publish.bundle.cjs),供 electron/main.cjs require。
export {
  startPublishWorker,
  stopPublishWorker,
  openLogin,
  openPage,
  hidePublishView,
} from "./worker";
// 语言切换占位:i18n 模块 v1 中文直出。
export { setLocale } from "./i18n";
