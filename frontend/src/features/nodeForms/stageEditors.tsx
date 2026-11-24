import type React from "react";

import { CropFrameField } from "@/features/nodeForms/CropFrameField";
import { cropPatch, readCrop } from "@/features/nodeForms/cropFrame";
import { LightRigField } from "@/features/nodeForms/LightRigField";
import { lightPatch, readLight } from "@/features/nodeForms/lightRig";
import { MaskPaintField } from "@/features/nodeForms/MaskPaintField";

/**
 * 主控件画在哪儿:哪个工作区、这个节点此刻改的是哪张图。画板上是能力挂着的那一格的图;工作流检查器里是
 * `asset_id` 那一格填的素材(接的是上游时没有 —— 控件照样能用,只是没有底图)。
 */
export interface StageContext {
  workspaceId: string;
  imageAssetId?: string;
  imageName?: string;
}

/**
 * **主控件**类的字段编辑器:一个大控件就是这个节点要做的那件事(打光的方向球 ADR 0108、裁切框和重绘的蒙版 ADR 0110),
 * 不是参数里的一格。工作流检查器里它照常是表单的一行(NodeConfigForm);画板的能力面板把它摆在**面板主体**里,不收进
 * 「参数」弹层(见 boards/composerFields 的 `stage`)。两处画的是同一个控件,由后端字段声明的 `editor` 点名。
 *
 * 主控件的字段由控件自己填:画板上不给它接上游的芯片、也不默认接上游(composerFields、boardTools.defaultBindings)——
 * 重绘的蒙版尤其如此,连进来的图默认是参考,是不是蒙版只由人说(ADR 0107)。
 *
 * 加一种 = 在这张表里加一项。
 */
const STAGE_EDITORS: Record<
  string,
  (config: Record<string, unknown>, patch: (values: Record<string, unknown>) => void, context: StageContext) => React.ReactNode
> = {
  light_rig: (config, patch) => <LightRigField light={readLight(config)} onChange={(change) => patch(lightPatch(change))} />,
  crop_frame: (config, patch, context) => (
    <CropFrameField imageAssetId={context.imageAssetId} box={readCrop(config)} onChange={(box) => patch(cropPatch(box))} />
  ),
  mask_paint: (config, patch, context) => (
    <MaskPaintField
      workspaceId={context.workspaceId}
      imageAssetId={context.imageAssetId}
      imageName={context.imageName ?? ""}
      maskAssetId={typeof config.mask_asset_id === "string" && config.mask_asset_id ? config.mask_asset_id : undefined}
      onChange={(mask) => patch({ mask_asset_id: mask })}
    />
  ),
};

export function isStageEditor(editor: string | undefined): boolean {
  return Boolean(editor && editor in STAGE_EDITORS);
}

/** 这个字段的主控件;不是主控件类的回 null。`patch` 一次写回好几格(这个控件编辑的那几格都 `edited_by` 它)。 */
export function renderStageEditor(
  editor: string | undefined,
  config: Record<string, unknown>,
  patch: (values: Record<string, unknown>) => void,
  context: StageContext,
): React.ReactNode {
  const render = editor ? STAGE_EDITORS[editor] : undefined;
  return render ? render(config, patch, context) : null;
}
