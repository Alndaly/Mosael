/**
 * 文档页的骨架。
 *
 * 没有它的话,换页时 `[locale]/layout.tsx` 的外壳先出来、正文那一段还在取 —— 屏幕上只剩
 * 站头和站脚,中间空几秒。这不是"慢",是"看起来像坏了"。
 *
 * 骨架的列宽和真实版面对齐(13rem / 正文 / 13rem),内容进来时不会整页跳一下。
 */
export default function DocsLoading() {
  return (
    <div className="mx-auto grid max-w-[88rem] animate-pulse gap-x-14 gap-y-12 px-5 pt-12 pb-20 sm:px-8 lg:grid-cols-[13rem_minmax(0,1fr)] xl:grid-cols-[13rem_minmax(0,1fr)_13rem]">
      <div className="hidden flex-col gap-3 lg:flex">
        {[80, 60, 70, 55, 65, 50].map((width, index) => (
          <div key={index} className="h-4 bg-muted" style={{ width: `${width}%` }} />
        ))}
      </div>

      <div className="min-w-0 lg:col-start-2 lg:row-start-1">
        <div className="mb-12 border-b-2 border-ink pb-8">
          <div className="mb-4 h-3 w-20 bg-muted" />
          <div className="mb-4 h-10 w-3/4 bg-muted" />
          <div className="h-5 w-1/2 bg-muted" />
        </div>
        <div className="flex flex-col gap-3">
          {[100, 92, 96, 60, 100, 88, 94, 45].map((width, index) => (
            <div key={index} className="h-4 bg-muted" style={{ width: `${width}%` }} />
          ))}
        </div>
      </div>

      <div className="hidden flex-col gap-3 xl:flex xl:col-start-3 xl:row-start-1">
        {[70, 90, 60, 80].map((width, index) => (
          <div key={index} className="h-4 bg-muted" style={{ width: `${width}%` }} />
        ))}
      </div>
    </div>
  );
}
