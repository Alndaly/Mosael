/**
 * **带版本号的服务端文档,在本地编辑。** 一个编辑器只说清三件事 —— 怎么读(`load`)、怎么带着底子存(`save`)、
 * 哪种错误是「底子旧了」(`isConflict`)—— 其余都在这里:
 *
 *  · **自动保存带 CAS 底子**(经 lib/useAutosave:防抖、同一时刻只一次、卸载 / 关页面时补上欠着的)。
 *    和服务端确认过的那份一样就不发。
 *  · **撞了 409:整份换成服务端那份**,撤销历史清空,告诉用户(`onConflict`)。冲突在这里就收拾完了,
 *    不算一次失败的保存(不报 `onSaveError`)。换上来的那份随即成了 useAutosave 眼里「更新的值」,
 *    被换掉的本地内容不会再被送出去。
 *  · **跟进服务端的新版本**:本地没有欠着的改动时,每隔 `followEveryMs` 读一次,版本号变了就换上。
 *  · **撤销 / 重做,一次手势 = 一步**(见 ./documentHistory)。
 *
 * 文档值按 `same`(缺省:JSON 相等)比较 —— 编辑器的值通常是每次改动新建的对象,按引用比不出「内容没变」。
 *
 * 现在接它的是 3D 场景。工作流的撤销挂在 zundo 的 graph store 上、画板要按格重放,各自另有一套(见架构体检第 3 条的进度)。
 */
import React from "react";

import { useAutosave } from "@/lib/useAutosave";

import { type DocumentHistory, record, redo as redoStep, reset, startHistory, undo as undoStep } from "./documentHistory";

/** 服务端的一版:内容和它的修订号。 */
export interface Versioned<T> {
  value: T;
  revision: number;
}

export interface VersionedDocumentOptions<T> {
  /** 打开时服务端给的那一版。换一份文档请换 React key 重新挂载,而不是换这个值。 */
  initial: Versioned<T>;
  load: () => Promise<Versioned<T>>;
  /** 带着底子 `baseRevision` 存;回存上之后的修订号。底子旧了要抛 `isConflict` 认得出的错。 */
  save: (value: T, baseRevision: number) => Promise<number>;
  isConflict: (error: unknown) => boolean;
  /** 撞了 409、已经换成服务端那份之后。 */
  onConflict?: () => void;
  /** 别的保存失败(断网、500……)。值留在队列里,下一次改动或离开页面时再试。 */
  onSaveError?: (error: unknown) => void;
  /** 存上了(或本来就和服务端一致)。 */
  onSaved?: () => void;
  /**
   * 本地这份变了:`value` 是还没存上的那份;`null` = 现在和服务端一致,没有欠着的。编辑器拿它存本地草稿。
   */
  onUnsaved?: (value: T | null) => void;
  /** 本地干净时多久读一次服务端;不给 = 不跟进。 */
  followEveryMs?: number;
  autosaveDelay?: number;
  same?: (a: T, b: T) => boolean;
}

export interface VersionedDocument<T> {
  value: T;
  /** 一次编辑。`gesture` 相同且挨得近的几次并成撤销栈里的一步。 */
  change: (next: T, options?: { gesture?: string }) => void;
  undo: () => void;
  redo: () => void;
  canUndo: boolean;
  canRedo: boolean;
  /** 此刻的内容(同步读,不等重渲染)。 */
  current: () => T;
  /** 下一次保存要带的底子。 */
  revision: () => number;
  /** 本地这份还没存上。 */
  unsaved: () => boolean;
  /** 有一次保存还在路上或在排队。 */
  pending: boolean;
  /** 不等防抖,现在就把欠着的存掉(上一次失败的那份也重试);回「存上了没有」。 */
  flush: () => Promise<boolean>;
  /** 换成服务端的这一版(版本历史里恢复了一版等):撤销历史清空。 */
  adopt: (server: Versioned<T>) => void;
}

const jsonSame = <T,>(a: T, b: T) => JSON.stringify(a) === JSON.stringify(b);

export function useVersionedDocument<T>(options: VersionedDocumentOptions<T>): VersionedDocument<T> {
  const [history, setHistory] = React.useState<DocumentHistory<T>>(() => startHistory(options.initial.value));
  //: 同步读:撤销、保存、轮询都在事件里读「此刻」,不能等下一次渲染。
  const historyRef = React.useRef(history);
  //: 服务端确认过的那一份和它的修订号 —— **一个单位**:只换其一,一份旧内容就会拿着新底子通过 CAS。
  const confirmed = React.useRef<Versioned<T>>(options.initial);
  const mounted = React.useRef(true);
  const optionsRef = React.useRef(options);
  optionsRef.current = options;
  //: 稳定的引用:它进了下面几个回调和跟进轮询的依赖,每次渲染换一个会让轮询不停重开。
  const same = React.useCallback((a: T, b: T) => (optionsRef.current.same ?? jsonSame)(a, b), []);

  const commit = React.useCallback(
    (next: DocumentHistory<T>) => {
      historyRef.current = next;
      setHistory(next);
      const dirty = !same(next.present, confirmed.current.value);
      optionsRef.current.onUnsaved?.(dirty ? next.present : null);
    },
    [same],
  );

  const adopt = React.useCallback(
    (server: Versioned<T>) => {
      confirmed.current = server;
      commit(reset(server.value));
    },
    [commit],
  );

  const autosave = useAutosave(history.present, async (next) => {
    const { save, load, isConflict, onConflict, onSaveError, onSaved } = optionsRef.current;
    if (same(next, confirmed.current.value)) {
      onSaved?.();
      return;
    }
    try {
      const revision = await save(next, confirmed.current.revision);
      confirmed.current = { value: next, revision };
      if (same(historyRef.current.present, next)) optionsRef.current.onUnsaved?.(null);
      onSaved?.();
    } catch (error) {
      if (!isConflict(error)) {
        onSaveError?.(error);
        throw error;
      }
      const latest = await load().catch(() => null);
      if (latest === null) {
        onSaveError?.(error);
        throw error;
      }
      if (mounted.current) {
        adopt(latest);
        onConflict?.();
      } else {
        confirmed.current = latest;
      }
      //: 冲突已收拾完(换成了服务端那份):这次保存不算失败。
    }
  }, { delay: options.autosaveDelay });

  //: 跟进服务端:本地干净时才读、读回来仍然干净才换(读的途中用户可能动了一下)。
  const followEveryMs = options.followEveryMs;
  React.useEffect(() => {
    if (!followEveryMs) return;
    let active = true;
    const timer = setInterval(async () => {
      const clean = () => same(historyRef.current.present, confirmed.current.value);
      if (!clean()) return;
      try {
        const latest = await optionsRef.current.load();
        if (!active || !clean() || latest.revision === confirmed.current.revision) return;
        adopt(latest);
      } catch {
        /* 离线时留着本地这份,下一轮再读。 */
      }
    }, followEveryMs);
    return () => {
      active = false;
      clearInterval(timer);
    };
  }, [adopt, followEveryMs, same]);

  React.useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);

  return {
    value: history.present,
    change: React.useCallback(
      (next: T, { gesture }: { gesture?: string } = {}) => commit(record(historyRef.current, next, { gesture })),
      [commit],
    ),
    undo: React.useCallback(() => commit(undoStep(historyRef.current)), [commit]),
    redo: React.useCallback(() => commit(redoStep(historyRef.current)), [commit]),
    canUndo: history.past.length > 0,
    canRedo: history.future.length > 0,
    current: React.useCallback(() => historyRef.current.present, []),
    revision: React.useCallback(() => confirmed.current.revision, []),
    unsaved: React.useCallback(() => !same(historyRef.current.present, confirmed.current.value), [same]),
    pending: autosave.pending,
    flush: autosave.flush,
    adopt,
  };
}
