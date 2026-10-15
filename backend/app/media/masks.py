"""蒙版:从一份源图的像素算出灰度蒙版,做形状运算,落盘(ADR 0056 决定 6)。

## 蒙版是什么,照抄契约,别顺手改

**灰度图、白 = 要改的地方** —— 和要改的那张图一起给(见
`app/ai/providers/contracts/generation.py` 的 `MASK`:白色是要改的地方)。它**不是一张带 alpha 的图**:
ComfyUI 插件那条注入的路读的是**红通道**(`plugins/bundled/comfyui/tools/graph.py` 的 `_MASK_CHANNEL`,
注释里写着带透明通道的图读出来是整块不透明),一张带 alpha 的图传过去会**静默地什么都不重绘**。
所以这里每交出一张蒙版都守着两条:

- `r = g = b`(灰度;灰度图里红通道就是那个灰);
- alpha 一律不透明。

守法的办法是**根本不写出 alpha 通道**:落盘走 PIL 的 `L` 模式(见 `write_mask_png`),蒙版在内存里
也是单通道的 `bytes`(一像素一个字节),四通道那种排法只在**读源图**时出现一次(见 `read_rgba`)。

## 和前端画布那一份的关系

编辑器(`frontend/src/lib/maskPixels.ts`)里的阈值、反选、扩张、羽化和这里是**同一套规则**(阈值按 Rec.601
加权、`>=` 判白、扩张按**圆盘**(数字八边形)取极值、羽化三遍盒式模糊、四边夹取、半径半数进位):同一张底图、同一组参数,
两边该切出同一串字节。这条"同一串字节"由 `contracts/mask-cases.json` 钉着(两侧读**同一份**语料、逐字节比),
改这里之前先看那边,反过来也一样。

## 蒙版只有一种形状、一个写出口(ADR 0057)

这里交出去的蒙版一律是**单通道字节 + 尺寸**:按配方算的(`recipe_mask`)、画出来再归一的(`painted_mask`)
都一样。落盘(`write_mask_png`,`L` 模式)和登记成素材是 `app/domain/assets/masks.write_mask_asset` 一处的事。

## 尺寸约定

`size` 一律是 `(width, height)`(和 PIL 的 `Image.size` 一样);一份 RGBA 像素是四通道、长度 =
`width * height * 4`(和 canvas 的 `ImageData.data` 一样)。蒙版本身是单通道、长度 = `width * height`。
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import BinaryIO

import numpy as np
from PIL import Image, ImageOps

from app.core.i18n import LocalizedError

#: 从源图的哪一样算阈值。请求体里那个 `source` 字段的合法取值。
LUMINANCE = "luminance"
ALPHA = "alpha"
SOURCES = (LUMINANCE, ALPHA)

#: 一像素几个通道(RGBA,和 canvas 的 ImageData 一样)。
CHANNELS = 4
#: Rec.601 —— 和 `lib/maskPixels.ts` 的 LUMA_* 同一组系数:底图不是灰的,按亮度加权才和眼睛看到的「亮」一致。
LUMA_R, LUMA_G, LUMA_B = 0.299, 0.587, 0.114
#: 羽化三遍盒式模糊(≈ 高斯,中心极限),和前端一遍一遍跑的次数一样。
FEATHER_PASSES = 3

MASK_FILENAME = "mask.png"
#: EXIF 里「方向」那一项的标签号(PIL 的 `ExifTags.Base.Orientation`)。
_EXIF_ORIENTATION = 0x0112


class MaskError(LocalizedError, ValueError):
    """这份像素算不出蒙版。带文案 key(`maskErr_*`),api 那一层翻成状态码。"""


def clamp01(value: float) -> float:
    """0..1 之外的一律夹回来;不是数的(NaN、inf)当 0。

    和 `lib/maskPixels.ts` 的 `clamp01` 一样 —— 界面上那根滑块的原始值就是按它解释的。
    """
    return 0.0 if not math.isfinite(value) else min(1.0, max(0.0, value))


def _cut(threshold: float) -> float:
    """阈值(0..1)换算成 0..255 的那条线。0 全白、1 只剩纯白,两头都是合法输入,不特殊处理。"""
    return clamp01(threshold) * 255


def _flat(mask) -> bytes:
    """一份单通道蒙版摊成字节。`bytes` / `bytearray` / numpy 数组都收。"""
    if isinstance(mask, bytes):
        return mask
    if isinstance(mask, bytearray):
        return bytes(mask)
    return np.ascontiguousarray(mask, dtype=np.uint8).tobytes()


def _size_of(size: tuple[int, int]) -> tuple[int, int]:
    """宽高收成 int,`0` / 负数报错。

    这里的 `int()` **不是**「取整规则」,是尺寸的类型收口:宽高是**像素的个数**,不是半径 ——
    「7.5 列」这种尺寸不存在,而它上游(`Image.size`、画布的 `width` / `height`)本来就只给整数。
    半径类的取整规则只有一条,写在 `_half_up` 那一处;别把这里也一起"统一"过去。
    """
    width, height = int(size[0]), int(size[1])
    if width < 1 or height < 1:
        raise MaskError("maskErr_badSize", width=width, height=height)
    return width, height


def _shape(pixels, size: tuple[int, int]) -> np.ndarray:
    """一份 RGBA 像素摊成 `(height, width, 4)` 的 uint8。长度对不上直接报错 ——

    按错的宽度重排像素,出来的是一张谁也认不出的图,而蒙版这东西的失效方式是**静默**的
    (读出来全空 = 什么都不重绘),宁可当场炸。
    """
    width, height = _size_of(size)
    raw = np.frombuffer(bytes(pixels), dtype=np.uint8)
    expected = width * height * CHANNELS
    if raw.size != expected:
        raise MaskError("maskErr_badPixels", expected=expected, got=int(raw.size))
    return raw.reshape(height, width, CHANNELS)


def _array(mask, size: tuple[int, int]) -> np.ndarray:
    """一份单通道蒙版摊成 `(height, width)` 的 uint8。长度对不上直接报错,理由同 `_shape`。"""
    width, height = _size_of(size)
    raw = np.frombuffer(_flat(mask), dtype=np.uint8)
    if raw.size != width * height:
        raise MaskError("maskErr_badPixels", expected=width * height, got=int(raw.size))
    return raw.reshape(height, width)


def _channels(pixels, size: tuple[int, int]) -> tuple[np.ndarray, np.ndarray]:
    """`(灰度, alpha)` 两份 `(height, width)` 的数组。

    灰度按 Rec.601 在 **float64** 里算:JS 的数是双精度,用 float32 会在阈值那一线上切出和前端
    不一样的图(差一个像素的边,而那正好是羽化过的那条边),这里也没有哪一处需要省那点内存。

    逐通道取而不是把整份 RGBA 先转成 float64:后者对一张 4K 图要多占四倍内存(四个通道里只用到
    三个,而且转的是 uint8 的那个副本)。
    """
    shaped = _shape(pixels, size)
    red, green, blue, alpha = (shaped[:, :, index] for index in range(CHANNELS))
    return LUMA_R * red + LUMA_G * green + LUMA_B * blue, alpha


def _as_mask(white: np.ndarray) -> bytes:
    """二值结果写回单通道蒙版:非黑即白(255 / 0)。"""
    return np.where(white, 255, 0).astype(np.uint8).tobytes()


def mask_from_luminance(pixels, size: tuple[int, int], threshold: float = 0.5) -> bytes:
    """**按亮度**阈值二值化:亮度 ≥ `threshold` 的变白(要改的地方),其余变黑。

    `threshold` 是 0..1。0 全白、1 只剩纯白 —— 两头都是合法输入,不特殊处理。源图直接喂进来也行
    (灰阶加权对灰像素就是它自己)。
    """
    gray, _ = _channels(pixels, size)
    return _as_mask(gray >= _cut(threshold))


def mask_from_alpha(pixels, size: tuple[int, int], threshold: float = 0.5) -> bytes:
    """**按 alpha** 阈值二值化:不透明的地方变白。

    抠好的 PNG(主体实、背景透)走这一条就是「把它抠出来」。源图没有透明通道时是整块白 ——
    那不是这里算错,是那张图本来就没有透的地方。
    """
    _, alpha = _channels(pixels, size)
    return _as_mask(alpha >= _cut(threshold))


def invert_mask(mask) -> bytes:
    """反选:黑变白、白变黑。

    灰的(羽化过的边)按 `255 - v` 翻,边翻过来还是同样软的一条边 —— 不是重新二值化。
    """
    return (255 - np.frombuffer(_flat(mask), dtype=np.uint8)).astype(np.uint8).tobytes()


def _disc_diagonal_floor(reach: int) -> int:
    """数字圆盘 `dx² + dy² ≤ r²` 里 `|dx| + |dy|` 的最大值 —— 八边形的对角边至少要有这么大。

    `math.isqrt` 是**精确的整数**开方(不是浮点近似),和前端 `lib/maskPixels.discDiagonalFloor`
    同一段循环:两侧算出的是同一个整数,形状不会在边界像素上差一格。
    """
    best = 0
    for dx in range(reach + 1):
        dy = math.isqrt(reach * reach - dx * dx)
        best = max(best, dx + dy)
    return best


def _disc_segments(reach: int) -> list[list[tuple[int, int, int]]]:
    """半径 `reach`(≥ 1)的**圆盘**结构元,拆成一组 1-D 线段 —— 前端 `maskPixels.discSegments` 同一份规则。

    组内按顺序各做一趟(结构元 = 这些线段的**闵可夫斯基和**),组与组之间取**并**:

    - `r = 1`:十字(两组 = 横、竖)—— 半径 1 的数字圆盘就是十字,而四向八边形做不出它(十字不是凸的);
    - `r = 2`:菱形 `|dx| + |dy| ≤ 2`(两组 = 3×3 的方、两条对角)—— 整数上它与 `dx² + dy² ≤ 4` 等价;
    - `r ≥ 3`:一组四段线段(0° / 45° / 90° / 135°)= 数字八边形
      `{|dx| ≤ r, |dx ± dy| ≤ M}`,`M` 是**能盖住数字圆盘的最小偶数**。

    `M` 取偶数是闵可夫斯基和自带的约束(它给出来的八边形恒有 `M = 2 × 两条线段半长之和`);
    取"能盖住圆盘"的那一侧 ⇒ 扩张半径 r **从不欠账**。小半径那两档为什么单独写、误差有多大,
    见 `grow_mask` 的 docstring 与 `contracts/mask-cases.json` 的 `semantics`。
    """
    if reach <= 1:
        return [[(1, 0, 1)], [(0, 1, 1)]]
    if reach == 2:
        return [[(1, 0, 1), (0, 1, 1)], [(1, 1, 1), (1, -1, 1)]]
    floor = _disc_diagonal_floor(reach)
    even = floor + (floor % 2)
    axis = even - reach
    diagonal = reach - even // 2
    return [[(1, 0, axis), (0, 1, axis), (1, 1, diagonal), (1, -1, diagonal)]]


def _shift(mask: np.ndarray, steps: int, dx: int, dy: int) -> np.ndarray:
    """把 `mask` 沿 `(dx, dy)` 平移 `steps` 格,越界处取边上那个像素(`mode="edge"`)。

    传进来的图是**已经补好夹取边**的那一张(见 `grow_mask`),所以这里夹到的边界是补出来的那一圈,
    不是原来那张图的边界 —— 组内每一趟都不必再想"取样点夹回原图"这回事。

    `mode="edge"` 的填充逐坐标夹取,夹取又是幂等的 ⇒ 两次夹取复合与一次夹取同值,倍增拼出来的每一块
    都对得上朴素窗口(`backend/tests/test_masks.py` 里那条对朴素窗口的用例钉着)。
    """
    if steps == 0:
        return mask
    height, width = mask.shape
    padded = np.pad(mask, ((steps, steps), (steps, steps)), mode="edge")
    top, left = steps + steps * dy, steps + steps * dx
    return padded[top:top + height, left:left + width]


def _one_sided(mask: np.ndarray, reach: int, dx: int, dy: int, *, keep) -> np.ndarray:
    """`{0, 1, …, reach}` 每一格上的极值(沿 `(dx, dy)`,越界夹取)。

    **倍增**:`levels[k]` 是一张盖住连续 `2^k` 格的图(`levels[k] = keep(levels[k-1], levels[k-1] 平移 2^(k-1))`),
    再把 `reach + 1` 按二进制拆成几块、各平移到位后拼起来。整图操作从 `2·reach` 遍降到
    `~2·log2(reach)` 遍 —— 半径 256 那一档此前是 512 遍整图(约 6 秒),现在十几遍。
    """
    total = reach + 1
    levels = [mask]
    while (1 << len(levels)) <= total:
        levels.append(keep(levels[-1], _shift(levels[-1], 1 << (len(levels) - 1), dx, dy)))
    result = None
    remaining, offset = total, 0
    for k in range(len(levels) - 1, -1, -1):
        block = 1 << k
        if remaining < block:
            continue
        piece = levels[k] if offset == 0 else _shift(levels[k], offset, dx, dy)
        result = piece if result is None else keep(result, piece)
        offset += block
        remaining -= block
    return result


def _extremum_segment(mask: np.ndarray, reach: int, dx: int, dy: int, *, maximum: bool) -> np.ndarray:
    """沿方向 `(dx, dy)` 取 `[i-reach, i+reach]` 的极值 —— 一维形态学(膨胀 / 腐蚀)。

    窗口对 `i` 是对称的 ⇒ 正向 `{0..reach}` 与反向 `{-reach..0}` 各自取极值再并;方向的正负号
    不影响窗口本身,和前端 `extremumAlong` 那条"四趟不是八趟"是同一件事。
    """
    if reach < 1:
        return mask
    keep = np.maximum if maximum else np.minimum
    return keep(
        _one_sided(mask, reach, dx, dy, keep=keep),
        _one_sided(mask, reach, -dx, -dy, keep=keep),
    )


def grow_mask(mask, size: tuple[int, int], radius: float) -> bytes:
    """扩张(`radius` > 0)/ 收缩(`radius` < 0)`|radius|` 个像素,**形态学**:结构元是**圆盘**。

    扩张取窗口最大值,收缩取窗口最小值。灰的(羽化过的边)照灰的取最大 / 最小,不先二值化:
    那一圈软边是用户自己调出来的,不该被这一步啃掉。

    ## 为什么不是正方形

    此前窗口是 `(2r+1)×(2r+1)` 的**正方形**,于是一个圆点扩张之后是一个**带直角的方块**。
    现在窗口是圆盘:一个点扩出去还是圆的(只是更大)。

    ## 怎么算(圆盘不可分离)

    正方形可分离(横一趟 + 竖一趟),圆盘不行。所以圆盘走「**若干 1-D 线段的闵可夫斯基和**」:
    沿 0° / 45° / 90° / 135° 各做一趟一维膨胀,**顺序复合**起来是一个数字八边形
    (凸结构元的膨胀 = 它各条边的 1-D 膨胀按顺序复合 —— 八条边、四个方向 ⇒ 四趟)。
    每趟是"沿一条线取一段的极值",由 `_extremum_segment` 用倍增在 `~log2(reach)` 遍整图里算完。

    注意不是「四趟取**并**」:四趟的并是一个点被扩成米字形的星;**顺序复合**才是那个多边形
    (前端 `lib/maskPixels.growMask` 是同一份形状规则的另一份实现:那边沿每条线走单调队列)。

    ## 边界:整组**先补边**,组内每一趟都不夹取

    「越界的取样点取边上那个像素」说的是**结构元的每一个取样点**:先夹取、再取极值。这跟"每一趟各自
    夹取、再把结果串起来"**不是**同一件事 —— 夹取会打断平移不变性:`clamp(clamp(y+2)-3)` 可能回到
    图里,而 `clamp(y+2-3)` 不会。正方形的两轴各管一个坐标、互不干扰,差别看不出来;圆盘的对角两趟
    同时动两个坐标,贴着边就会差出来。

    所以每一组先按"这一组所有趟的偏移之和"在四周补上**夹取边**(`np.pad(..., mode="edge")`),组内
    每一趟都在补好的图上跑、取回的中间那块就恰好是"每个取样点各自夹取"的结果。契约里那几条贴着边的
    用例钉着这条。

    ## 形状与语义

    结构元是数字圆盘 `dx² + dy² ≤ r²` 的八向近似:r ≤ 2 时**精确**(十字 / 菱形),r ≥ 3 时是
    "内切半径 r 的八边形"(`_disc_segments` 的 M 规则)。于是「扩张 r」的结果**一定含住**半径 r 的
    真圆盘(不欠账),八个顶点方向上最多多出 ~8%(r = 4 / 5 因为 M 只能取偶数,最多 ~17%)。
    三档怎么分、M 为什么取偶数、两侧怎么保证同一串字节,见 `contracts/mask-cases.json` 的 `semantics`。

    半径是「半径类参数」,和 `feather_mask` 走**同一条规则**(写在一处:见 `_half_up`)——
    一律**半数进位**、对齐前端与契约那边的 `Math.round`:`0.5` 扩张 1 格、`2.5` 扩张 3 格、
    `-1.7` 收缩 2 格,`0.4` 取整成 0 格 ⇒ 原样。此前这里是 `int(radius)`(**向零截断**:
    `0.5 → 0`、`2.5 → 2`、`-1.7 → 1`),同一个形状的坑 —— 今天**用户侧**够不着(`grow` 三条入口都是
    整数:HTTP schema 与 MCP 签名是 `int`,素材库对话框那格先 `Math.round`),但两处半径各说各话时,
    同一组参数会在后端与编辑器里出来两张图(见 `contracts/mask-cases.json` 的 `grow_rounding`
    与那几条 `grow` 小数用例)。

    半径按图像的长边封顶:扩张半个图宽和扩张整个图宽是同一个结果(全白 / 全黑),再往上只是
    白算一遍。`radius == 0`(取整后 0 格也一样)原样返回。
    """
    if radius == 0:
        return _flat(mask)
    source = _array(mask, size)
    maximum = radius > 0
    reach = min(abs(_half_up(radius)), max(source.shape))
    if reach < 1:
        return _flat(mask)
    #: 组内顺序复合(闵可夫斯基和),组间取并 —— 只有 r ≤ 2 会分成两组(十字 / 菱形)。
    #: 每一组各补各的边(这一组所有趟的偏移之和),补好之后组内每一趟都不夹取(见 docstring)。
    grown = None
    for group in _disc_segments(reach):
        pad_x = sum(abs(dx) * step for dx, _dy, step in group)
        pad_y = sum(abs(dy) * step for _dx, dy, step in group)
        result = np.pad(source, ((pad_y, pad_y), (pad_x, pad_x)), mode="edge")
        for dx, dy, step in group:
            result = _extremum_segment(result, step, dx, dy, maximum=maximum)
        result = result[pad_y:pad_y + source.shape[0], pad_x:pad_x + source.shape[1]]
        if grown is None:
            grown = result
        else:
            grown = np.maximum(grown, result) if maximum else np.minimum(grown, result)
    return grown.astype(np.uint8).tobytes()


def _box_blur_axis(channel: np.ndarray, reach: int, axis: int) -> np.ndarray:
    """一趟盒式模糊:窗口是 `[i-reach, i+reach]`,边上的取样点夹取(见 `grow_mask` 那段边界)。

    用前缀和跑。前端是一格一格加减的滑动窗口 —— 那些和都是整数、双精度里精确,和这里的差值
    逐位相等,但这里不必在 Python 里逐行循环。**每跑完一趟落回 float32**:前端那一趟写进的是
    `Float32Array`,精度得跟着它,不然三趟下来会差出肉眼看不见、但两边对不上的半格。
    """
    if reach < 1:
        return channel
    pad = ((reach, reach), (0, 0)) if axis == 0 else ((0, 0), (reach, reach))
    padded = np.pad(channel.astype(np.float64), pad, mode="edge")
    #: 前缀和就地算(`padded` 本来就是这一趟自己的副本),省一份整图大小的临时数组。
    totals = np.cumsum(padded, axis=axis, out=padded)
    #: 前面接一格 0:`totals[j]` 从此是 `padded[0..j-1]` 的和,窗口两端可以直接相减。
    totals = np.concatenate([np.zeros_like(np.take(totals, [0], axis=axis)), totals], axis=axis)
    length = channel.shape[axis]
    span = 2 * reach + 1
    upper = np.take(totals, np.arange(span, span + length), axis=axis)
    lower = np.take(totals, np.arange(0, length), axis=axis)
    return ((upper - lower) / span).astype(np.float32)


def _half_up(value: float) -> int:
    """四舍五入,**半数进位**(`floor(x + 0.5)`)—— **`masks.py` 里所有半径类参数只走这一处**。

    半径有两个:`grow`(扩张 / 收缩)和 `feather`(羽化)。两个都对齐前端 / 契约那边的 `Math.round`
    (`0.5 → 1`、`2.5 → 3`;负数也一样:`Math.round(-1.5) == -1`),也和羽化往回写那一处的
    `floor(x + 0.5)` 同一条规则。差一格看着无所谓,但同一组参数该在两侧出来同一串字节 ——
    而两边都看不出错:Python 内建 `round` 是「半数取偶」(`round(0.5) == 0`、`round(2.5) == 2`),
    向零截断(`int(0.5) == 0`、`int(2.5) == 2`)更是每个小数都少一格。前者在这里真发生过一次
    (`feather`),后者是同一个形状的坑(`grow` 此前就是它)—— 两条都钉在 `contracts/mask-cases.json`
    的 `rounding` / `grow_rounding` 上。
    """
    return math.floor(value + 0.5)


def feather_mask(mask, size: tuple[int, int], radius: float) -> bytes:
    """羽化:把边晕开 `radius` 个像素。

    三遍盒式模糊 ≈ 高斯(中心极限),够用而且没有系数要调。单通道跑 —— 羽化只对灰度有定义,
    四通道各跑一遍是四倍工作量、结果还一样。边缘夹取,理由同 `grow_mask`。`radius < 1` 什么都不做
    (0.4px 的模糊看不出来,却是六遍全画布扫描)。

    `radius` 是浮点,**决定结果的是取整后的那一格** `reach = _half_up(radius)`:半径类参数的同一条
    规则写在 `_half_up` 那一处(`grow` 与 `feather` 都半数进位、都对齐前端的 `Math.round`),
    往回写那一处 `floor(x + 0.5)` 也是它 —— 不是 numpy / Python 缺省的「半数取偶」。所以
    `feather = 0.5` 两边都是 1 格(不是"后端不羽化、编辑器羽化"),`feather = 2.5` 两边都是 3 格。
    """
    reach = _half_up(radius)
    if reach < 1:
        return _flat(mask)
    channel = _array(mask, size).astype(np.float32)
    #: 一横一纵 = 一遍;三遍下来,权重分布已经贴着高斯了。
    for _ in range(FEATHER_PASSES):
        channel = _box_blur_axis(_box_blur_axis(channel, reach, 1), reach, 0)
    return np.floor(channel + np.float32(0.5)).clip(0, 255).astype(np.uint8).tobytes()


def write_mask_png(target: Path, mask, size: tuple[int, int]) -> Path:
    """把一份单通道蒙版写成 PNG(模式 `L`)。

    **`L` 模式的 PNG 里根本没有 alpha 通道** —— 契约那条「灰、不透明」就落在这里,不靠调用方记得。
    走 `RGBA` 存的话会多出一个全 255 的通道:读回来 `r=g=b` 是成立的,但那一层要靠在别处再擦一遍,
    而漏擦的失效方式是静默的。
    """
    width, height = _size_of(size)
    data = _flat(mask)
    if len(data) != width * height:
        raise MaskError("maskErr_badPixels", expected=width * height, got=len(data))
    target.parent.mkdir(parents=True, exist_ok=True)
    Image.frombytes("L", (width, height), data).save(target, "PNG")
    return target


def read_rgba(source: Path) -> tuple[bytes, tuple[int, int]]:
    """源图的 RGBA 像素和尺寸(`(width, height)`)。

    手机拍的图先按 EXIF 摆正 —— 不摆正的话「按亮度取上半张」取到的是侧着的那半张,而用户在界面上
    看的是正的那张(和 domain/assets/image_grid 切宫格前的处理是同一件事)。
    """
    with Image.open(source) as opened:
        image = ImageOps.exif_transpose(opened).convert("RGBA")
        return image.tobytes(), image.size


def oriented_size(source: Path) -> tuple[int, int]:
    """源图**摆正之后**的尺寸 —— 蒙版要和它一样大(ADR 0057 决定 1)。

    浏览器按 EXIF 摆正了才显示(编辑器里画的就是摆正的那张),所以竖拍的 4000×3000 在这里是 3000×4000。
    只读文件头,不解码像素。
    """
    with Image.open(source) as opened:
        width, height = opened.size
        orientation = opened.getexif().get(_EXIF_ORIENTATION, 1)
    #: 5–8 是转了 90° / 270° 的那四种(含镜像):宽高互换。
    return (height, width) if orientation in (5, 6, 7, 8) else (width, height)


def recipe_mask(
    source: Path,
    *,
    source_kind: str = LUMINANCE,
    threshold: float = 0.5,
    invert: bool = False,
    grow: int = 0,
    feather: float = 0,
) -> tuple[bytes, tuple[int, int]]:
    """按配方从源图算一张蒙版:单通道字节 + 尺寸(和摆正后的源图一样大)。不落盘 —— 落盘是写出口的事。

    四步的先后是定死的:**阈值 → 反选 → 扩张/收缩 → 羽化**。

    - 阈值一定在最前:后面三步都是对已经分好黑白的那张图做的,先羽化再阈值等于把羽化扔掉;
    - 反选在扩张之前:反选和扩张换不了序(先扩后翻 = 先翻后缩),这里说的是「翻过来,再按这个半径
      长 / 缩」—— 用户点的是反选那一下,后面的形状是对反选后的结果说的;
    - 羽化一定在最后:它是唯一一个把边弄软的步骤,放前面会被后面的形态学再啃硬。

    编辑器里「应用到蒙版」那一下也是先扩张、再羽化(`lib/maskPixels`,两侧由 contracts/mask-cases.json 钉成同一串字节)。
    """
    if source_kind not in SOURCES:
        raise MaskError("maskErr_unknownSource", source=source_kind)
    pixels, size = read_rgba(source)
    if source_kind == ALPHA:
        mask = mask_from_alpha(pixels, size, threshold)
    else:
        mask = mask_from_luminance(pixels, size, threshold)
    if invert:
        mask = invert_mask(mask)
    if grow:
        mask = grow_mask(mask, size, grow)
    if feather:
        mask = feather_mask(mask, size, feather)
    return mask, size


def painted_mask(painted: Path | BinaryIO, size: tuple[int, int] | None = None) -> tuple[bytes, tuple[int, int]]:
    """一张**画出来的**蒙版图归一成契约那个形状:单通道字节 + 尺寸(ADR 0057 决定 2)。

    - 读的是**红通道** —— 和 ComfyUI 那条注入的 `LoadImageMask(channel="red")` 读的是同一个通道;
      灰度图(`L`)的红通道就是它自己。
    - **透明的地方当黑**(= 不改):先铺在黑底上再取红通道。带 alpha 的图交到插件那边会被读成整块不透明,
      所以 alpha 在这里就消化掉,不往后带。
    - `size` 给了、又和画出来的不一样(编辑器的文档长边封顶 4096,源图比它大)就**双线性**缩放过去:
      最近邻会在边上拉出锯齿,而羽化过的软边经双线性缩放仍是软边。
    """
    with Image.open(painted) as opened:
        rgba = opened.convert("RGBA")
    flattened = Image.alpha_composite(Image.new("RGBA", rgba.size, (0, 0, 0, 255)), rgba).getchannel("R")
    if size is not None:
        target = _size_of(size)
        if flattened.size != target:
            flattened = flattened.resize(target, Image.Resampling.BILINEAR)
    return flattened.tobytes(), flattened.size


def normalize_mask_file(path: Path, size: tuple[int, int] | None) -> bool:
    """把一个已经存下来的蒙版文件**就地**归一成契约那个形状(迁移 `normalize-mask-files` 用)。

    已经是 `L` 模式、尺寸也对(或者没有源图可对)就不动,返回 False;改写了返回 True。可以重复跑。
    """
    with Image.open(path) as opened:
        already = opened.mode == "L" and (size is None or opened.size == tuple(size))
    if already:
        return False
    mask, actual = painted_mask(path, size)
    write_mask_png(path, mask, actual)
    return True


__all__ = [
    "ALPHA",
    "CHANNELS",
    "FEATHER_PASSES",
    "LUMINANCE",
    "MASK_FILENAME",
    "SOURCES",
    "MaskError",
    "clamp01",
    "feather_mask",
    "grow_mask",
    "invert_mask",
    "mask_from_alpha",
    "mask_from_luminance",
    "normalize_mask_file",
    "oriented_size",
    "painted_mask",
    "read_rgba",
    "recipe_mask",
    "write_mask_png",
]
