/**
 * 上传工具的家在 components/generation/assetUpload.tsx —— 用它的地方横跨好几个功能(画板、工作流节点表单),
 * 放进 features/boards 会让 boards ↔ nodeForms 成环(棘轮:features/featureBoundaries.test.ts)。
 * 这里只把原来的 import 路径续上:features/boards/ 里的现有调用方一行不用改。
 */
export {
  acceptFor,
  AssetUploadStatus,
  fileKind,
  namedFile,
  useAssetUpload,
  wrongKindText,
} from "@/components/generation/assetUpload";
export type { AssetUpload, AssetUploadState, UploadKind } from "@/components/generation/assetUpload";
