import React from "react";

import { assetFileUrl, assetPreviewUrl, getAsset, isNotFound } from "@/api/client";

/**
 * 一张素材图此刻该取哪个地址、取不到时是哪一种取不到。
 *
 * - `loading`:先取预览地址(HEIC 这类浏览器解不了的原图,后端转好了一份),不行再取原文件;
 * - `gone`:两个都取不到,而且服务端**明确说这份素材不在了**(404)—— 才说「素材已删除」;
 * - `unavailable`:两个都取不到,但素材还在(或查不到它在不在:断网、后端重启、超时)。这是一次偶发的失败:
 *   隔一会儿自己再取一遍(`RETRY_DELAYS_MS`),人也可以点「重试」。
 *
 * 此前两个地址一取不到就一律写「素材已删除」,也不再取:后端重启那一下、网络抖一下,画布上的图就都成了
 * 「已删除」,要切页面再回来才恢复 —— 用户会顺手把那一格删掉。
 */
export type AssetImageState = "loading" | "gone" | "unavailable";

/** 偶发失败后自己再取的间隔:够等一次后端重启,不至于对着一份真打不开的图一直请求。 */
const RETRY_DELAYS_MS = [2_000, 8_000, 30_000];

export function useAssetImage(assetId: string): {
  src: string;
  state: AssetImageState;
  /** `<img onError>`:预览地址不行换原文件,原文件也不行就去问这份素材还在不在。 */
  onError: () => void;
  retry: () => void;
} {
  //: 状态按 assetId 记着:换了一份素材就从头取,不带着上一份的失败。
  const [attempt, setAttempt] = React.useState({ assetId, source: "preview" as "preview" | "file", state: "loading" as AssetImageState, round: 0 });
  const current = attempt.assetId === assetId ? attempt : { assetId, source: "preview" as const, state: "loading" as const, round: 0 };

  const retry = React.useCallback(() => {
    setAttempt((last) => ({ assetId, source: "preview", state: "loading", round: (last.assetId === assetId ? last.round : 0) + 1 }));
  }, [assetId]);

  const onError = React.useCallback(() => {
    if (current.source === "preview") {
      setAttempt({ ...current, source: "file" });
      return;
    }
    void getAsset(assetId).then(
      () => setAttempt((last) => (last.assetId === assetId ? { ...last, state: "unavailable" } : last)),
      (error: unknown) =>
        setAttempt((last) => (last.assetId === assetId ? { ...last, state: isNotFound(error) ? "gone" : "unavailable" } : last)),
    );
  }, [assetId, current]);

  //: 偶发失败:隔一会儿自己再取。重试的次数用完了就停,剩下的交给「重试」按钮。
  const delay = current.state === "unavailable" ? RETRY_DELAYS_MS[current.round] : undefined;
  React.useEffect(() => {
    if (delay === undefined) return;
    const timer = window.setTimeout(retry, delay);
    return () => window.clearTimeout(timer);
  }, [delay, retry]);

  //: 重试的地址带上第几轮:浏览器对同一个地址的失败会直接用缓存的结果,不真的再取。
  const base = current.source === "preview" ? assetPreviewUrl(assetId) : assetFileUrl(assetId);
  const src = current.round === 0 ? base : `${base}${base.includes("?") ? "&" : "?"}retry=${current.round}`;
  return { src, state: current.state, onError, retry };
}
