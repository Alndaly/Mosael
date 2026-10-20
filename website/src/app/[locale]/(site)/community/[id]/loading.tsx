import { DetailSkeleton } from "@/components/community/detail-skeleton";

/** 从列表点进详情时先出骨架:版面和真实内容对齐,内容进来时不跳。 */
export default function Loading() {
  return <DetailSkeleton />;
}
