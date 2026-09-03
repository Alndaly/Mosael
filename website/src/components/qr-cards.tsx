import Image from "next/image";

import { mediaVersion } from "@/lib/media";
import { cn } from "@/lib/utils";

/**
 * 两张微信二维码,并排。
 *
 * 首页和「联系我们」两处都要用,所以做成组件而不是各摆一遍 —— 二维码换了(群码会过期)
 * 只需要换图,不用去两个地方改版面。
 *
 * 两张源图的比例和底色都不一样(一张 2:3 深底,一张 4:5 白底),固定同一个画框 +
 * `object-contain`:卡片等高、说明文字对得齐,而二维码一个像素都没被裁 —— 裁了就扫不出来。
 *
 * 文案由调用方给:MDX 那侧是按语言分开的文件,组件里没法也不该再查一次 i18n。
 */
export function QrCards({
  group,
  groupHint,
  author,
  authorHint,
  className,
}: {
  group: string;
  groupHint: string;
  author: string;
  authorHint: string;
  className?: string;
}) {
  const cards = [
    { src: "/media/qr-group.png", title: group, hint: groupHint },
    { src: "/media/qr-wechat.png", title: author, hint: authorHint },
  ];

  return (
    <div className={cn("my-8 grid gap-8 not-prose sm:grid-cols-2", className)}>
      {cards.map((card) => (
        <figure key={card.src} className="m-0 flex min-w-0 flex-col">
          <div className="relative aspect-4/5 w-full overflow-hidden rounded-[1.5rem] border border-black/8 bg-white">
            <Image
              src={`${card.src}?v=${mediaVersion(card.src)}`}
              alt={card.title}
              fill
              sizes="(min-width: 40rem) 20rem, 90vw"
              className="object-contain"
            />
          </div>
          <figcaption className="pt-5">
            <p className="m-0 font-display text-lg font-semibold tracking-[-0.02em]">{card.title}</p>
            <p className="m-0 mt-1 text-sm leading-6 text-current/55">{card.hint}</p>
          </figcaption>
        </figure>
      ))}
    </div>
  );
}
