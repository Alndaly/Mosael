/**
 * 社区详情页的骨架。
 *
 * 换页时外壳先出来、正文还在取,屏幕上只剩站头站脚、中间空一段 —— 那不是"慢",是"看起来像坏了"。
 * 版面和真实的对齐(身份栏 / 正文 + 20rem 右栏),内容进来时不会整页跳一下。
 */
export function DetailSkeleton() {
  return (
    <div className="-mt-20 animate-pulse bg-paper motion-reduce:animate-none">
      <div className="border-b border-border">
        <div className="mx-auto max-w-[76rem] px-5 pt-30 pb-10 sm:px-8 sm:pt-34">
          <div className="h-4 w-40 rounded bg-muted" />
          <div className="mt-8 flex items-start gap-5">
            <div className="size-16 shrink-0 rounded-2xl bg-muted" />
            <div className="grid flex-1 gap-3">
              <div className="h-9 w-2/5 rounded bg-muted" />
              <div className="h-3 w-48 rounded bg-muted" />
              <div className="h-4 w-3/4 rounded bg-muted" />
            </div>
          </div>
        </div>
      </div>
      <div className="mx-auto grid max-w-[76rem] gap-10 px-5 py-12 sm:px-8 lg:grid-cols-[minmax(0,1fr)_20rem] lg:gap-14">
        <div className="grid content-start gap-3">
          <div className="mb-3 h-6 w-24 rounded bg-muted" />
          {[100, 92, 96, 60, 100, 88, 94, 45].map((width, index) => (
            <div key={index} className="h-4 rounded bg-muted" style={{ width: `${width}%` }} />
          ))}
        </div>
        <div className="grid content-start gap-4">
          <div className="h-44 rounded-2xl bg-muted" />
          <div className="h-36 rounded-2xl bg-muted" />
        </div>
      </div>
    </div>
  );
}
