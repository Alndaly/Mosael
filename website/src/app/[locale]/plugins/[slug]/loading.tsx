/**
 * 插件详情页的骨架。
 *
 * 和文档页同一个道理(见 docs/loading):换页时外壳先出来、正文还在取,屏幕上只剩站头
 * 站脚,中间空一段。这不是"慢",是"看起来像坏了"。
 *
 * 这一页渲染的是插件自己的 README —— 和文档正文一样是 markdown,一样有这段空窗。
 *
 * 骨架的版面和真实的对齐(正文 / 18rem 右栏),内容进来时不会整页跳一下。
 */
export default function PluginDetailLoading() {
  return (
    <div className="-mt-20 bg-paper pt-20">
      <div className="mx-auto max-w-[72rem] animate-pulse px-5 py-16 sm:px-8">
        <div className="h-4 w-28 bg-muted" />

        <div className="mt-8 border-b-2 border-ink pb-8">
          <div className="h-10 w-2/5 bg-muted" />
          <div className="mt-3 h-3 w-56 bg-muted" />
          <div className="mt-4 h-5 w-3/4 bg-muted" />
        </div>

        <div className="mt-10 grid gap-10 lg:grid-cols-[minmax(0,1fr)_18rem]">
          <div className="flex min-w-0 flex-col gap-3">
            <div className="mb-2 h-7 w-24 bg-muted" />
            {[100, 92, 96, 60, 100, 88, 94, 45].map((width, index) => (
              <div key={index} className="h-4 bg-muted" style={{ width: `${width}%` }} />
            ))}
          </div>

          <div className="flex flex-col gap-8">
            {[3, 4, 2].map((rows, section) => (
              <div key={section} className="flex flex-col gap-3">
                <div className="h-6 w-32 bg-muted" />
                {Array.from({ length: rows }, (_, index) => (
                  <div key={index} className="h-4 bg-muted" style={{ width: `${90 - index * 12}%` }} />
                ))}
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}
