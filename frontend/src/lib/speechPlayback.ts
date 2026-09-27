/**
 * 同一时刻只响一段。
 *
 * **必须是模块级的一份。** 播放的地方有两个 —— 消息页脚那个喇叭、免提对话里念回复 ——
 * 而"当前在响的是哪一段"是它们之间的共享事实。各管各的话:连点两条消息两段一起响;更糟的是
 * **打断掐不掉它自己念的那段**(掐的是另一个模块里的引用),于是你开口了它还在说,而这正是
 * 打断存在的全部意义。
 */

let current: { audio: HTMLAudioElement; stop: () => void } | null = null;

/** 停掉正在响的那一段。打断、切会话、关掉语音模式都走这里。 */
export function stopSpeaking(): void {
  current?.stop();
}

/** 现在有东西在响吗。 */
export function isSpeaking(): boolean {
  return current !== null;
}

/**
 * 播一段音频,**接管前一段**。Promise 在播完或被打断时落定。
 *
 * 被打断和播完在调用方看来是同一件事:都该回到"听"。区分它们只会让每个调用方各写一遍
 * 同样的收尾。
 */
export function playSpeech(blob: Blob): Promise<void> {
  stopSpeaking();
  const url = URL.createObjectURL(blob);
  const audio = new Audio(url);
  return new Promise<void>((resolve) => {
    const finish = () => {
      audio.pause();
      URL.revokeObjectURL(url);
      if (current?.audio === audio) current = null;
      resolve();
    };
    current = { audio, stop: finish };
    audio.onended = finish;
    audio.onerror = finish;
    void audio.play().catch(finish);
  });
}
