import type React from "react";

import { LightRigField } from "@/features/nodeForms/LightRigField";
import { lightPatch, readLight } from "@/features/nodeForms/lightRig";

/**
 * **主控件**类的字段编辑器:一个大控件就是这个节点要做的那件事(打光的方向球,ADR 0108),不是参数里的一格。
 * 工作流检查器里它照常是表单的一行(NodeConfigForm);画板的能力面板把它摆在**面板主体**里,不收进「参数」弹层
 * (见 boards/composerFields 的 `stage`)。两处画的是同一个控件,由后端字段声明的 `editor` 点名。
 *
 * 加一种 = 在这张表里加一项。
 */
const STAGE_EDITORS: Record<
  string,
  (config: Record<string, unknown>, patch: (values: Record<string, unknown>) => void) => React.ReactNode
> = {
  light_rig: (config, patch) => <LightRigField light={readLight(config)} onChange={(change) => patch(lightPatch(change))} />,
};

export function isStageEditor(editor: string | undefined): boolean {
  return Boolean(editor && editor in STAGE_EDITORS);
}

/** 这个字段的主控件;不是主控件类的回 null。`patch` 一次写回好几格(这个控件编辑的那几格都 `edited_by` 它)。 */
export function renderStageEditor(
  editor: string | undefined,
  config: Record<string, unknown>,
  patch: (values: Record<string, unknown>) => void,
): React.ReactNode {
  const render = editor ? STAGE_EDITORS[editor] : undefined;
  return render ? render(config, patch) : null;
}
