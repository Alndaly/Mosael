// 内嵌浏览器里的**坐标换算**,只有这一份(P5/P6)。
//
// 四套坐标系同时存在,而它们之间的乘法此前散在三处各写一遍 —— 每一处都是一次脱靶的机会:
//
//   页面 CSS 像素   getBoundingClientRect / innerWidth(页面的自己的尺子)
//   视图 CSS 像素   面板里页面被 setZoomFactor(z) 缩放后,`视图px = 页面px × z`
//   窗口 DIP        view.setBounds / sendInputEvent 要的是它,`DIP = CSS × hostZoom`
//   屏幕点          screen.getCursorScreenPoint 那一套,`屏幕 = 窗口内容原点 + DIP`
//   物理像素        capturePage 在 Retina 上给 2× 图
//
// 规矩:**只有这个文件里出现这些乘法**。别处要坐标就去问它 —— 出现第二份,就是下一次脱靶。

/** 主窗口缩放(渲染层「视图 → 放大 / 缩小」)。0/NaN 都按 1 处理:除零比脱靶更难查。 */
function safeZoom(value) {
  const zoom = Number(value);
  return Number.isFinite(zoom) && zoom > 0 ? zoom : 1;
}

/** 页面 CSS → 视图 CSS(面板缩放)。 */
function pageToView(value, pageZoom) {
  return Number(value) * safeZoom(pageZoom);
}

/**
 * CSS 矩形 → 原生视图要的 DIP。
 *
 * **往里取整**:x/y 向上、右下向下 —— 原生视图宁可窄半个像素,也不压住外壳的边(顶栏、页面列表)。
 */
function cssToDip(rect, hostZoom) {
  const zoom = safeZoom(hostZoom);
  const x = Math.ceil(rect.x * zoom - 1e-6) || 0; // `|| 0`:Math.ceil(-1e-7) 是 -0
  const y = Math.ceil(rect.y * zoom - 1e-6) || 0;
  const right = Math.floor((rect.x + rect.width) * zoom + 1e-6);
  const bottom = Math.floor((rect.y + rect.height) * zoom + 1e-6);
  return { x, y, width: Math.max(0, right - x), height: Math.max(0, bottom - y) };
}

/** DIP 矩形 → 渲染层画外壳用的 CSS 矩形(让位计算反着来的时候用)。 */
function dipToCss(rect, hostZoom) {
  const zoom = safeZoom(hostZoom);
  return {
    x: rect.x / zoom,
    y: rect.y / zoom,
    width: rect.width / zoom,
    height: rect.height / zoom,
  };
}

/** 页面 CSS → DIP(一次乘完:面板缩放 × 宿主缩放)。可信点击要它。 */
function pageToDip(value, { pageZoom = 1, hostZoom = 1 } = {}) {
  return Number(value) * safeZoom(pageZoom) * safeZoom(hostZoom);
}

/**
 * `capturePage` 的图 → 窗口 CSS 尺寸。
 *
 * Retina 上这张图是**物理像素**(800×568 的窗口拍出 1600×1136),而 `sendInputEvent` 认 CSS ——
 * 不归一化,模型按图给的坐标点下去会差整整一倍(全偏到左上角)。返回 null = 不需要缩。
 */
function captureToCss(captured, cssSize) {
  const width = Math.round(Number(cssSize?.[0]) || 0);
  const height = Math.round(Number(cssSize?.[1]) || 0);
  const shotWidth = Math.round(Number(captured?.width) || 0);
  const shotHeight = Math.round(Number(captured?.height) || 0);
  if (!width || !height || !shotWidth || !shotHeight) return null;
  if (shotWidth === width && shotHeight === height) return null;
  return { width, height };
}

module.exports = { captureToCss, cssToDip, dipToCss, pageToDip, pageToView, safeZoom };
