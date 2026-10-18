import type { Asset } from "@/api/domains/assets";
import { api } from "@/api/transport";

/**
 * 贴一条图片直链,直接收进素材库。
 *
 * 不走「从链接导入」那个后台任务:一张图不值得为它排一个任务,用户点完就该在素材库里看到。
 * 上游的闸(出站检查、40 MiB、文件头认格式)全在后端 `domain/assets/from_url.import_image_url`。
 */
export interface ImageUrlImportBody {
  workspace_id: string;
  project_id?: string | null;
  url: string;
  name?: string | null;
}

export function importImageUrl(body: ImageUrlImportBody): Promise<Asset> {
  return api<Asset>("/api/assets/import-image-url", {
    method: "POST",
    body: JSON.stringify(body),
  });
}
