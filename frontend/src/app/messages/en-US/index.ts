// 英文文案表:各分区按原先的先后拼起来(键序不变)。分区与 ../zh-CN/ 同名文件一一对应、键集相同。
import { agentMemory } from "./agentMemory";
import { aiStudio } from "./aiStudio";
import { assetLibrary } from "./assetLibrary";
import { bulkSelection } from "./bulkSelection";
import { canvasMarkers } from "./canvasMarkers";
import { community } from "./community";
import { desktop } from "./desktop";
import { mediaLibrary } from "./mediaLibrary";
import { nodeToolbar } from "./nodeToolbar";
import { otherUi } from "./otherUi";
import { plugins } from "./plugins";
import { publish } from "./publish";
import { scene3d } from "./scene3d";
import { shell } from "./shell";

export const enUS = {
  ...scene3d,
  ...shell,
  ...mediaLibrary,
  ...agentMemory,
  ...bulkSelection,
  ...publish,
  ...nodeToolbar,
  ...otherUi,
  ...aiStudio,
  ...plugins,
  ...canvasMarkers,
  ...desktop,
  ...community,
  ...assetLibrary,
} as const;
