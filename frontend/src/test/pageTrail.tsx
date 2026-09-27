import React from "react";

import { PageTrailProvider, type PageTrail } from "@/components/layout/pageTrail";

/**
 * 测试里没有顶栏(AppShell):把页面交上来的路径接住,画成一排按钮 —— 和顶栏同样的规矩:页面名(`trail-root`)
 * 和中间几段点得回去,最后一段给了改名就是改名键,否则是纯文字。断言「现在在哪一层」看这一排。
 */
export function WithPageTrail({ children }: { children: React.ReactNode }) {
  const [trail, setTrail] = React.useState<PageTrail | null>(null);
  return (
    <PageTrailProvider value={setTrail}>
      <nav aria-label="page-trail">
        {trail?.onRoot && (
          <button type="button" onClick={trail.onRoot}>
            trail-root
          </button>
        )}
        {trail?.segments.map((segment, index) => {
          const last = index === trail.segments.length - 1;
          if (last && segment.onRename) {
            return (
              <button key={index} type="button" aria-current="page" onClick={segment.onRename}>
                {segment.label}
              </button>
            );
          }
          if (!last && segment.onSelect) {
            return (
              <button key={index} type="button" onClick={segment.onSelect}>
                {segment.label}
              </button>
            );
          }
          return (
            <span key={index} aria-current={last ? "page" : undefined}>
              {segment.label}
            </span>
          );
        })}
      </nav>
      {children}
    </PageTrailProvider>
  );
}
