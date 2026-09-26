import { derivesOutputs, withSlotProducer, type BoardAbilitySetting, type BoardItem, type BoardProducer } from "@/api/client";

export type BoardItemRunStatus = NonNullable<BoardItem["run"]>["status"];

export function itemJobId(item: BoardItem): string | undefined {
  return item.run?.job_id;
}

export function itemError(item: BoardItem): string | undefined {
  return item.run?.error;
}

/**
 * 选中这一格时底下挂哪个产出者的面板;不挂回 null。**一处说了算。**
 *
 * 产出者写在这一格的表单上(`form.producer`,见后端 boards/producers.py)—— 不再按种类猜。此前
 * 这里按种类推断(便签写字、音频念、图片视频生成,表单记着 trim 的截取),升级时由迁移
 * migrate-board-forms-name-their-producer 照那条推断写进了每一格。
 *
 * 已经有了产出(asset_id)的一格不挂 —— 它的事做完了;便签的产出是它自己的正文,不占 asset_id,
 * 所以有字照样挂(有字就是照我说的改)。产出新建在右边的(3D 场景格渲白模)也照样挂:场景格的
 * asset_id 是缩略图,不是它的产出(api/domains/boards 的 derivesOutputs)。
 *
 * 这是这一格**自己的**产出者;它的能力(转写、翻译……)从操作条上点开,不在这里(见 boardAbilities)。
 */
export function producerOf(item: BoardItem): BoardProducer | null {
  const producer = item.form?.producer;
  if (!producer || (item.asset_id && !derivesOutputs(producer))) return null;
  return producer;
}

/**
 * 面板看到的那一格:表单里不带产出者,也不带能力的设置。这两样都不归这块面板编辑 —— 面板只管自己那几个
 * 字段,存回来的表单由画布补上(见 withProducer)。面板拿「上一次存下的表单」比对要不要回写,带着它们的话
 * 每次一挂上就会白写一遍;而面板自己拼一份新表单时,能力的设置不在它手里,会被悄悄丢掉。
 */
export function composerView(item: BoardItem): BoardItem {
  if (!item.form || (!("producer" in item.form) && !("abilities" in item.form))) return item;
  const { producer: _producer, abilities: _abilities, ...form } = item.form;
  return { ...item, form };
}

/**
 * 面板存回来的表单,补上这一格的能力设置(`stored` 是这一格此刻的表单)和产出者。**产出者排在最后、能力的设置
 * 在它前面** —— 和后端摆占位时写的位置一致,前端按 JSON 比对表单。
 */
export function withProducer(
  form: NonNullable<BoardItem["form"]>,
  producer: BoardProducer,
  stored?: BoardItem["form"],
): NonNullable<BoardItem["form"]> {
  const { producer: _producer, abilities: _abilities, ...rest } = form;
  const abilities = stored?.abilities;
  return { ...rest, ...(abilities ? { abilities } : {}), producer };
}

/**
 * 一项能力的设置存回这一格:`form.abilities[producer]` 换成这一份,这一格自己的草稿和产出者、别的几项能力都不动。
 * 键的先后同后端 canvas._with_ability(草稿、`abilities`、产出者)。
 */
export function withAbility(
  form: BoardItem["form"],
  producer: BoardProducer,
  setting: BoardAbilitySetting,
): NonNullable<BoardItem["form"]> {
  const { producer: own, abilities, ...rest } = form ?? {};
  return { ...rest, abilities: { ...(abilities ?? {}), [producer]: setting }, ...(own ? { producer: own } : {}) };
}

/**
 * 新放下的一格带上的表单:写明它的产出者(见 withSlotProducer)。自带表单的不在这里给 —— 调用方的表单
 * 会整个盖掉这一份,要补的话对整格调 withSlotProducer。
 */
export function newSlotForm(kind: BoardItem["kind"], extra: Partial<BoardItem> = {}): Pick<BoardItem, "form"> | null {
  if (extra.form) return null;
  const { form } = withSlotProducer<Pick<BoardItem, "kind" | "asset_id" | "form">>({ kind, asset_id: extra.asset_id });
  return form ? { form } : null;
}

/** 所有画布节点共用的六态解释。 */
export function itemRunStatus(item: BoardItem): BoardItemRunStatus {
  return item.run?.status ?? "idle";
}

export function itemIsRunning(item: BoardItem): boolean {
  const status = itemRunStatus(item);
  // 轮询必须有可查询的 job；显式状态仍可用于节点视觉，但不能凭一个缺失 job_id 的脏快照
  // 启动永远无法收敛的 polling。
  return Boolean(itemJobId(item)) && (status === "queued" || status === "running");
}

export function runningState(jobId: string): NonNullable<BoardItem["run"]> {
  return { status: "running", job_id: jobId };
}

/** 这一格这一轮(或上一轮)跑的是它的哪一项能力;不是能力的运行回 undefined(见后端 producer_ids.ability_of)。 */
export function runningAbility(item: BoardItem): BoardProducer | undefined {
  return item.run?.ability;
}

/**
 * 复制出来的一格。**进行中的运行态只属于原件**:任务的回执认的是原件那一格(见后端
 * receipt_to_item),便签写作回来的也只落在原件上 —— 带着「在跑」过去的副本永远等不到结束,
 * 框里一直转圈,面板一直按不动。副本退回空槽,表单(提示词、参数)照带,想要的话再点一次;
 * 已经结束的状态(有产出、失败原因)照样带过去。和后端「创建副本」是同一条规则。
 */
export function copiedItem(item: BoardItem, id: string): BoardItem {
  const status = itemRunStatus(item);
  if (status !== "queued" && status !== "running") return { ...item, id };
  const { run: _live, ...rest } = item;
  return { ...rest, id };
}

/**
 * 存回去之后,服务端留下的**运行态和产出**和本地送出去的不一样时,本地那一格该改成什么。
 *
 * 这两样归服务端(见后端 _keep_server_owned_state):客户端的快照改不动在跑的任务、抹不掉已经
 * 到了的产出。服务端没收下本地那一份时,本地要跟着回来 —— 否则撤销后的那一格看着是个能点的
 * 空槽,任务其实还在跑。只动这两样:位置、表单、文字是用户的,请求在路上时他可能又改了。
 */
export function serverOwnedPatch(sent: BoardItem, stored: BoardItem): Partial<BoardItem> | null {
  const same = JSON.stringify(sent.run ?? null) === JSON.stringify(stored.run ?? null) && sent.asset_id === stored.asset_id;
  return same ? null : { run: stored.run, asset_id: stored.asset_id };
}

type Bindings = NonNullable<NonNullable<BoardItem["form"]>["bindings"]>;

/** 一份绑定里,服务端摘掉了(`sent` 有、`stored` 没有)的那几条从 `mine` 里摘掉;没摘到本地的回 null。 */
function prunedBindings(sent: Bindings | undefined, stored: Bindings | undefined, mine: Bindings | undefined): Bindings | null {
  const bound = (bindings: Bindings | undefined) =>
    new Set(Object.entries(bindings ?? {}).flatMap(([field, refs]) => refs.map((ref) => `${field}|${ref.from}`)));
  const keptRefs = bound(stored);
  const droppedRefs = new Set([...bound(sent)].filter((one) => !keptRefs.has(one)));
  if (droppedRefs.size === 0 || ![...bound(mine)].some((one) => droppedRefs.has(one))) return null;
  return Object.fromEntries(
    Object.entries(mine ?? {})
      .map(([field, refs]) => [field, refs.filter((ref) => !droppedRefs.has(`${field}|${ref.from}`))] as const)
      .filter(([, refs]) => refs.length > 0),
  );
}

/**
 * 存回去之后,服务端把哪些「顺着线接上的东西」摘掉了(线已经断了 —— 规则只在后端
 * canvas._drop_detached_bindings 一处):槽位里顺着线挂上的素材、生成器和每一项能力上字段的绑定。
 * 回本地那一格该换成的表单;没摘就回 null。
 *
 * 只摘**服务端摘掉的那几份**,拿本地此刻的那一格去摘:请求在路上时用户又挂上的、又改的照留。
 */
export function prunedLinksPatch(sent: BoardItem, stored: BoardItem, local: BoardItem): Partial<BoardItem> | null {
  let form: NonNullable<BoardItem["form"]> | null = null;

  const key = (one: { asset_id: string; role: string; from?: string }) => `${one.asset_id}|${one.role}|${one.from ?? ""}`;
  const kept = new Set((stored.form?.source_assets ?? []).map(key));
  const dropped = new Set((sent.form?.source_assets ?? []).map(key).filter((one) => !kept.has(one)));
  const mine = local.form?.source_assets ?? [];
  if (dropped.size > 0 && mine.some((one) => dropped.has(key(one)))) {
    form = { ...local.form, source_assets: mine.filter((one) => !dropped.has(key(one))) };
  }

  const bindings = prunedBindings(sent.form?.bindings, stored.form?.bindings, local.form?.bindings);
  if (bindings) form = { ...(form ?? local.form), bindings };

  const myAbilities = local.form?.abilities ?? {};
  let abilities: Record<string, BoardAbilitySetting> | null = null;
  for (const [producer, setting] of Object.entries(myAbilities)) {
    const next = prunedBindings(
      sent.form?.abilities?.[producer]?.bindings,
      stored.form?.abilities?.[producer]?.bindings,
      setting.bindings,
    );
    if (next) abilities = { ...(abilities ?? myAbilities), [producer]: { ...setting, bindings: next } };
  }
  if (abilities) form = { ...(form ?? local.form), abilities };

  return form ? { form } : null;
}
/**
 * 服务端轮询到的这一格已经不在跑了:写回本地节点的补丁。成功必须连同服务端已重置的 form 一起落下。
 *
 * **按状态认「跑完了」,不按有没有失败原因。** 原因可以没有(任务失败时没留下话、被取消),
 * 此前按原因认,服务端只好拿状态名顶一个原因上去,格子上的失败原因于是写着「succeeded」。
 * 还在跑就回 null。
 */
export function boardSettlementPatch(item: BoardItem): Partial<BoardItem> | null {
  if (itemIsRunning(item)) return null;
  if (item.asset_id || itemRunStatus(item) === "succeeded") {
    return {
      //: 产出:媒体是 asset_id,便签是正文(写字的回执把它写进 text)。
      ...(item.kind === "note" ? { text: item.text } : { asset_id: item.asset_id }),
      form: item.form,
      run: item.run ?? { status: "succeeded" },
    };
  }
  return { run: item.run };
}

/**
 * Composer 的局部交互状态只在“节点拿到一份新产物”时重建。
 *
 * 不能把整个 item/form stringify 进 key：每敲一个字、拖一下节点都会 remount，光标与手动选择
 * 立刻丢失。失败/取消也不换 key，输入要留给重试；成功产生新 asset、或手动换素材，才说明
 * 上一次编辑周期已经结束。持久表单本身仍在节点上，重建后从它重新水合。
 */
export function itemFormResetKey(item: BoardItem): string {
  const completed = item.run?.status === "succeeded" ? "completed" : "draft";
  return `${item.id}:${item.asset_id ?? "empty"}:${completed}`;
}
