"""一次生成可能出**多份**产出,而链路上每一处都只放得下一个。

图像接口的 `n`(界面上的「4×」)选了几就出几张,计费也按几张记。但产出此前一路被收成单数:
provider 只读 data[0]、GenerationResult 只有一个 output_path、runner 只登记一份、回执只填
一个 asset_id。于是用户选 4 张、按 4 张付钱,拿回来一张 —— 而且**没有任何地方会报错**,
界面上就是安安静静地少了三张。

这些用例钉住那条链子上的每一环。
"""

from __future__ import annotations

from app.ai.providers.openai.image import extract_image_bytes
from app.ai.providers.alibaba.image import extract_result_urls
from tests.util import fresh_client


def test_契约本身是一串不是一个() -> None:
    """GenerationResult 只认列表 —— 留一条单数的路,就还会有人从那条路上把其余的丢掉。"""
    import inspect

    from app.ai.providers.contracts.generation import GenerationResult

    fields = inspect.get_annotations(GenerationResult)
    assert "output_paths" in fields, "产出退回了单数"
    assert "output_path" not in fields, "又开了一条单数的路"


def test_两家出多张的供应商都把每一张取回来() -> None:
    assert extract_image_bytes({"data": [{"b64_json": "aGk="}, {"b64_json": "eW8="}]}) == [b"hi", b"yo"]
    assert extract_result_urls(
        {"output": {"task_status": "SUCCEEDED", "results": [{"url": "https://x/1.png"}, {"url": "https://x/2.png"}]}}
    ) == ["https://x/1.png", "https://x/2.png"]


def test_列表接口吐出全部产出而不只是封面() -> None:
    """界面照 result_asset_ids 出图。只给封面的话,另外三张在库里躺着而用户不知道。"""
    from app.core.db import SessionLocal
    from app.db.models import Asset, GeneratedAsset, GenerationJob, Job, new_id

    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()["id"]

    db = SessionLocal()
    # GenerationJob.job_id 是指向 jobs 的外键 —— 真建一条,别拿一个不存在的 id 糊弄。
    db.add(Job(id="job-multi", workspace_id=ws, kind="generation", status="succeeded"))
    db.commit()
    assets = []
    for name in ("a", "b", "c"):
        asset = Asset(id=new_id(), workspace_id=ws, kind="image", source="generated", name=name)
        db.add(asset)
        assets.append(asset)
    db.commit()
    generation = GenerationJob(
        id=new_id(),
        workspace_id=ws,
        job_id="job-multi",
        provider="openai",
        model="gpt-image-2",
        kind="image",
        request={"prompt": "p"},
        result_asset_id=assets[0].id,
    )
    db.add(generation)
    for asset in assets:
        db.add(GeneratedAsset(asset_id=asset.id, provider="openai", model="m", job_id="job-multi"))
    db.commit()
    db.close()

    listed = client.get("/api/generation/jobs", params={"workspace_id": ws}).json()
    mine = next(one for one in listed if one["id"] == generation.id)
    assert mine["result_asset_ids"] == [a.id for a in assets], f"没把全部产出吐出来:{mine['result_asset_ids']}"
    # 封面仍然排第一 —— 界面上那一格显示的就是它。
    assert mine["result_asset_ids"][0] == mine["result_asset_id"]
