"""资产库(ADR 0027):人物、场景、道具、姿势、服装,参考库。

从仓库根的 mcp_server.py 按工具族拆出来(架构体检第 8 条)。登记、调用身份、领域用例的调用方式见 ./registry。
"""

from __future__ import annotations

from pydantic import Field
from typing import Annotated
from typing import Any

from app.agent_tools.registry import confirmation_reply, default_workspace_id, open_card, REQUESTED_BY, tool, use_case
from app.api.schemas import EntityCreate, EntityOut, EntityReferenceAdd, EntitySummaryOut
from app.domain import reference_library
from app.domain.entities import projections, use_cases as entities_use_cases
from app.domain.voices import engine_catalog

@tool(effect="reads")
def list_entities(kind: str = "", query: str = "", tag: str = "", workspace_id: str = "") -> list[dict[str, Any]]:
    """Read-only: list the asset library — the named CHARACTERS, LOCATIONS and PROPS of this workspace,
    plus POSES and COSTUMES (references any character can use: a body pose, an outfit).

    An asset ("资产") is a named thing with reference images, not a file: "张三" with his
    front / side / turnaround images, a prompt descriptor and (for characters) a voice. Media
    files ("素材") are what list_assets returns. kind is "character", "location", "prop", "pose" or
    "costume" (empty = all); query matches name, description and prompt descriptor; tag filters by tag.
    Variants (张三 · 冬装) are listed under their parent — read get_entity for them.

    To use one in a generation, pass its id in entity_ids of generate_image / generate_video
    instead of picking reference images yourself.
    """

    workspace_id = workspace_id or default_workspace_id()

    def listing(db, user) -> list[dict[str, Any]]:
        rows = entities_use_cases.list_entities(db, user, workspace_id, kind=kind, tag=tag, query=query)
        return projections.summaries(db, rows)

    return use_case(listing, out=EntitySummaryOut)


@tool(effect="reads")
def get_entity(entity_id: str) -> dict[str, Any]:
    """Read-only: one asset from the asset library — its description, prompt descriptor, reference
    images (each with its angle: front / side / back / turnaround / closeup / full_body / expression /
    three_quarter / high_angle / low_angle / concept / detail), cover, per-kind attributes (a character's
    voice_id, blockout color, whether it is a real person and the consent declared; a location's 3D scene
    and time of day; a prop's 3D model; a pose's posture and number of people) and its variants."""

    return use_case(lambda db, user: projections.detail(db, entities_use_cases.entity(db, user, entity_id)), out=EntityOut)


@tool(effect="writes")
def create_entity(
    kind: str,
    name: str,
    description: str = "",
    prompt: str = "",
    tags: list[str] | None = None,
    parent_id: str = "",
    workspace_id: str = "",
) -> dict[str, Any]:
    """Create a character, location, prop, pose or costume in the asset library (a workspace edit, no confirmation).

    kind: "character" / "location" / "prop" / "pose" / "costume". A pose's prompt describes the body pose
    only (no looks or clothing); a costume's prompt describes each piece. description is for people; prompt is the
    descriptor models read (appearance, clothing, materials) and is appended whenever the asset
    is mentioned in a generation. parent_id makes it a VARIANT of an existing asset (张三 · 冬装):
    a variant inherits the parent's prompt descriptor — write only what differs.
    Add reference images afterwards with attach_entity_reference. Real-person consent is declared
    by the user in the app, never by you.
    """
    body: dict[str, Any] = {
        "workspace_id": workspace_id or default_workspace_id(),
        "kind": kind,
        "name": name,
        "description": description,
        "prompt": prompt,
        "tags": tags or [],
    }
    if parent_id:
        body["parent_id"] = parent_id

    request = EntityCreate(**body)
    fields = request.model_dump(exclude={"workspace_id"})
    return use_case(
        lambda db, user: projections.detail(db, entities_use_cases.create(db, user, request.workspace_id, **fields)), out=EntityOut
    )


@tool(effect="writes")
def set_entity_voice(entity_id: str, engine: str, voice: str) -> dict[str, Any]:
    """Give a CHARACTER in the asset library its voice (a workspace edit, no confirmation). engine and voice come from
    list_speech_engines (e.g. "builtin:edge" + "zh-CN-XiaoyiNeural"). Workflows then speak that character's lines in it
    (Topic to finished video voices each line by its speaker). Empty voice clears it."""

    def apply(db, user) -> dict[str, Any]:
        entity = entities_use_cases.entity(db, user, entity_id)
        if entity.kind != "character":
            raise ValueError(f"{entity.name} is a {entity.kind}; only characters have a voice")
        attributes = {key: value for key, value in (entity.attributes or {}).items() if key != "voice"}
        if voice.strip():
            choice = engine_catalog.voice_choice(db, engine=engine, voice=voice, user_id=user.id)
            attributes["voice"] = choice.to_json()
        return projections.detail(db, entities_use_cases.update(db, user, entity_id, attributes=attributes))

    return use_case(apply, out=EntityOut)


@tool(effect="writes")
def attach_entity_reference(entity_id: str, asset_id: str, role: str = "", cover: bool = False) -> dict[str, Any]:
    """Attach an existing image (or video) asset to an asset-library entry as a reference image
    (a workspace edit, no confirmation). The media file is referenced, not copied.

    role is the angle / purpose: front, side, back, turnaround, closeup, full_body, expression,
    concept or detail; poses use camera angles (front, three_quarter, side, back, high_angle, low_angle,
    detail) and costumes front, back, side, detail or concept (empty = front, concept for locations). Attaching
    the same asset again changes its role. cover=true also makes it the cover image.
    """

    request = EntityReferenceAdd(asset_id=asset_id, role=role, cover=cover)
    return use_case(
        lambda db, user: projections.detail(
            db, entities_use_cases.add_reference(db, user, entity_id, request.asset_id, request.role, cover=request.cover)
        ),
        out=EntityOut,
    )


@tool(effect="reads", needs="reference_library")
def search_references(
    query: Annotated[str, Field(description="Keywords; Chinese, English and Japanese names, ids and tags all match.")] = "",
    kind: Annotated[str, Field(description='"pose" or "costume" (empty = both).')] = "",
    connection_id: Annotated[str, Field(description="One reference library connection (empty = all of yours).")] = "",
    limit: Annotated[int, Field(description="At most this many entries per collection (1-40).")] = 12,
) -> dict[str, Any]:
    """Read-only: search the user's external REFERENCE LIBRARIES (read-only atlases from plugins, such as
    PoseAtlas: multi-angle mannequin poses and outfits without a person). Nothing is downloaded.

    Each entry: connection_id, collection, id, kind (pose / costume), name, tags, the camera angles it has,
    a thumbnail URL and its provenance (author, source, license). Entries flagged as adult content are never
    returned. To use one, call use_reference with its connection_id, collection and id — the user approves
    taking it into the workspace; with save_as_asset it becomes a pose / costume asset you can pass in
    entity_ids of a generation (a pose goes to the model as a pose reference: body pose only, not style).
    """

    return use_case(lambda db, user: reference_library.search_everywhere(
        db, user.id, query=query, kind=kind, connection_id=connection_id, limit=limit,
    ))


@tool(effect="confirms", needs="reference_library")
def use_reference(
    connection_id: Annotated[str, Field(description="connection_id from search_references.")],
    item_id: Annotated[str, Field(description="id from search_references.")],
    collection: Annotated[str, Field(description="collection from search_references.")] = "",
    save_as_asset: Annotated[bool, Field(description="Also create a pose / costume asset from it (to @ in generations).")] = True,
    angle: Annotated[str, Field(description="Without save_as_asset: which view to take (one of the entry's angles from search_references); empty = the first.")] = "",
    workspace_id: str = "",
) -> dict[str, Any]:
    """Confirmation required: take ONE entry from a reference library into this workspace,
    with its provenance recorded. save_as_asset takes EVERY view and creates a pose / costume asset with
    each view attached by its angle (a pose is matched to a shot by angle, so one view is not enough);
    without it, only the view named by angle is taken as media.

    Taking an item is always initiated by the user: this opens a card they approve. Search first with
    search_references; never guess ids. The result (after approval) has asset_id and entity_id.
    """
    confirmation = open_card(
        {
            "workspace_id": workspace_id or default_workspace_id(),
            "tool": "use_reference",
            "requested_by": REQUESTED_BY.get(),
            "payload": {"connection_id": connection_id, "item_id": item_id, "collection": collection,
                        "save_as_asset": bool(save_as_asset), **({"angle": angle} if angle and not save_as_asset else {})},
        },
    )
    return confirmation_reply(confirmation)
