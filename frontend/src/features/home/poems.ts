/**
 * 首页「每日一句」:本地精选古诗词,主题偏光影 / 时序 / 创作心境。
 *
 * 刻意不用外部 API(今日诗词等)——Mibu 本地优先,首页不该因断网少一块;
 * 数据量小到不值得一次网络请求。按日期取句保证一天内稳定,刷新按钮随机换。
 */

export interface Poem {
  text: string;
  author: string;
  source: string;
}

export const POEMS: Poem[] = [
  { text: "落霞与孤鹜齐飞,秋水共长天一色。", author: "王勃", source: "滕王阁序" },
  { text: "大漠孤烟直,长河落日圆。", author: "王维", source: "使至塞上" },
  { text: "月出惊山鸟,时鸣春涧中。", author: "王维", source: "鸟鸣涧" },
  { text: "疏影横斜水清浅,暗香浮动月黄昏。", author: "林逋", source: "山园小梅" },
  { text: "山重水复疑无路,柳暗花明又一村。", author: "陆游", source: "游山西村" },
  { text: "两个黄鹂鸣翠柳,一行白鹭上青天。", author: "杜甫", source: "绝句" },
  { text: "日出江花红胜火,春来江水绿如蓝。", author: "白居易", source: "忆江南" },
  { text: "接天莲叶无穷碧,映日荷花别样红。", author: "杨万里", source: "晓出净慈寺送林子方" },
  { text: "泉眼无声惜细流,树阴照水爱晴柔。", author: "杨万里", source: "小池" },
  { text: "不识庐山真面目,只缘身在此山中。", author: "苏轼", source: "题西林壁" },
  { text: "人有悲欢离合,月有阴晴圆缺。", author: "苏轼", source: "水调歌头" },
  { text: "竹外桃花三两枝,春江水暖鸭先知。", author: "苏轼", source: "惠崇春江晚景" },
  { text: "欲把西湖比西子,淡妆浓抹总相宜。", author: "苏轼", source: "饮湖上初晴后雨" },
  { text: "千里莺啼绿映红,水村山郭酒旗风。", author: "杜牧", source: "江南春" },
  { text: "停车坐爱枫林晚,霜叶红于二月花。", author: "杜牧", source: "山行" },
  { text: "孤舟蓑笠翁,独钓寒江雪。", author: "柳宗元", source: "江雪" },
  { text: "海上生明月,天涯共此时。", author: "张九龄", source: "望月怀远" },
  { text: "春江潮水连海平,海上明月共潮生。", author: "张若虚", source: "春江花月夜" },
  { text: "无边光景一时新,等闲识得东风面。", author: "朱熹", source: "春日" },
  { text: "问渠那得清如许?为有源头活水来。", author: "朱熹", source: "观书有感" },
  { text: "纸上得来终觉浅,绝知此事要躬行。", author: "陆游", source: "冬夜读书示子聿" },
  { text: "长风破浪会有时,直挂云帆济沧海。", author: "李白", source: "行路难" },
  { text: "此中有真意,欲辨已忘言。", author: "陶渊明", source: "饮酒·其五" },
  { text: "文章本天成,妙手偶得之。", author: "陆游", source: "文章" },
];

/** 当天固定一句(以日期为种子),刷新时再随机。 */
export function poemOfToday(): Poem {
  const today = new Date();
  const seed = today.getFullYear() * 372 + (today.getMonth() + 1) * 31 + today.getDate();
  return POEMS[seed % POEMS.length];
}

export function randomPoem(exclude?: Poem): Poem {
  const pool = exclude ? POEMS.filter((poem) => poem !== exclude) : POEMS;
  return pool[Math.floor(Math.random() * pool.length)];
}
