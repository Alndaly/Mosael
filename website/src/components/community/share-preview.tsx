/**
 * 社区分享详情的**内容预览**:一张只用现有 token 画出来的结构 SVG。
 *
 * 它是 server component:payload 在服务端读、在服务端画,HTML 里只有 `<svg>`,
 * **没有**那份 2MB 的工程 JSON(见详情页的 `loadSharePayload`)。
 *
 * 几何规则全在 `share-preview-model.ts` 里(纯 `.ts`,node 测试能直接 import)。
 * 这里只负责三件事:把模型画成 `<rect>` / `<line>` / `<text>`、给 SVG 一句可读的
 * `aria-label`、以及超过 200 个时在下面写一行「还有 N 个没画」。
 *
 * **不是交互控件**:没有 tabIndex、没有按钮,屏幕阅读器读到的是一张图。
 */
import { getMessages } from "@/i18n/messages";
import type { Locale } from "@/i18n/config";

import { buildSharePreview } from "./share-preview-model";

/**
 * 淡色。**同类同色**由模型里的 tint 决定,这里只把序号翻成 class。
 *
 * 全部取现有 token(`--secondary` / `--brand-soft` / `--muted` / `--accent` / `--foreground`),
 * 深浅色由变量自己翻,不需要第二套颜色。连线统一用 `border`。
 */
const TINTS: readonly string[] = [
  "fill-secondary",
  "fill-brand-soft",
  "fill-muted",
  "fill-accent/10",
  "fill-foreground/10",
];

export function SharePreview({
  locale,
  kind,
  payload,
}: {
  locale: Locale;
  /** 云端分享类型;plugin / 未知类型不会画出任何东西。 */
  kind: string;
  /** `GET /shares/{id}/payload` 的 payload 原文;取不到就是 null。 */
  payload: unknown;
}) {
  const model = buildSharePreview(kind, payload);
  // 空内容、形状不对、插件 manifest —— 都退回「没有预览」,不留一个空框。
  if (!model) return null;

  const t = getMessages(locale).community;
  const title = model.kind === "workflow" ? t.previewWorkflow : t.previewBoard;
  const unit = model.kind === "workflow" ? t.previewNodesUnit : t.previewItemsUnit;
  const hiddenText = model.hidden > 0 ? t.previewHidden.replace("{n}", String(model.hidden)) : null;

  return (
    <figure className="m-0 grid gap-2">
      {/* 固定宽高比 + w-full:SVG 用 viewBox 自动缩放到容器里,页面多宽都不变形。
          底用 bg-card(面板色)而不是 bg-secondary:后者和几档淡色太接近,深色下矩形会糊成一片。 */}
      <div className="aspect-[16/10] w-full overflow-hidden rounded-2xl border border-border bg-card">
        <svg
          viewBox={model.viewBox}
          // 内联 SVG 没有 `<img>` 的等价物;`role="img"` + aria-label 是给它一句可读的名字,
          // 让读屏软件把它当一张图,而不是一堆没有名字的 <rect>。jsx-a11y 的这条建议在 SVG 上不适用。
          // oxlint-disable-next-line jsx-a11y/prefer-tag-over-role
          role="img"
          aria-label={`${title}: ${model.total} ${unit}`}
          focusable="false"
          className="block size-full"
        >
          <g aria-hidden="true">
            {/* 先画线再画矩形:线头钻进卡片底下,不会压在框上。 */}
            {model.lines.map((line, index) => (
              <line
                key={`line-${index}`}
                x1={line.x1}
                y1={line.y1}
                x2={line.x2}
                y2={line.y2}
                strokeWidth={1.25}
                vectorEffect="non-scaling-stroke"
                className="stroke-border"
              />
            ))}
            {model.rects.map((rect, index) => (
              <g key={`rect-${index}`}>
                <rect
                  x={rect.x}
                  y={rect.y}
                  width={rect.width}
                  height={rect.height}
                  rx={rect.radius}
                  strokeWidth={1.25}
                  vectorEffect="non-scaling-stroke"
                  className={`${TINTS[rect.tint % TINTS.length]} stroke-border`}
                />
                {rect.label && (
                  <text
                    x={rect.x + 10}
                    y={rect.y + rect.height / 2}
                    dominantBaseline="middle"
                    fontSize={model.labelSize}
                    className="fill-muted-foreground"
                  >
                    {rect.label}
                  </text>
                )}
              </g>
            ))}
          </g>
        </svg>
      </div>
      {/* 上限的说明放在 SVG 外面:图里再塞字会被一起缩放,读不清。 */}
      {hiddenText && <figcaption className="text-xs text-muted-foreground">{hiddenText}</figcaption>}
    </figure>
  );
}
