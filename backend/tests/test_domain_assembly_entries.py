"""Domain slices stay implementation details behind the three stable assembly entries."""


def test_publish_orm_slice_is_reexported_and_registered() -> None:
    from app.db import models
    from app.db.model_slices.publish import PublishAccount, PublishTask

    assert models.PublishAccount is PublishAccount
    assert models.PublishTask is PublishTask
    assert PublishAccount.__table__ is models.Base.metadata.tables["publish_accounts"]
    assert PublishTask.__table__ is models.Base.metadata.tables["publish_tasks"]


def test_publish_schema_slice_is_reexported() -> None:
    from app.api import schemas
    from app.api.schemas.publish import PublishAccountOut, PublishCreate

    assert schemas.PublishAccountOut is PublishAccountOut
    assert schemas.PublishCreate is PublishCreate


def test_browser_orm_slice_is_reexported_and_registered() -> None:
    from app.db import models
    from app.db.model_slices.browser import BrowserAction, BrowserProfile, BrowserSession

    assert models.BrowserProfile is BrowserProfile
    assert models.BrowserSession is BrowserSession
    assert models.BrowserAction is BrowserAction
    assert BrowserProfile.__table__ is models.Base.metadata.tables["browser_profiles"]
    assert BrowserSession.__table__ is models.Base.metadata.tables["browser_sessions"]
    assert BrowserAction.__table__ is models.Base.metadata.tables["browser_actions"]


def test_browser_schema_slice_is_reexported() -> None:
    from app.api import schemas
    from app.api.schemas.browser import BrowserProfileCreate, BrowserProfileOut

    assert schemas.BrowserProfileOut is BrowserProfileOut
    assert schemas.BrowserProfileCreate is BrowserProfileCreate
