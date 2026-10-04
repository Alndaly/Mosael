import React from "react";
import { useMutation } from "@tanstack/react-query";

import { useI18n } from "@/app/preferences";

import type { PageImageItem } from "./ImagePanel";
import { savePageImage } from "./imageActions";
import type { PageInfo, PageToolsBridge } from "./pageActions";
import type { ToolNotice } from "./useToolNotice";

/**
 * 采集页面图片:列出够大的图、用这个档案的会话取回字节当缩略图(防盗链的站点直接拿地址只回一张「禁止外链」)、
 * 勾选、一张张带着出处入库。字节只取一次:缩略图和入库用的是同一份。
 */
export function useImageTools(tools: PageToolsBridge, workspaceId: string, notice: ToolNotice) {
  const t = useI18n();
  const { say, failed, savedAsset } = notice;
  const [images, setImages] = React.useState<PageImageItem[]>([]);
  const [selected, setSelected] = React.useState<Set<string>>(new Set());
  const bytes = React.useRef(new Map<string, { bytes: Uint8Array; mime: string }>());
  const page = React.useRef<PageInfo>({ url: "", title: "" });

  const release = React.useCallback(() => {
    setImages((list) => {
      for (const item of list) if (item.preview) URL.revokeObjectURL(item.preview);
      return [];
    });
    bytes.current.clear();
  }, []);
  React.useEffect(() => release, [release]);

  const find = useMutation({
    mutationFn: async () => {
      const listed = await tools.listImages();
      page.current = listed.page;
      setImages(listed.images.map((image) => ({ ...image, state: "loading" })));
      if (listed.images.length === 0) return;
      const fetched = await tools.fetchImages(listed.images.map((image) => image.url));
      setImages((list) =>
        list.map((item) => {
          const result = fetched.find((one) => one.url === item.url);
          if (!result?.ok) return { ...item, state: "failed" };
          bytes.current.set(item.url, { bytes: result.bytes, mime: result.mime });
          const blob = new Blob([result.bytes as Uint8Array<ArrayBuffer>], { type: result.mime });
          return { ...item, state: "ready", preview: URL.createObjectURL(blob) };
        }),
      );
    },
    onMutate: () => {
      release();
      setSelected(new Set());
    },
    onError: failed,
  });

  const save = useMutation({
    mutationFn: async () => {
      const capturedAt = new Date().toISOString();
      const ids: string[] = [];
      for (const item of images.filter((one) => selected.has(one.url))) {
        const data = bytes.current.get(item.url);
        if (!data) continue;
        const asset = await savePageImage(workspaceId, { url: item.url, alt: item.alt, ...data }, page.current, capturedAt);
        ids.push(asset.id);
      }
      return ids;
    },
    onMutate: () => say({ tone: "busy", text: t("browserToolsWorking") }),
    onSuccess: (ids) => {
      setSelected(new Set());
      savedAsset(
        ids.length === 1 ? ids[0] : null,
        ids.length === 1 ? undefined : t("browserToolsSavedAssets").replace("{n}", String(ids.length)),
      );
    },
    onError: failed,
  });

  const toggle = (url: string) =>
    setSelected((current) => {
      const next = new Set(current);
      if (next.has(url)) next.delete(url);
      else next.add(url);
      return next;
    });
  const ready = images.filter((item) => item.state === "ready");
  const toggleAll = () => setSelected((current) => (current.size ? new Set() : new Set(ready.map((item) => item.url))));

  return { images, selected, find, save, toggle, toggleAll, anyReady: ready.length > 0 };
}
