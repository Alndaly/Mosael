import React from "react";
import { keepPreviousData, useInfiniteQuery, useQueries, useQuery } from "@tanstack/react-query";

import {
  getAsset,
  getAssetFacets,
  listAssetPage,
  listSequenceAssets,
  type Asset,
  type AssetCard,
  type AssetQuery,
  type Sequence,
} from "@/api/client";
import { assetKeys } from "@/api/queryKeys";
import { useDebouncedValue } from "@/lib/useDebouncedValue";

/**
 * 素材库一页页地取(筛选、排序在服务端,见后端 domain/assets/listing)。
 *
 * 换了条件(搜索词、种类、标签、排序)就是另一份列表;新的那份回来之前,先留着旧的那份
 * (`keepPreviousData`)—— 每敲一个字都闪一下骨架,比看着上一份多停 100 毫秒难受得多。
 */
export function useAssetPages(query: AssetQuery, { enabled = true }: { enabled?: boolean } = {}) {
  const pages = useInfiniteQuery({
    queryKey: assetKeys.pages(query),
    queryFn: ({ pageParam }) => listAssetPage(query, pageParam),
    initialPageParam: null as string | null,
    getNextPageParam: (last) => last.next_cursor,
    placeholderData: keepPreviousData,
    enabled,
  });
  const items = React.useMemo<AssetCard[]>(() => pages.data?.pages.flatMap((page) => page.items) ?? [], [pages.data]);
  const { hasNextPage, fetchNextPage } = pages;
  /**
   * 把剩下的几页都取回来,交回整份清单。「全选」要的是**满足条件的全部**,不只是已经翻到的那几页。
   * 一页一页接着取(游标只能这样走);取到一半失败就停在那儿,交回已经有的。
   */
  const loadAll = React.useCallback(async (): Promise<AssetCard[]> => {
    let result = hasNextPage ? await fetchNextPage() : null;
    while (result?.hasNextPage && !result.isError) result = await result.fetchNextPage();
    return (result?.data ?? pages.data)?.pages.flatMap((page) => page.items) ?? [];
  }, [hasNextPage, fetchNextPage, pages.data]);
  return { ...pages, items, total: pages.data?.pages[0]?.total, loadAll };
}

/** 挑素材的下拉 / 弹窗一页摆几条:往下滚再接着取,或者再搜细一点。 */
const PICKER_PAGE = 50;

/**
 * 挑素材用:敲的字停手之后交给服务端搜(名字、文件名、标签),一页页接着取。下拉和挑选弹窗共用 ——
 * 素材库分了页之后,「把全部素材拿回来在浏览器里筛」这条路就没有了。
 */
export function useAssetSearch(query: Omit<AssetQuery, "q">, { enabled = true }: { enabled?: boolean } = {}) {
  const [text, setText] = React.useState("");
  const settled = useDebouncedValue(text.trim());
  const pages = useAssetPages({ limit: PICKER_PAGE, ...query, q: settled || undefined }, { enabled });
  return { ...pages, text, search: setText, query: settled };
}

/**
 * 满足条件的**全部**卡片:一页页接着取,取到头为止(一页按最大的 200 份取)。
 *
 * 只给「一个通用的下拉 / 多选、在浏览器里按字筛」的地方用 —— 工作流节点的素材字段、生成节点挂素材的那几格。
 * 那几个控件吃的是一份完整的选项清单,而节点可能要库里任何一份素材。只在那个节点的表单开着时取,
 * 取回来的是卡片字段(一份几百字节),而且只是素材库里的(中间产物不在里面)。
 */
export function useAllAssetCards(query: AssetQuery, { enabled = true }: { enabled?: boolean } = {}) {
  const pages = useAssetPages({ limit: 200, ...query }, { enabled });
  const { hasNextPage, isFetchingNextPage, isError, fetchNextPage } = pages;
  React.useEffect(() => {
    if (enabled && hasNextPage && !isFetchingNextPage && !isError) void fetchNextPage();
  }, [enabled, hasNextPage, isFetchingNextPage, isError, fetchNextPage]);
  return { ...pages, complete: pages.isSuccess && !hasNextPage };
}

/** 页签上的数字和标签筛选的候选(整个范围,不看搜索)。`intermediate` 给了就数那一种中间产物。 */
export function useAssetFacets(
  workspaceId: string,
  { projectId, intermediate = "", enabled = true }: { projectId?: string | null; intermediate?: string; enabled?: boolean } = {},
) {
  return useQuery({
    queryKey: assetKeys.facets(workspaceId, projectId, intermediate),
    queryFn: () => getAssetFacets(workspaceId, projectId, intermediate),
    enabled,
    //: 换一种看的时候先留着上一份:页签上的数字从 243 跳到 985,不先闪成空的。
    placeholderData: keepPreviousData,
  });
}

/** 时间线上用到的那几份素材的指纹:一组 id 排好序拼起来再折成一个短串。 */
export function assetIdsFingerprint(ids: readonly string[]): string {
  const sorted = [...new Set(ids)].sort();
  // FNV-1a:几千个 id 拼起来也只是一个八位十六进制数,放进查询键里不占地方。
  let hash = 0x811c9dc5;
  for (const id of sorted) {
    for (let i = 0; i < id.length; i += 1) {
      hash ^= id.charCodeAt(i);
      hash = Math.imul(hash, 0x01000193) >>> 0;
    }
    hash ^= 0x2c;
    hash = Math.imul(hash, 0x01000193) >>> 0;
  }
  return `${sorted.length}:${hash.toString(16)}`;
}

/**
 * 剪辑台的时间线、监视器、检查器读的素材:**这条时间线用到的那些**,完整字段。
 *
 * 不从素材库的列表里找:列表分了页、只带卡片字段,而且只列素材库里的(配音片段这类中间产物不在里面)。
 * 时间线上放进一段新素材时指纹变了,重取一次;只是挪动片段不重取。重取的那一下先用着上一份。
 */
export function useSequenceAssets(workspaceId: string, sequence: Sequence | null | undefined) {
  const ids = React.useMemo(
    () =>
      (sequence?.tracks ?? []).flatMap((track) =>
        (track.clips ?? []).flatMap((clip) => (clip.asset_id ? [clip.asset_id] : [])),
      ),
    [sequence],
  );
  const fingerprint = React.useMemo(() => assetIdsFingerprint(ids), [ids]);
  return useQuery({
    queryKey: assetKeys.sequence(workspaceId, sequence?.id ?? "", fingerprint),
    queryFn: () => listSequenceAssets(sequence!.id),
    enabled: Boolean(sequence?.id),
    placeholderData: keepPreviousData,
  });
}

/** 按 id 取来的几份素材:`byId` 里是已经到了的;`settled` 是每一份都有了结果(到了,或者取不到 —— 被删了)。 */
export interface AssetDetails {
  byId: Map<string, Asset>;
  settled: boolean;
}

/** 几条详情查询的结果并成一份。放在模块顶层:引用不变,React Query 才不会每次渲染都重并一遍。 */
function collectDetails(results: { data?: Asset; isPending: boolean }[]): AssetDetails {
  return {
    byId: new Map(results.flatMap((result) => (result.data ? [[result.data.id, result.data] as const] : []))),
    settled: results.every((result) => !result.isPending),
  };
}

/** 按 id 取几份素材的完整字段(各自走详情缓存,和详情弹窗共用一份)。手上只有 id 的地方用它,不必把素材库拉回来再找。 */
export function useAssetDetails(ids: readonly string[]): AssetDetails {
  const unique = React.useMemo(() => [...new Set(ids.filter(Boolean))], [ids]);
  return useQueries({
    queries: unique.map((id) => ({ queryKey: assetKeys.detail(id), queryFn: () => getAsset(id), retry: false })),
    combine: collectDetails,
  });
}

/**
 * `@` 引用素材的候选:按这几种、敲的字在服务端搜,只要前几条(提示词编辑器每次 query 变了问一次,见 PromptEditor)。
 * 不把素材库整个拉回来、在浏览器里筛 —— 素材库分了页,也不该为一个菜单这么做。
 */
export function useMentionCandidates(workspaceId: string, kinds: readonly string[], limit = 8) {
  const key = kinds.join(",");
  return React.useCallback(
    (query: string) => listAssetPage({ workspace_id: workspaceId, kind: key ? key.split(",") : [], q: query, limit }).then((page) => page.items),
    [workspaceId, key, limit],
  );
}
