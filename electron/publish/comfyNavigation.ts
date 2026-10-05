/**
 * 内嵌 ComfyUI 画布的操控方式:触控板 / 鼠标(维护者:「如果我是 mac 调用的 windows 上面的 comfyui 的服务的话,我的触控板的
 * 交互很奇怪,应该支持切换操控方式」)。
 *
 * ComfyUI 前端(1.25 起)有一个设置 `Comfy.Canvas.NavigationMode`:`standard`(双指滑动平移、捏合 / Ctrl+滚轮缩放,左键拖是框选
 * —— 触控板的手感)、`legacy`(滚轮缩放、在空白处拖动平移 —— 鼠标的手感,也是它的缺省)、`custom`。改它时前端的 onChange 再用
 * `setMany` 一并改 `Comfy.Canvas.LeftMouseClickBehavior` 和 `Comfy.Canvas.MouseWheelScroll`(1.53.10 的前端里查过)。
 *
 * **这几个设置存在 ComfyUI 服务器上、按 ComfyUI 的用户存**:在 Mac 上的 Mosael 里切成触控板,坐在那台 Windows 前面的人打开
 * ComfyUI 也变成了触控板。所以只在这个视图里生效:
 *
 * - 页面就绪后由主进程注入一段**写死的**脚本(`navigationScript`),经前端自己的设置仓库(`extensionManager.setting`)把模式设成
 *   要的那个 —— 和用户在 ComfyUI 设置里改是同一条路,画布当场换手感;
 * - 前端随后要把它写回服务器(`POST /api/settings/<键>`,联动的两个走批量的 `POST /api/settings`):主进程只在这个连接的分区上
 *   拦下这几个键的写回(`settingsWriteVerdict`)。批量里混着别的键时,拦下整批、只把别的键原样补发一次;
 * - 每次载入 / 刷新之后重新设一次(服务器上的值没变,前端每次载入都按服务器上的来)。
 *
 * 这版前端没有这个设置(或者没有 `standard` / `legacy` 这两项)就什么都不做,界面藏起开关、说一句为什么。
 */

/** Mosael 这边的两种操控方式。 */
export type ComfyNavigation = "trackpad" | "mouse";

/** 前端的设置键:操控方式本身。 */
export const NAVIGATION_SETTING = "Comfy.Canvas.NavigationMode";

/** 只在这个视图里生效、不许写回服务器的那几个键:操控方式和它联动改的两个。 */
export const NAVIGATION_KEYS: readonly string[] = [
  NAVIGATION_SETTING,
  "Comfy.Canvas.LeftMouseClickBehavior",
  "Comfy.Canvas.MouseWheelScroll",
];

/** Mosael 的两种 → 前端设置里的值。 */
export const NAVIGATION_VALUES: Readonly<Record<ComfyNavigation, string>> = { trackpad: "standard", mouse: "legacy" };

/** 设的结果:设好了 / 这版前端没有这个设置 / 视图不在这台 ComfyUI 上 / 前端一直没就绪。 */
export type NavigationOutcome = "applied" | "unsupported" | "elsewhere" | "notReady";

/**
 * 在页面里设操控方式的脚本。变量只有来源和值,都经 JSON 编码嵌进去。先探测:设置仓库在、这个设置登记过、可选值里有要的那个,
 * 才设;前端写回服务器那一下被主进程拦了(fetch 报错),本地的值已经换好了 —— 吞掉这个错。
 */
export function navigationScript(origin: string, mode: ComfyNavigation): string {
  const value = NAVIGATION_VALUES[mode];
  return `(async () => {
  if (location.origin !== ${JSON.stringify(origin)}) return "elsewhere";
  const setting = window.app && window.app.extensionManager && window.app.extensionManager.setting;
  if (!setting || typeof setting.get !== "function" || typeof setting.set !== "function") return "unsupported";
  const definition = setting.settings ? setting.settings[${JSON.stringify(NAVIGATION_SETTING)}] : null;
  const options = definition && Array.isArray(definition.options) ? definition.options : [];
  const values = options.map((one) => (one && typeof one === "object" ? one.value : one));
  if (!values.includes(${JSON.stringify(value)})) return "unsupported";
  if (setting.get(${JSON.stringify(NAVIGATION_SETTING)}) !== ${JSON.stringify(value)}) {
    try {
      await setting.set(${JSON.stringify(NAVIGATION_SETTING)}, ${JSON.stringify(value)});
    } catch (error) {
      // 写回服务器被拦下了(只在这个视图里生效):本地的值已经换好
    }
  }
  return setting.get(${JSON.stringify(NAVIGATION_SETTING)}) === ${JSON.stringify(value)} ? "applied" : "unsupported";
})()`;
}

/** 一次请求怎么办:放行 / 拦下 / 拦下、把剩下的键补发一次(`body` 是要补发的 JSON)。 */
export type SettingsVerdict = { action: "allow" } | { action: "block" } | { action: "reissue"; body: string };

const ALLOW: SettingsVerdict = { action: "allow" };
const BLOCK: SettingsVerdict = { action: "block" };
//: `/api/settings`(批量)和 `/api/settings/<键>`(一个);ComfyUI 挂在子路径下时前面还有一段(api_base)
const SETTINGS_PATH = /(?:^|\/)api\/settings(?:\/([^/]+))?\/?$/;

/**
 * 内嵌 ComfyUI 发出的一次请求是不是在把操控方式写回服务器。只看写(GET 放行)、只看设置那条路、只认 `NAVIGATION_KEYS`:
 *
 * - 一个键的写回(`POST /api/settings/<键>`):是那几个键就拦;
 * - 批量写回(`POST /api/settings`,body 是 `{键: 值}`):全是那几个键就拦;混着别的键就拦下整批、补发剩下的(别的设置照常存);
 *   一个都没有就放行。body 读不出来(不是 JSON 对象)放行 —— 那不是前端发的设置。
 */
export function settingsWriteVerdict(request: { method: string; url: string; body?: string | null }): SettingsVerdict {
  if (request.method.toUpperCase() === "GET" || request.method.toUpperCase() === "HEAD") return ALLOW;
  let path: string;
  try {
    path = new URL(request.url).pathname;
  } catch {
    return ALLOW;
  }
  const match = SETTINGS_PATH.exec(path);
  if (!match) return ALLOW;
  if (match[1] !== undefined) {
    let key: string;
    try {
      key = decodeURIComponent(match[1]);
    } catch {
      return ALLOW;
    }
    return NAVIGATION_KEYS.includes(key) ? BLOCK : ALLOW;
  }
  let values: unknown;
  try {
    values = JSON.parse(request.body ?? "");
  } catch {
    return ALLOW;
  }
  if (!values || typeof values !== "object" || Array.isArray(values)) return ALLOW;
  const keys = Object.keys(values);
  if (!keys.some((key) => NAVIGATION_KEYS.includes(key))) return ALLOW;
  const rest = Object.fromEntries(Object.entries(values).filter(([key]) => !NAVIGATION_KEYS.includes(key)));
  return Object.keys(rest).length === 0 ? BLOCK : { action: "reissue", body: JSON.stringify(rest) };
}
