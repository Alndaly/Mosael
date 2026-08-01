import {
  Cake,
  Candy,
  Clapperboard,
  Flag,
  Flower,
  Flower2,
  Ghost,
  Gift,
  Heart,
  Moon,
  PartyPopper,
  Snowflake,
  Sparkles,
  TreePine,
  type LucideIcon,
} from "lucide-react";

/**
 * 首页问候区的节日彩蛋:今天是节,标题旁出现一枚徽章,背后飘对应的小图标。
 *
 * **为什么写死日期而不是算农历**:农历换算要一整套历法表,而这里只需要知道"今天是不是"。
 * 阳历节直接判月日;农历/节气节把未来几年逐个列出来 —— 过期了就自然停在"没有节日",
 * 而不是算错一天。列表到期时补几行即可,代价远小于背一个农历库。
 *
 * **颜色走自己的 token**:节日色单独定义在 tokens.css(--holiday-*),不用 Tailwind 调色板 ——
 * 这个应用的明暗两档是分别校准过的暖色系,直接塞一个 emerald-500 会在暖纸面上显脏。
 */

export type HolidayMotion = "fall" | "rise" | "pulse" | "sway";

export interface Holiday {
  id: string;
  /** i18n key。 */
  labelKey: string;
  Icon: LucideIcon;
  /** tokens.css 里的 --holiday-<accent>。 */
  accent: "red" | "amber" | "pink" | "green" | "violet" | "sky" | "orange";
  motion: HolidayMotion;
}

/** 农历 / 节气节:逐年列出。到期后自动没有节日,而不是算错。 */
const LUNAR_WINDOWS: Record<string, [string, string][]> = {
  spring_festival: [
    ["2026-02-17", "2026-02-23"],
    ["2027-02-06", "2027-02-12"],
    ["2028-01-26", "2028-02-01"],
  ],
  lantern: [["2026-03-03", "2026-03-03"], ["2027-02-20", "2027-02-20"], ["2028-02-09", "2028-02-09"]],
  qingming: [["2026-04-05", "2026-04-05"], ["2027-04-05", "2027-04-05"], ["2028-04-04", "2028-04-04"]],
  dragon_boat: [["2026-06-19", "2026-06-19"], ["2027-06-09", "2027-06-09"], ["2028-05-28", "2028-05-28"]],
  qixi: [["2026-08-19", "2026-08-19"], ["2027-08-08", "2027-08-08"], ["2028-08-26", "2028-08-26"]],
  mid_autumn: [["2026-09-25", "2026-09-25"], ["2027-09-15", "2027-09-15"], ["2028-10-03", "2028-10-03"]],
};

export const HOLIDAYS: Record<string, Holiday> = {
  new_year: { id: "new_year", labelKey: "holidayNewYear", Icon: PartyPopper, accent: "amber", motion: "rise" },
  spring_festival: { id: "spring_festival", labelKey: "holidaySpringFestival", Icon: PartyPopper, accent: "red", motion: "rise" },
  lantern: { id: "lantern", labelKey: "holidayLantern", Icon: Moon, accent: "amber", motion: "rise" },
  valentines: { id: "valentines", labelKey: "holidayValentines", Icon: Heart, accent: "pink", motion: "pulse" },
  womens_day: { id: "womens_day", labelKey: "holidayWomensDay", Icon: Flower, accent: "pink", motion: "sway" },
  qingming: { id: "qingming", labelKey: "holidayQingming", Icon: Flower2, accent: "green", motion: "sway" },
  labor_day: { id: "labor_day", labelKey: "holidayLaborDay", Icon: Sparkles, accent: "red", motion: "sway" },
  childrens_day: { id: "childrens_day", labelKey: "holidayChildrensDay", Icon: Candy, accent: "pink", motion: "sway" },
  dragon_boat: { id: "dragon_boat", labelKey: "holidayDragonBoat", Icon: Sparkles, accent: "green", motion: "sway" },
  qixi: { id: "qixi", labelKey: "holidayQixi", Icon: Heart, accent: "pink", motion: "pulse" },
  mid_autumn: { id: "mid_autumn", labelKey: "holidayMidAutumn", Icon: Cake, accent: "amber", motion: "pulse" },
  national_day: { id: "national_day", labelKey: "holidayNationalDay", Icon: Flag, accent: "red", motion: "sway" },
  halloween: { id: "halloween", labelKey: "holidayHalloween", Icon: Ghost, accent: "orange", motion: "sway" },
  christmas_eve: { id: "christmas_eve", labelKey: "holidayChristmasEve", Icon: Gift, accent: "green", motion: "fall" },
  christmas: { id: "christmas", labelKey: "holidayChristmas", Icon: TreePine, accent: "green", motion: "fall" },
  new_year_eve: { id: "new_year_eve", labelKey: "holidayNewYearEve", Icon: Snowflake, accent: "sky", motion: "fall" },
  /** 只在开发/演示时用 ?holiday=studio 预览:平日不会命中。 */
  studio: { id: "studio", labelKey: "holidayStudio", Icon: Clapperboard, accent: "violet", motion: "sway" },
};

const ymd = (date: Date) =>
  `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}-${String(date.getDate()).padStart(2, "0")}`;

const inLunarWindow = (id: string, today: string) =>
  (LUNAR_WINDOWS[id] ?? []).some(([from, to]) => today >= from && today <= to);

/** 今天是哪个节;不是节日返回 null。 */
export function holidayOf(date: Date): Holiday | null {
  const month = date.getMonth() + 1;
  const day = date.getDate();
  const today = ymd(date);

  if (month === 1 && day === 1) return HOLIDAYS.new_year;
  if (month === 2 && day === 14) return HOLIDAYS.valentines;
  if (month === 3 && day === 8) return HOLIDAYS.womens_day;
  if (month === 5 && day >= 1 && day <= 3) return HOLIDAYS.labor_day;
  if (month === 6 && day === 1) return HOLIDAYS.childrens_day;
  if (month === 10 && day >= 1 && day <= 7) return HOLIDAYS.national_day;
  if (month === 10 && day === 31) return HOLIDAYS.halloween;
  if (month === 12 && day === 24) return HOLIDAYS.christmas_eve;
  if (month === 12 && day >= 25 && day <= 26) return HOLIDAYS.christmas;
  if (month === 12 && day === 31) return HOLIDAYS.new_year_eve;

  for (const id of ["spring_festival", "lantern", "qingming", "dragon_boat", "qixi", "mid_autumn"]) {
    if (inLunarWindow(id, today)) return HOLIDAYS[id];
  }
  return null;
}

/** 稳定的伪随机:同一个位置每次渲染落在同一处,不会因为重渲染而抖。 */
export function seeded(index: number, salt: number): number {
  const value = Math.sin(index * 9301 + salt * 49297) * 233280;
  return value - Math.floor(value);
}
