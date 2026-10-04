import React from "react";
import { useMutation } from "@tanstack/react-query";

import type { MessageKey } from "@/app/messages";
import { useI18n } from "@/app/preferences";

import { captureName, saveScreenshot, type PageToolsBridge, type ShotMode } from "./pageActions";
import type { ToolNotice } from "./useToolNotice";

/** 整页长图的高度上限(CSS 像素),和 electron/publish/pageToolsCore 的 MAX_FULL_PAGE_HEIGHT 一致。 */
const FULL_PAGE_LIMIT = 15_000;

const SHOT_NAME: Record<ShotMode, MessageKey> = {
  visible: "browserToolsShotNameVisible",
  full: "browserToolsShotNameFull",
  region: "browserToolsShotNameRegion",
};

export type RegionFrame = { src: string; width: number; height: number };
type Selection = { x: number; y: number; width: number; height: number };

/**
 * 截屏到素材:可见区域 / 整页长图一步到位;框选分两步 —— 主进程冻结画面并藏起网页(beginRegion),
 * 渲染层铺那一帧让人拖框(RegionOverlay),框交回去裁(finishRegion)。截下来的都带着出处入库。
 */
export function useShotTools(tools: PageToolsBridge, workspaceId: string, notice: ToolNotice) {
  const t = useI18n();
  const { say, failed, savedAsset } = notice;
  const [region, setRegion] = React.useState<RegionFrame | null>(null);

  const shoot = useMutation({
    mutationFn: async (mode: "visible" | "full") => {
      const capture = await tools.capture(mode);
      const asset = await saveScreenshot(workspaceId, capture, mode, captureName(capture.page, t(SHOT_NAME[mode])));
      return { asset, truncated: capture.truncated };
    },
    onMutate: () => say({ tone: "busy", text: t("browserToolsWorking") }),
    onSuccess: ({ asset, truncated }) =>
      savedAsset(
        asset.id,
        truncated
          ? `${t("browserToolsSavedAsset")} · ${t("browserToolsTruncated").replace("{px}", String(FULL_PAGE_LIMIT))}`
          : undefined,
      ),
    onError: failed,
  });

  const beginRegion = useMutation({
    mutationFn: () => tools.beginRegion(),
    onSuccess: (frame) => {
      say(null);
      setRegion({ src: frame.frame, width: frame.width, height: frame.height });
    },
    onError: failed,
  });

  const finishRegion = useMutation({
    mutationFn: async (selection: Selection | null) => {
      const capture = await tools.finishRegion(selection);
      if (!capture) return null;
      return saveScreenshot(workspaceId, capture, "region", captureName(capture.page, t(SHOT_NAME.region)));
    },
    onMutate: (selection) => {
      setRegion(null);
      if (selection) say({ tone: "busy", text: t("browserToolsWorking") });
    },
    onSuccess: (asset) => {
      if (asset) savedAsset(asset.id);
      else say(null);
    },
    onError: failed,
  });
  const finish = finishRegion.mutate;
  const onRegionDone = React.useCallback((selection: Selection | null) => finish(selection), [finish]);

  return {
    shoot,
    beginRegion,
    region,
    onRegionDone,
    busy: shoot.isPending || beginRegion.isPending || finishRegion.isPending,
  };
}
