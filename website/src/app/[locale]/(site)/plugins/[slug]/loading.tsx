import { DetailSkeleton } from "@/components/community/detail-skeleton";

/** 插件详情渲染的是插件自己的 README,和文档正文一样有一段取内容的空窗。 */
export default function PluginDetailLoading() {
  return <DetailSkeleton />;
}
