import React from "react";

/**
 * 多选:选择模式 + 已选集合。**全项目只有这一份。**
 *
 * 素材页先有了一套(选择模式 / 已选 N 项 / 全选切换 / 批量动作 / 取消),发布记录、工作流、画板
 * 照它做;设置页的几张列表(模型、供应商、成本规则、记忆)另写过一份带 shift 连选的,两份已经
 * 分叉。抄第二遍必然分叉,而分叉的地方恰好都不显眼:
 *
 *   - 退出选择模式**要清空已选** —— 漏了的话下次进来上一批还勾着,而批量删除照那批执行;
 *   - 「全选」作用于**当前可见**的那些(筛选/搜索之后),不是全库;
 *   - 选中的东西被删掉/被筛掉之后要自动不算数,否则批量动作会带着一批幽灵 id 发出去;
 *   - **shift 连选**:批量操作的对象几乎总是连续的一段(同一个供应商的一串规则、目录预填出来的
 *     一批),没有连选,"批量"只是把 N 次删除换成 N 次勾选。
 *
 * 所以状态机收在这里,页面只负责自己的那几个批量按钮 —— 那部分本来就各不相同。
 *
 * `items` 是选中集所在的那张列表,也是 shift 连选的顺序;不在里面的 id 会被摘掉。
 * 选中集只认 id,不持有行对象 —— 列表刷新后行是新对象,持有它们会让选中状态每次 refetch 都失效。
 */
export function useMultiSelect<T>(items: readonly T[], idOf: (item: T) => string) {
  const [selectMode, setSelectMode] = React.useState(false);
  const [selectedIds, setSelectedIds] = React.useState<ReadonlySet<string>>(() => new Set());
  const lastIndex = React.useRef<number | null>(null);

  // idOf 几乎总是就地写的箭头函数,放进依赖会让 ids 每次渲染都重算,进而让下面每个
  // useCallback 都换身份。用 ref 接住它,只跟着 items 变。
  const idOfRef = React.useRef(idOf);
  idOfRef.current = idOf;
  const ids = React.useMemo(() => items.map((item) => idOfRef.current(item)), [items]);
  const idsKey = ids.join("\u0000");

  // 列表变了(别人删了一条、筛选换了)就把已经不在的剔掉 —— 留着会让批量动作带上幽灵 id,
  // 计数也会一直显示"已选 3 项"而列表里只剩 1 行。
  React.useEffect(() => {
    setSelectedIds((current) => {
      if (current.size === 0) return current;
      const present = new Set(idsKey ? idsKey.split("\u0000") : []);
      const next = new Set([...current].filter((id) => present.has(id)));
      return next.size === current.size ? current : next;
    });
  }, [idsKey]);

  /** 勾/取消一项。带 shift 时从上一次点的那项到这项,整段设成**这一次的目标状态**(而不是各自
   *  取反 —— 取反会把段中已选的又反选掉,和所有文件管理器的行为都不一样)。 */
  const toggle = React.useCallback(
    (id: string, event?: { shiftKey?: boolean }) => {
      const index = ids.indexOf(id);
      // 锚点**先取出来**:更新函数可能延到渲染时才跑,那时下面那行已经把锚点改成了这一项,
      // 连选就退化成只勾这一项。
      const anchor = lastIndex.current;
      setSelectedIds((current) => {
        const next = new Set(current);
        if (event?.shiftKey && anchor !== null && index >= 0) {
          const [from, to] = [anchor, index].sort((a, b) => a - b);
          const turnOn = !current.has(id);
          for (let i = from; i <= to; i += 1) {
            if (turnOn) next.add(ids[i]);
            else next.delete(ids[i]);
          }
        } else if (next.has(id)) {
          next.delete(id);
        } else {
          next.add(id);
        }
        return next;
      });
      if (index >= 0) lastIndex.current = index;
    },
    [ids],
  );

  /** 当前可见的这些是否已全选(默认整张列表)。**空列表不算全选** —— 否则按钮会写着「取消全选」。 */
  const allSelected = React.useCallback(
    (visible: readonly T[] = items) =>
      visible.length > 0 && visible.every((item) => selectedIds.has(idOfRef.current(item))),
    [items, selectedIds],
  );

  /** 全选/取消全选当前可见的那些(默认整张列表)。 */
  const selectAll = React.useCallback(
    (visible: readonly T[] = items) => {
      const visibleIds = visible.map((item) => idOfRef.current(item));
      setSelectedIds((current) => {
        const every = visibleIds.length > 0 && visibleIds.every((id) => current.has(id));
        return every ? new Set() : new Set(visibleIds);
      });
      lastIndex.current = null;
    },
    [items],
  );

  const clear = React.useCallback(() => {
    setSelectedIds(new Set());
    lastIndex.current = null;
  }, []);

  const enter = React.useCallback(() => setSelectMode(true), []);

  /** 退出选择模式:**顺带清空**。 */
  const exit = React.useCallback(() => {
    setSelectMode(false);
    setSelectedIds(new Set());
    lastIndex.current = null;
  }, []);

  const isSelected = React.useCallback((id: string) => selectedIds.has(id), [selectedIds]);

  /**
   * 右键菜单作用在谁身上 —— 和时间线同一条规则(editor/timeline/Timeline 的 menuTargets):
   * 右键的那一项在选区里,就是整个选区;不在,就只是它自己。此前多选着右键一项,菜单给的是
   * 单条的重命名 / 删除,作用在被点的那一项上 —— 看着像批量删,实际只删了一条。
   */
  const menuTargets = React.useCallback(
    (id: string): string[] => (selectMode && selectedIds.has(id) ? [...selectedIds] : [id]),
    [selectMode, selectedIds],
  );

  return { selectMode, enter, exit, selectedIds, count: selectedIds.size, isSelected, toggle, selectAll, allSelected, clear, menuTargets };
}
