import { useI18n } from "@/app/preferences";
import { CanvasInputModeMenu } from "@/components/app/CanvasInputModeMenu";
import { useCanvasInputMode } from "@/components/app/canvasInputMode";

/**
 * 画板、工作流、3D 场景工具条上的「画布操控方式」:全局那一份(canvasInputMode),三处共用。样子和交互在 CanvasInputModeMenu,
 * 这里只接存储。`scene`:3D 场景里鼠标是拖动旋转视角,菜单里那一句换成它。
 */
export function CanvasInputModeSwitch({ scene = false }: { scene?: boolean }) {
  const [mode, setMode] = useCanvasInputMode();
  const t = useI18n();
  return (
    <CanvasInputModeMenu
      mode={mode}
      onChange={setMode}
      scope={t("canvasInputGlobalScope")}
      descriptions={scene ? { mouse: t("canvasInputMouseSceneDesc") } : undefined}
      className="self-center"
    />
  );
}
