"""名字按什么顺序排:中文按拼音、和英文按字母混排,数字按大小。

素材库分页之后,名称排序从浏览器挪到了服务端,成了 SQLite 的码位顺序,中文名不再按拼音。这里把名字换成一串
**排序键**,数据库按它的字节顺序排:

1. 按字的类别分先后:空白和标点 < 数字 < 字母 < 其余文字;
2. 汉字换成拼音(不分声调),和拉丁字母算同一类、按字母混排:阿(a)< apple < Banana < 草莓(cao)。
   拉丁字母不分大小写、不分重音(全角先折成半角,é 和 e 排在一起);
3. 一串数字按数值比:「第2集」排在「第10集」前面。

键的形状:一个个「类别号 + 内容」接起来。一串拉丁字母是一段,汉字一个音节一段,一串数字是一段(先写位数再写
数字,位数少的就小),标点一个字一段。类别号是 1–4 这几个数字字符,比任何字母都小,所以它同时是段与段的分隔:
「阿姨」(a·yi)排在「爱」(ai)前面,「B站」(b·zhan)排在「Banana」前面。

以上都一样的(只差大小写、全角、重音、数字前面的 0,或者英文和拼音拼出来相同:a 和「阿」),键的最后接上原名
定先后 —— 中间隔一个比任何类别号都小的 `0`,所以它只在前面完全相同时才起作用。这样同一份名单怎么排都是同一个顺序,
不用指望插入顺序。

多音字按词组读(pypinyin 带词组表):「重庆」是 chong、「长城」是 chang、「银行」是 yin·hang。

**规则一改,库里存着的键就旧了**:改这里的同时加一条迁移把 `assets.name_sort_key` 整列重算(见 db/migrations 里
算这一列的那一步)。
"""

from __future__ import annotations

import itertools
import re
import unicodedata

PUNCTUATION = "1"
DIGIT = "2"
LETTER = "3"
OTHER = "4"
#: 主键和原名之间的分隔:比任何类别号都小,原名只在主键完全相同时才比得到。
TIEBREAK = "0"

#: 汉字:基本区、扩展 A、兼容区,以及扩展 B 往后的几个平面。
_HAN_RUN = re.compile("[㐀-䶿一-鿿豈-﫿\U00020000-\U0002ebef\U00030000-\U0003134f]+")
#: 一串数字、一串字母(\w 去掉数字和下划线),或者其余的一个字。
_TOKEN = re.compile(r"(\d+)|([^\W\d_]+)|(.)", re.DOTALL)


def name_sort_key(name: str) -> str:
    """名字的排序键(按字节比就是模块说明里那个顺序)。"""
    folded = unicodedata.normalize("NFKD", name)
    parts: list[str] = []
    position = 0
    for run in _HAN_RUN.finditer(folded):
        parts.append(_non_han(folded[position:run.start()]))
        parts.append("".join(LETTER + syllable for syllable in _pinyin(run.group())))
        position = run.end()
    parts.append(_non_han(folded[position:]))
    return "".join(parts) + TIEBREAK + name


def _pinyin(han: str) -> list[str]:
    """一段汉字的拼音,一个字一个音节,不带声调,按词组定多音字。查不到的字原样留着(排在字母这一类最后)。

    在用到时才载入:两张字典表(几 MB 的 JSON)不该算进后端启动的时间。"""
    from pypinyin import Style, lazy_pinyin

    return [syllable.lower() for syllable in lazy_pinyin(han, style=Style.NORMAL)]


def _non_han(text: str) -> str:
    # 重音、变音符号:é 拆成 e + ́ 之后只留 e
    plain = "".join(char for char in text if not unicodedata.combining(char)).lower()
    out: list[str] = []
    for digits, letters, other in _TOKEN.findall(plain):
        if digits:
            out.append(_number(digits))
        elif letters:
            for latin, run in itertools.groupby(letters, _is_latin):
                out.append((LETTER if latin else OTHER) + "".join(run))
        else:
            out.append(PUNCTUATION + other)
    return "".join(out)


def _number(digits: str) -> str:
    """一串数字按数值比:先写位数(两位,去掉前面的 0 之后),位数一样再一位位比。"""
    value = str(int(digits))
    return DIGIT + f"{min(len(value), 99):02d}" + value


def _is_latin(char: str) -> bool:
    return char.isascii() or unicodedata.name(char, "").startswith("LATIN")
