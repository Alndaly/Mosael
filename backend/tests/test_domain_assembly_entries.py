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


def test_jobs_orm_slice_is_reexported_and_registered() -> None:
    from app.db import models
    from app.db.model_slices.jobs import Job, TaskEvent

    assert models.Job is Job
    assert models.TaskEvent is TaskEvent
    assert Job.__table__ is models.Base.metadata.tables["jobs"]
    assert TaskEvent.__table__ is models.Base.metadata.tables["task_events"]


def test_jobs_schema_slice_is_reexported() -> None:
    from app.api import schemas
    from app.api.schemas.jobs import JobOut, TaskEventOut

    assert schemas.JobOut is JobOut
    assert schemas.TaskEventOut is TaskEventOut


def test_notifications_orm_slice_is_reexported_and_registered() -> None:
    from app.db import models
    from app.db.model_slices.notifications import Notification

    assert models.Notification is Notification
    assert Notification.__table__ is models.Base.metadata.tables["notifications"]


def test_notifications_schema_slice_is_reexported() -> None:
    from app.api import schemas
    from app.api.schemas.notifications import NotificationListOut, NotificationOut

    assert schemas.NotificationOut is NotificationOut
    assert schemas.NotificationListOut is NotificationListOut


def test_scheduler_orm_slice_is_reexported_and_registered() -> None:
    from app.db import models
    from app.db.model_slices.scheduler import ScheduledTask, ScheduledTaskRun

    assert models.ScheduledTask is ScheduledTask
    assert models.ScheduledTaskRun is ScheduledTaskRun
    assert ScheduledTask.__table__ is models.Base.metadata.tables["scheduled_tasks"]
    assert ScheduledTaskRun.__table__ is models.Base.metadata.tables["scheduled_task_runs"]


def test_scheduler_schema_slice_is_reexported() -> None:
    from app.api import schemas
    from app.api.schemas.scheduler import RunScheduledTaskResponse, ScheduledTaskOut

    assert schemas.ScheduledTaskOut is ScheduledTaskOut
    assert schemas.RunScheduledTaskResponse is RunScheduledTaskResponse


def test_workflows_orm_slice_is_reexported_and_registered() -> None:
    from app.db import models
    from app.db.model_slices.workflows import Workflow

    assert models.Workflow is Workflow
    assert Workflow.__table__ is models.Base.metadata.tables["workflows"]


def test_workflows_schema_slice_is_reexported() -> None:
    from app.api import schemas
    from app.api.schemas.workflows import WorkflowNodeTypeOut, WorkflowOut

    assert schemas.WorkflowOut is WorkflowOut
    assert schemas.WorkflowNodeTypeOut is WorkflowNodeTypeOut
