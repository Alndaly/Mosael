/**
 * 同一时刻只响一段 —— **全应用只有这一个「当前在响」**。
 *
 * 播放的地方不止一处:消息页脚的喇叭、免提对话里念回复、资产页的语音、音色库的试听 ▷。
 * "当前在响的是哪一段"是它们之间的共享事实。此前朗读和试听各有一份「同一时刻只放一个」,
 * 彼此看不见:连点试听和喇叭两段一起响;更糟的是**免提打断掐不掉试听**,而打断存在的全部
 * 意义就是你一开口它就闭嘴。
 *
 * 播放方有两种形状,共用同一个登记处:
 * - 手里只有一段音频数据的(朗读)用 `playBlob`;
 * - 自己持有 `<audio>` 的(试听要能暂停、显示在放哪一个)用 `takePlayback` 登记停法。
 */

let current: (() => void) | null = null;

/** 停掉正在响的那一段,不管是谁放的。打断、切会话、关掉语音模式都走这里。 */
export function stopPlayback(): void {
  current?.();
}

/**
 * 由我来响:先停掉前一段,再登记我的停法。
 *
 * 交回的函数在我自己停下时调用,把位置让出来;那时位置已经被别人接管的话它什么都不做,
 * 所以晚到的收尾不会误删后来者的登记。
 */
export function takePlayback(stop: () => void): () => void {
  stopPlayback();
  current = stop;
  return () => {
    if (current === stop) current = null;
  };
}

/**
 * 播一段音频,**接管前一段**。Promise 在播完或被打断时落定。
 *
 * 被打断和播完在调用方看来是同一件事:都该回到"听"。区分它们只会让每个调用方各写一遍
 * 同样的收尾。
 */
export function playBlob(blob: Blob): Promise<void> {
  const url = URL.createObjectURL(blob);
  const audio = new Audio(url);
  return new Promise<void>((resolve) => {
    let release = () => {};
    const finish = () => {
      audio.pause();
      URL.revokeObjectURL(url);
      release();
      resolve();
    };
    release = takePlayback(finish);
    audio.onended = finish;
    audio.onerror = finish;
    void audio.play().catch(finish);
  });
}
