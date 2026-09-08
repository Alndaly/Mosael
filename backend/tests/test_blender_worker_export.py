"""`worker.py` 跑在 Blender 里,平时测不到 —— 但导出的**降级梯子**正是最容易烂掉的那种代码:
它只在别人的场景上触发,而我们自己的往返用例永远走不到第二次尝试。

所以这里把 `bpy` 换成假的,单测 `export_glb` 的三件事:顺利时不降级、失败时退到只导几何体、
以及**降级必须出一条警告**(悄悄少掉材质比直接报错更难查)。
"""
import importlib.util
import sys
import types
from pathlib import Path

import pytest

WORKER = Path(__file__).resolve().parents[1] / 'app' / 'domain' / 'blender' / 'worker.py'


def load(export):
    """把 worker.py 载进来,`bpy.ops.export_scene.gltf` 换成给定的假实现。"""
    bpy = types.ModuleType('bpy')
    bpy.ops = types.SimpleNamespace(export_scene=types.SimpleNamespace(gltf=export),
                                    import_scene=types.SimpleNamespace(gltf=lambda **k: None))
    bpy.data = types.SimpleNamespace()
    bpy.context = types.SimpleNamespace()
    bpy.app = types.SimpleNamespace(version_string='5.2.0')
    mathutils = types.ModuleType('mathutils')
    mathutils.Vector = lambda v: v
    saved = {name: sys.modules.get(name) for name in ('bpy', 'mathutils')}
    sys.modules['bpy'], sys.modules['mathutils'] = bpy, mathutils
    try:
        spec = importlib.util.spec_from_file_location('mosael_blender_worker', WORKER)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    finally:
        for name, value in saved.items():
            if value is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = value


def test_a_clean_export_does_not_degrade():
    calls = []
    module = load(lambda **options: calls.append(options))
    assert module.export_glb('/tmp/model.glb') == []
    assert len(calls) == 1
    assert calls[0].get('export_materials') != 'NONE'


def test_material_failure_falls_back_to_geometry_and_says_so():
    # Blender 自带的 glTF 导出器会在某些材质上抛 AssertionError(io/com/gltf2_io.py 的
    # from_union:候选序列化器全失败就 assert False)。那不是我们能修的,但它不该变成一句 502。
    calls = []

    def export(**options):
        calls.append(options)
        if options.get('export_materials') != 'NONE':
            raise AssertionError('Python: ...\nAssertionError')

    module = load(export)
    warnings = module.export_glb('/tmp/model.glb')

    assert len(calls) == 2
    assert calls[1]['export_materials'] == 'NONE' and calls[1]['export_extras'] is False
    assert len(warnings) == 1 and '只导出几何体' in warnings[0]


def test_a_failure_that_survives_the_fallback_still_raises():
    # 降级是给"材质导不出去"准备的。连几何体都导不出来时不能假装成功 ——
    # 那样上层拿到的是一个空文件,报错会挪到很远的地方。
    module = load(lambda **options: (_ for _ in ()).throw(RuntimeError('disk full')))
    with pytest.raises(RuntimeError):
        module.export_glb('/tmp/model.glb')
