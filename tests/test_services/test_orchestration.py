"""
Tests for orchestration service.
"""

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from unittest.mock import Mock, patch

from foundry_sdk.v2.core.models import Duration
from foundry_sdk.v2.orchestration.models import (
    Action,
    AffectedResourcesResponse,
    AndTrigger,
    Build,
    ConnectingTarget,
    DatasetUpdatedTrigger,
    DatasetJobOutput,
    Job,
    ManualTarget,
    ManualTrigger,
    OrTrigger,
    ProjectScope,
    Schedule,
    ScheduleRun,
    ScheduleRunError,
    ScheduleRunIgnored,
    ScheduleRunSubmitted,
    ScheduleSucceededTrigger,
    TransactionalMediaSetJobOutput,
    UpstreamTarget,
    UserScope,
)

from pltr.services.dependency import (
    AnalysisContext,
    DependencyGraphService,
    DependencyTarget,
)
from pltr.services.orchestration import OrchestrationService
from pltr.utils.pagination import PaginationConfig


@pytest.fixture
def mock_orchestration_service():
    """Create a mocked OrchestrationService."""
    with patch("pltr.services.base.AuthManager") as mock_auth:
        # Set up client mock
        mock_client = Mock()
        mock_orchestration = Mock()

        # Mock the Build, Job, and Schedule classes
        mock_build_class = Mock()
        mock_job_class = Mock()
        mock_schedule_class = Mock()

        mock_orchestration.Build = mock_build_class
        mock_orchestration.Job = mock_job_class
        mock_orchestration.Schedule = mock_schedule_class

        mock_client.orchestration = mock_orchestration
        mock_auth.return_value.get_client.return_value = mock_client

        # Create service
        service = OrchestrationService()
        return service, mock_build_class, mock_job_class, mock_schedule_class


ACTOR_ID = "00000000-0000-0000-0000-000000000001"
SCHEDULE_RID = "ri.orchestration.main.schedule.test-schedule"
SCHEDULE_VERSION_RID = "ri.orchestration.main.schedule-version.test-version"


def pinned_action(target):
    return Action(
        target=target,
        branchName="feature",
        fallbackBranches=[],
        forceBuild=True,
        abortOnFailure=True,
        notificationsEnabled=False,
    )


def pinned_schedule(target, *, trigger=None, scope=None):
    now = datetime.now(timezone.utc)
    return Schedule(
        rid=SCHEDULE_RID,
        displayName="Pinned schedule",
        description="SDK-shaped schedule",
        currentVersionRid=SCHEDULE_VERSION_RID,
        createdTime=now,
        createdBy=ACTOR_ID,
        updatedTime=now,
        updatedBy=ACTOR_ID,
        paused=False,
        trigger=trigger or ManualTrigger(),
        action=pinned_action(target),
        scopeMode=scope or UserScope(),
    )


def pinned_run(run_suffix, result):
    return ScheduleRun(
        rid=f"ri.orchestration.main.schedule-run.{run_suffix}",
        scheduleRid=SCHEDULE_RID,
        scheduleVersionRid=SCHEDULE_VERSION_RID,
        createdTime=datetime.now(timezone.utc),
        createdBy=ACTOR_ID,
        result=result,
    )


@pytest.fixture
def sample_build():
    """Create sample build object."""
    build = Mock()
    build.rid = "ri.orchestration.main.build.test-build"
    build.status = "COMPLETED"
    build.created_time = "2024-01-01T00:00:00Z"
    build.started_time = "2024-01-01T00:01:00Z"
    build.finished_time = "2024-01-01T00:10:00Z"
    build.created_by = "user@example.com"
    build.branch_name = "main"
    build.commit_hash = "abc123"
    return build


@pytest.fixture
def sample_job():
    """Create sample job object."""
    job = Mock()
    job.rid = "ri.orchestration.main.job.test-job"
    job.status = "RUNNING"
    job.created_time = "2024-01-01T00:00:00Z"
    job.started_time = "2024-01-01T00:01:00Z"
    job.finished_time = None
    job.job_type = "TRANSFORM"
    job.build_rid = "ri.orchestration.main.build.test-build"
    return job


@pytest.fixture
def sample_schedule():
    """Create sample schedule object."""
    schedule = Mock()
    schedule.rid = "ri.orchestration.main.schedule.test-schedule"
    schedule.display_name = "Test Schedule"
    schedule.description = "Test schedule description"
    schedule.paused = False
    schedule.created_time = "2024-01-01T00:00:00Z"
    schedule.created_by = "user@example.com"
    schedule.modified_time = "2024-01-02T00:00:00Z"
    schedule.modified_by = "user@example.com"
    schedule.trigger = Mock()
    schedule.action = Mock()
    return schedule


def test_orchestration_service_initialization():
    """Test OrchestrationService initialization."""
    with patch("pltr.services.base.AuthManager"):
        service = OrchestrationService()
        assert service is not None


def test_orchestration_service_get_service(mock_orchestration_service):
    """Test getting the underlying orchestration service."""
    service, mock_build, mock_job, mock_schedule = mock_orchestration_service
    orchestration = service._get_service()
    assert orchestration.Build == mock_build
    assert orchestration.Job == mock_job
    assert orchestration.Schedule == mock_schedule


# Build tests
def test_get_build_success(mock_orchestration_service, sample_build):
    """Test successful build retrieval."""
    service, mock_build_class, _, _ = mock_orchestration_service

    mock_build_class.get.return_value = sample_build

    result = service.get_build("ri.orchestration.main.build.test-build")

    assert result["rid"] == "ri.orchestration.main.build.test-build"
    assert result["status"] == "COMPLETED"
    assert result["created_by"] == "user@example.com"
    assert result["branch_name"] == "main"
    mock_build_class.get.assert_called_once_with(
        "ri.orchestration.main.build.test-build"
    )


def test_get_build_error(mock_orchestration_service):
    """Test build retrieval with error."""
    service, mock_build_class, _, _ = mock_orchestration_service

    mock_build_class.get.side_effect = Exception("API Error")

    with pytest.raises(RuntimeError) as exc_info:
        service.get_build("ri.orchestration.main.build.test-build")

    assert "Failed to get build" in str(exc_info.value)


def test_create_build_success(mock_orchestration_service, sample_build):
    """Test successful build creation."""
    service, mock_build_class, _, _ = mock_orchestration_service

    mock_build_class.create.return_value = sample_build

    target = {"dataset_rid": "ri.foundry.main.dataset.test"}
    result = service.create_build(
        target=target, branch_name="feature-branch", force_build=True
    )

    assert result["rid"] == "ri.orchestration.main.build.test-build"
    assert result["status"] == "COMPLETED"

    # Check that create was called with correct arguments
    call_args = mock_build_class.create.call_args[1]
    assert call_args["target"] == target
    assert call_args["branch_name"] == "feature-branch"
    assert call_args["force_build"] is True


def test_cancel_build_success(mock_orchestration_service):
    """Test successful build cancellation."""
    service, mock_build_class, _, _ = mock_orchestration_service

    service.cancel_build("ri.orchestration.main.build.test-build")

    mock_build_class.cancel.assert_called_once_with(
        "ri.orchestration.main.build.test-build"
    )


def test_get_build_jobs_success(mock_orchestration_service, sample_job):
    """Test successful retrieval of build jobs."""
    service, mock_build_class, _, _ = mock_orchestration_service

    # Mock response with jobs
    mock_response = Mock()
    mock_response.data = [sample_job]
    mock_response.next_page_token = "next-token"
    mock_build_class.jobs.return_value = mock_response

    result = service.get_build_jobs(
        "ri.orchestration.main.build.test-build", page_size=10
    )

    assert len(result["jobs"]) == 1
    assert result["jobs"][0]["rid"] == "ri.orchestration.main.job.test-job"
    assert result["next_page_token"] == "next-token"

    mock_build_class.jobs.assert_called_once()


def test_search_builds_success(mock_orchestration_service, sample_build):
    """Test successful build search."""
    service, mock_build_class, _, _ = mock_orchestration_service

    # Mock response with builds
    mock_response = Mock()
    mock_response.data = [sample_build]
    mock_response.next_page_token = "next-token"
    mock_build_class.search.return_value = mock_response

    result = service.search_builds(page_size=10)

    assert len(result["builds"]) == 1
    assert result["builds"][0]["rid"] == "ri.orchestration.main.build.test-build"
    assert result["next_page_token"] == "next-token"
    mock_build_class.search.assert_called_once_with(page_size=10, preview=True)


def test_search_builds_paginated_uses_preview(mock_orchestration_service, sample_build):
    """Test paginated build search enables preview mode."""
    service, mock_build_class, _, _ = mock_orchestration_service

    mock_response = Mock()
    mock_response.data = [sample_build]
    mock_response.next_page_token = None
    mock_build_class.search.return_value = mock_response

    config = PaginationConfig(page_size=10, max_pages=1)
    result = service.search_builds_paginated(config)

    assert len(result.data) == 1
    assert result.data[0]["rid"] == "ri.orchestration.main.build.test-build"
    mock_build_class.search.assert_called_once_with(page_size=10, preview=True)


def test_search_builds_paginated_collects_multiple_pages(
    mock_orchestration_service, sample_build
):
    """Test paginated build search collects builds across multiple pages."""
    service, mock_build_class, _, _ = mock_orchestration_service

    page_one = Mock()
    build_one = Mock()
    build_one.rid = "ri.orchestration.main.build.page-1"
    page_one.data = [build_one]
    page_one.next_page_token = "token-2"

    page_two = Mock()
    build_two = Mock()
    build_two.rid = "ri.orchestration.main.build.page-2"
    page_two.data = [build_two]
    page_two.next_page_token = None

    mock_build_class.search.side_effect = [page_one, page_two]

    config = PaginationConfig(page_size=10, max_pages=2)
    result = service.search_builds_paginated(config)

    assert len(result.data) == 2
    assert result.data[0]["rid"] == "ri.orchestration.main.build.page-1"
    assert result.data[1]["rid"] == "ri.orchestration.main.build.page-2"
    assert mock_build_class.search.call_count == 2
    assert mock_build_class.search.call_args_list[0].kwargs == {
        "page_size": 10,
        "preview": True,
    }
    assert mock_build_class.search.call_args_list[1].kwargs == {
        "page_size": 10,
        "preview": True,
        "page_token": "token-2",
    }


def test_search_builds_falls_back_when_preview_kwarg_unsupported(
    mock_orchestration_service, sample_build
):
    """Test build search retries without preview when call-level preview is unsupported."""
    service, mock_build_class, _, _ = mock_orchestration_service

    mock_response = Mock()
    mock_response.data = [sample_build]
    mock_response.next_page_token = None
    mock_build_class.search.side_effect = [
        TypeError("unexpected keyword argument 'preview'"),
        mock_response,
    ]

    result = service.search_builds(page_size=10)

    assert len(result["builds"]) == 1
    assert mock_build_class.search.call_count == 2
    assert mock_build_class.search.call_args_list[0].kwargs == {
        "page_size": 10,
        "preview": True,
    }
    assert mock_build_class.search.call_args_list[1].kwargs == {"page_size": 10}


def test_search_builds_reraises_unrelated_type_error(mock_orchestration_service):
    """Test build search does not swallow unrelated TypeError failures."""
    service, mock_build_class, _, _ = mock_orchestration_service

    mock_build_class.search.side_effect = TypeError("invalid request body")

    with pytest.raises(
        RuntimeError, match="Failed to search builds: invalid request body"
    ):
        service.search_builds(page_size=10)

    assert mock_build_class.search.call_count == 1


def test_get_builds_batch_success(mock_orchestration_service, sample_build):
    """Test successful batch build retrieval."""
    service, mock_build_class, _, _ = mock_orchestration_service

    # Mock batch response
    mock_response = Mock()
    mock_item = Mock()
    mock_item.data = sample_build
    mock_response.data = [mock_item]
    mock_build_class.get_batch.return_value = mock_response

    build_rids = ["rid1", "rid2"]
    result = service.get_builds_batch(build_rids)

    assert len(result["builds"]) == 1
    assert result["builds"][0]["rid"] == "ri.orchestration.main.build.test-build"

    # Check that batch request was formatted correctly
    call_args = mock_build_class.get_batch.call_args[0][0]
    assert len(call_args) == 2
    assert call_args[0]["rid"] == "rid1"
    assert call_args[1]["rid"] == "rid2"


def test_get_builds_batch_too_many(mock_orchestration_service):
    """Test batch build retrieval with too many builds."""
    service, _, _, _ = mock_orchestration_service

    build_rids = ["rid" + str(i) for i in range(101)]  # 101 builds

    with pytest.raises(ValueError) as exc_info:
        service.get_builds_batch(build_rids)

    assert "Maximum batch size is 100" in str(exc_info.value)


def test_get_builds_batch_error(mock_orchestration_service):
    """Test batch build retrieval with error."""
    service, mock_build_class, _, _ = mock_orchestration_service

    mock_build_class.get_batch.side_effect = Exception("API Error")

    with pytest.raises(RuntimeError) as exc_info:
        service.get_builds_batch(["rid1", "rid2"])

    assert "Failed to get builds batch" in str(exc_info.value)


# Job tests
def test_get_job_success(mock_orchestration_service, sample_job):
    """Test successful job retrieval."""
    service, _, mock_job_class, _ = mock_orchestration_service

    mock_job_class.get.return_value = sample_job

    result = service.get_job("ri.orchestration.main.job.test-job")

    assert result["rid"] == "ri.orchestration.main.job.test-job"
    assert result["status"] == "RUNNING"
    assert result["job_type"] == "TRANSFORM"
    mock_job_class.get.assert_called_once_with("ri.orchestration.main.job.test-job")


def test_get_job_error(mock_orchestration_service):
    """Test job retrieval with error."""
    service, _, mock_job_class, _ = mock_orchestration_service

    mock_job_class.get.side_effect = Exception("API Error")

    with pytest.raises(RuntimeError) as exc_info:
        service.get_job("ri.orchestration.main.job.test-job")

    assert "Failed to get job" in str(exc_info.value)


def test_get_jobs_batch_success(mock_orchestration_service, sample_job):
    """Test successful batch job retrieval."""
    service, _, mock_job_class, _ = mock_orchestration_service

    # Mock batch response
    mock_response = Mock()
    mock_item = Mock()
    mock_item.data = sample_job
    mock_response.data = [mock_item]
    mock_job_class.get_batch.return_value = mock_response

    job_rids = ["rid1", "rid2"]
    result = service.get_jobs_batch(job_rids)

    assert len(result["jobs"]) == 1
    assert result["jobs"][0]["rid"] == "ri.orchestration.main.job.test-job"

    # Check that batch request was formatted correctly
    call_args = mock_job_class.get_batch.call_args[0][0]
    assert len(call_args) == 2
    assert call_args[0]["rid"] == "rid1"
    assert call_args[1]["rid"] == "rid2"


def test_get_jobs_batch_too_many(mock_orchestration_service):
    """Test batch job retrieval with too many jobs."""
    service, _, _, _ = mock_orchestration_service

    job_rids = ["rid" + str(i) for i in range(501)]  # 501 jobs

    with pytest.raises(RuntimeError) as exc_info:
        service.get_jobs_batch(job_rids)

    assert "Maximum batch size is 500" in str(exc_info.value)


# Schedule tests
def test_get_schedule_success(mock_orchestration_service, sample_schedule):
    """Test successful schedule retrieval."""
    service, _, _, mock_schedule_class = mock_orchestration_service

    mock_schedule_class.get.return_value = sample_schedule

    result = service.get_schedule("ri.orchestration.main.schedule.test-schedule")

    assert result["rid"] == "ri.orchestration.main.schedule.test-schedule"
    assert result["display_name"] == "Test Schedule"
    assert result["paused"] is False
    mock_schedule_class.get.assert_called_once()


def test_get_schedule_with_preview(mock_orchestration_service, sample_schedule):
    """Test schedule retrieval with preview mode."""
    service, _, _, mock_schedule_class = mock_orchestration_service

    mock_schedule_class.get.return_value = sample_schedule

    result = service.get_schedule(
        "ri.orchestration.main.schedule.test-schedule", preview=True
    )

    assert result["rid"] == "ri.orchestration.main.schedule.test-schedule"

    # Check preview parameter was passed
    call_args = mock_schedule_class.get.call_args[1]
    assert call_args["preview"] is True


def test_create_schedule_success(mock_orchestration_service, sample_schedule):
    """Test successful schedule creation."""
    service, _, _, mock_schedule_class = mock_orchestration_service

    mock_schedule_class.create.return_value = sample_schedule

    action = {"type": "BUILD", "target": "dataset-rid"}
    trigger = {"type": "CRON", "expression": "0 0 * * *"}

    result = service.create_schedule(
        action=action,
        display_name="Test Schedule",
        description="Test description",
        trigger=trigger,
    )

    assert result["rid"] == "ri.orchestration.main.schedule.test-schedule"
    assert result["display_name"] == "Test Schedule"

    # Check create parameters
    call_args = mock_schedule_class.create.call_args[1]
    assert call_args["action"] == action
    assert call_args["display_name"] == "Test Schedule"
    assert call_args["trigger"] == trigger


def test_delete_schedule_success(mock_orchestration_service):
    """Test successful schedule deletion."""
    service, _, _, mock_schedule_class = mock_orchestration_service

    service.delete_schedule("ri.orchestration.main.schedule.test-schedule")

    mock_schedule_class.delete.assert_called_once_with(
        "ri.orchestration.main.schedule.test-schedule"
    )


def test_pause_schedule_success(mock_orchestration_service):
    """Test successful schedule pausing."""
    service, _, _, mock_schedule_class = mock_orchestration_service

    service.pause_schedule("ri.orchestration.main.schedule.test-schedule")

    mock_schedule_class.pause.assert_called_once_with(
        "ri.orchestration.main.schedule.test-schedule"
    )


def test_unpause_schedule_success(mock_orchestration_service):
    """Test successful schedule unpausing."""
    service, _, _, mock_schedule_class = mock_orchestration_service

    service.unpause_schedule("ri.orchestration.main.schedule.test-schedule")

    mock_schedule_class.unpause.assert_called_once_with(
        "ri.orchestration.main.schedule.test-schedule"
    )


def test_run_schedule_success(mock_orchestration_service):
    """Test successful schedule execution."""
    service, _, _, mock_schedule_class = mock_orchestration_service

    service.run_schedule("ri.orchestration.main.schedule.test-schedule")

    mock_schedule_class.run.assert_called_once_with(
        "ri.orchestration.main.schedule.test-schedule"
    )


def test_replace_schedule_success(mock_orchestration_service, sample_schedule):
    """Test successful schedule replacement."""
    service, _, _, mock_schedule_class = mock_orchestration_service

    mock_schedule_class.replace.return_value = sample_schedule

    action = {"type": "BUILD", "target": "new-dataset-rid"}

    result = service.replace_schedule(
        schedule_rid="ri.orchestration.main.schedule.test-schedule",
        action=action,
        display_name="Updated Schedule",
    )

    assert result["rid"] == "ri.orchestration.main.schedule.test-schedule"

    # Check replace parameters
    call_args = mock_schedule_class.replace.call_args[1]
    assert call_args["schedule_rid"] == "ri.orchestration.main.schedule.test-schedule"
    assert call_args["action"] == action
    assert call_args["display_name"] == "Updated Schedule"


@pytest.fixture
def sample_run():
    """Create sample schedule run object."""
    run = Mock()
    run.rid = "ri.orchestration.main.run.test-run"
    run.schedule_rid = "ri.orchestration.main.schedule.test-schedule"
    run.status = "COMPLETED"
    run.created_time = "2024-01-01T00:00:00Z"
    run.started_time = "2024-01-01T00:01:00Z"
    run.finished_time = "2024-01-01T00:10:00Z"
    run.build_rid = "ri.orchestration.main.build.test-build"
    run.result = "SUCCESS"
    return run


def test_get_schedule_runs_success(mock_orchestration_service, sample_run):
    """Test successful schedule runs retrieval."""
    service, _, _, mock_schedule_class = mock_orchestration_service

    # Mock response with runs
    mock_response = Mock()
    mock_response.data = [sample_run]
    mock_response.next_page_token = "next-token"
    mock_schedule_class.runs.return_value = mock_response

    result = service.get_schedule_runs(
        "ri.orchestration.main.schedule.test-schedule", page_size=10
    )

    assert len(result["runs"]) == 1
    assert result["runs"][0]["rid"] == "ri.orchestration.main.run.test-run"
    assert result["runs"][0]["status"] == "COMPLETED"
    assert result["next_page_token"] == "next-token"

    mock_schedule_class.runs.assert_called_once()


def test_get_schedule_runs_with_pagination(mock_orchestration_service, sample_run):
    """Test schedule runs retrieval with pagination parameters."""
    service, _, _, mock_schedule_class = mock_orchestration_service

    mock_response = Mock()
    mock_response.data = [sample_run]
    mock_response.next_page_token = None
    mock_schedule_class.runs.return_value = mock_response

    result = service.get_schedule_runs(
        "ri.orchestration.main.schedule.test-schedule",
        page_size=20,
        page_token="prev-token",
    )

    assert len(result["runs"]) == 1

    # Check pagination parameters were passed
    call_args = mock_schedule_class.runs.call_args[1]
    assert call_args["page_size"] == 20
    assert call_args["page_token"] == "prev-token"


def test_get_schedule_runs_error(mock_orchestration_service):
    """Test schedule runs retrieval with error."""
    service, _, _, mock_schedule_class = mock_orchestration_service

    mock_schedule_class.runs.side_effect = Exception("API Error")

    with pytest.raises(RuntimeError) as exc_info:
        service.get_schedule_runs("ri.orchestration.main.schedule.test-schedule")

    assert "Failed to get runs for schedule" in str(exc_info.value)


def test_format_run_info(mock_orchestration_service, sample_run):
    """Test run info formatting."""
    service, _, _, _ = mock_orchestration_service

    result = service._format_run_info(sample_run)

    assert result["rid"] == "ri.orchestration.main.run.test-run"
    assert result["schedule_rid"] == "ri.orchestration.main.schedule.test-schedule"
    assert result["status"] == "COMPLETED"
    assert result["build_rid"] == "ri.orchestration.main.build.test-build"
    assert result["result"] == "SUCCESS"


# Formatting method tests
def test_format_build_info(mock_orchestration_service, sample_build):
    """Test build info formatting."""
    service, _, _, _ = mock_orchestration_service

    result = service._format_build_info(sample_build)

    assert result["rid"] == "ri.orchestration.main.build.test-build"
    assert result["status"] == "COMPLETED"
    assert result["created_by"] == "user@example.com"
    assert result["branch_name"] == "main"
    assert result["commit_hash"] == "abc123"


def test_format_job_info(mock_orchestration_service, sample_job):
    """Test job info formatting."""
    service, _, _, _ = mock_orchestration_service

    result = service._format_job_info(sample_job)

    assert result["rid"] == "ri.orchestration.main.job.test-job"
    assert result["status"] == "RUNNING"
    assert result["job_type"] == "TRANSFORM"
    assert result["build_rid"] == "ri.orchestration.main.build.test-build"


def test_format_schedule_info(mock_orchestration_service, sample_schedule):
    """Test schedule info formatting."""
    service, _, _, _ = mock_orchestration_service

    result = service._format_schedule_info(sample_schedule)

    assert result["rid"] == "ri.orchestration.main.schedule.test-schedule"
    assert result["display_name"] == "Test Schedule"
    assert result["description"] == "Test schedule description"
    assert result["paused"] is False
    assert "trigger" in result
    assert "action" in result


def test_pinned_build_schema_and_wrapper_never_expose_target(
    mock_orchestration_service,
):
    service, mock_build_class, _, _ = mock_orchestration_service
    expected_fields = {
        "rid",
        "branch_name",
        "created_time",
        "created_by",
        "fallback_branches",
        "job_rids",
        "retry_count",
        "retry_backoff_duration",
        "abort_on_failure",
        "status",
        "finished_time",
        "schedule_rid",
    }
    assert set(Build.model_fields) == expected_fields
    assert "target" not in Build.model_fields

    build = Build(
        rid="ri.orchestration.main.build.test-build",
        branchName="feature",
        createdTime=datetime.now(timezone.utc),
        createdBy="00000000-0000-0000-0000-000000000001",
        fallbackBranches=[],
        jobRids=["ri.orchestration.main.job.test-job"],
        retryCount=0,
        retryBackoffDuration=Duration(value=1, unit="SECONDS"),
        abortOnFailure=True,
        status="SUCCEEDED",
        scheduleRid="ri.orchestration.main.schedule.test-schedule",
    )
    mock_build_class.get.return_value = build

    result = service.get_build(build.rid, request_timeout=19)

    assert result["rid"] == build.rid
    assert result["job_rids"] == ["ri.orchestration.main.job.test-job"]
    assert result["schedule_rid"] == "ri.orchestration.main.schedule.test-schedule"
    assert "target" not in result
    mock_build_class.get.assert_called_once_with(
        build_rid=build.rid, request_timeout=19
    )


def test_pinned_job_outputs_are_preserved_as_declared_discriminated_models(
    mock_orchestration_service,
):
    service, mock_build_class, _, _ = mock_orchestration_service
    dataset_output = DatasetJobOutput(datasetRid="ri.foundry.main.dataset.output")
    media_output = TransactionalMediaSetJobOutput(
        mediaSetRid="ri.mio.main.media-set.output"
    )
    job = Job(
        rid="ri.orchestration.main.job.test-job",
        buildRid="ri.orchestration.main.build.test-build",
        startedTime=datetime.now(timezone.utc),
        jobStatus="SUCCEEDED",
        outputs=[dataset_output, media_output],
    )
    page = Mock(data=[job], next_page_token=None)
    mock_build_class.jobs.return_value = page

    result = service.get_build_jobs(
        "ri.orchestration.main.build.test-build", request_timeout=13
    )

    assert result["jobs"][0]["outputs"] == [
        {
            "dataset_rid": "ri.foundry.main.dataset.output",
            "output_transaction_rid": None,
            "type": "datasetJobOutput",
        },
        {
            "media_set_rid": "ri.mio.main.media-set.output",
            "transaction_id": None,
            "type": "transactionalMediaSetJobOutput",
        },
    ]
    mock_build_class.jobs.assert_called_once_with(
        build_rid="ri.orchestration.main.build.test-build", request_timeout=13
    )


def test_affected_resources_uses_pinned_datasets_field(mock_orchestration_service):
    service, _, _, mock_schedule_class = mock_orchestration_service
    response = AffectedResourcesResponse(datasets=["ri.foundry.main.dataset.output"])
    mock_schedule_class.get_affected_resources.return_value = response

    assert service.get_schedule_affected_resources(
        "ri.orchestration.main.schedule.test-schedule",
        preview=True,
        request_timeout=11,
    ) == {"affected_resources": ["ri.foundry.main.dataset.output"]}
    mock_schedule_class.get_affected_resources.assert_called_once_with(
        schedule_rid="ri.orchestration.main.schedule.test-schedule",
        preview=True,
        request_timeout=11,
    )


@pytest.mark.parametrize(
    ("target", "expected_target", "scope", "expected_scope"),
    [
        (
            ManualTarget(targetRids=["ri.foundry.main.dataset.manual"]),
            {
                "target_rids": ["ri.foundry.main.dataset.manual"],
                "type": "manual",
            },
            UserScope(),
            {"type": "user"},
        ),
        (
            UpstreamTarget(
                targetRids=["ri.foundry.main.dataset.upstream"],
                ignoredRids=["ri.foundry.main.dataset.ignored"],
            ),
            {
                "target_rids": ["ri.foundry.main.dataset.upstream"],
                "ignored_rids": ["ri.foundry.main.dataset.ignored"],
                "type": "upstream",
            },
            ProjectScope(projectRids=["ri.compass.main.folder.project"]),
            {
                "project_rids": ["ri.compass.main.folder.project"],
                "type": "project",
            },
        ),
        (
            ConnectingTarget(
                inputRids=["ri.foundry.main.dataset.input"],
                targetRids=["ri.foundry.main.dataset.output"],
                ignoredRids=["ri.foundry.main.dataset.ignored"],
            ),
            {
                "input_rids": ["ri.foundry.main.dataset.input"],
                "target_rids": ["ri.foundry.main.dataset.output"],
                "ignored_rids": ["ri.foundry.main.dataset.ignored"],
                "type": "connecting",
            },
            UserScope(),
            {"type": "user"},
        ),
    ],
)
def test_pinned_schedule_action_target_and_scope_survive_real_wrapper(
    mock_orchestration_service,
    target,
    expected_target,
    scope,
    expected_scope,
):
    service, _, _, mock_schedule_class = mock_orchestration_service
    mock_schedule_class.get.return_value = pinned_schedule(target, scope=scope)

    result = service.get_schedule(SCHEDULE_RID, preview=True, request_timeout=9)

    assert result["action"] == {
        "target": expected_target,
        "branch_name": "feature",
        "fallback_branches": [],
        "force_build": True,
        "retry_count": None,
        "retry_backoff_duration": None,
        "abort_on_failure": True,
        "notifications_enabled": False,
    }
    assert result["scope_mode"] == expected_scope
    mock_schedule_class.get.assert_called_once_with(
        schedule_rid=SCHEDULE_RID,
        preview=True,
        request_timeout=9,
    )


def test_pinned_recursive_trigger_survives_real_schedule_wrapper(
    mock_orchestration_service,
):
    service, _, _, mock_schedule_class = mock_orchestration_service
    trigger = AndTrigger(
        triggers=[
            DatasetUpdatedTrigger(
                datasetRid="ri.foundry.main.dataset.trigger", branchName="master"
            ),
            OrTrigger(
                triggers=[
                    ScheduleSucceededTrigger(
                        scheduleRid="ri.orchestration.main.schedule.upstream"
                    ),
                    ManualTrigger(),
                ]
            ),
        ]
    )
    mock_schedule_class.get.return_value = pinned_schedule(
        ManualTarget(targetRids=["ri.foundry.main.dataset.output"]),
        trigger=trigger,
    )

    result = service.get_schedule(SCHEDULE_RID)

    assert result["trigger"] == {
        "triggers": [
            {
                "dataset_rid": "ri.foundry.main.dataset.trigger",
                "branch_name": "master",
                "type": "datasetUpdated",
            },
            {
                "triggers": [
                    {
                        "schedule_rid": "ri.orchestration.main.schedule.upstream",
                        "type": "scheduleSucceeded",
                    },
                    {"type": "manual"},
                ],
                "type": "or",
            },
        ],
        "type": "and",
    }


@pytest.mark.parametrize(
    ("result_model", "expected_result"),
    [
        (
            ScheduleRunSubmitted(
                buildRid="ri.orchestration.main.build.submitted-build"
            ),
            {
                "build_rid": "ri.orchestration.main.build.submitted-build",
                "type": "submitted",
            },
        ),
        (ScheduleRunIgnored(), {"type": "ignored"}),
        (
            ScheduleRunError(errorName="INTERNAL", description="failed safely"),
            {
                "error_name": "INTERNAL",
                "description": "failed safely",
                "type": "error",
            },
        ),
        (None, None),
    ],
)
def test_pinned_schedule_run_result_variants_survive_real_wrapper(
    mock_orchestration_service,
    result_model,
    expected_result,
):
    service, _, _, mock_schedule_class = mock_orchestration_service
    run = pinned_run("result-variant", result_model)
    mock_schedule_class.runs.return_value = Mock(data=[run], next_page_token=None)

    response = service.get_schedule_runs(
        SCHEDULE_RID,
        page_size=20,
        page_token="current-page",
        request_timeout=7,
    )

    assert response["runs"][0]["result"] == expected_result
    mock_schedule_class.runs.assert_called_once_with(
        schedule_rid=SCHEDULE_RID,
        page_size=20,
        page_token="current-page",
        request_timeout=7,
    )


def test_pinned_schedule_models_flow_through_wrappers_into_dependency_collector(
    mock_orchestration_service,
):
    orchestration, mock_build_class, _, mock_schedule_class = mock_orchestration_service
    trigger = AndTrigger(
        triggers=[
            DatasetUpdatedTrigger(
                datasetRid="ri.foundry.main.dataset.trigger", branchName="master"
            ),
            OrTrigger(
                triggers=[
                    ScheduleSucceededTrigger(
                        scheduleRid="ri.orchestration.main.schedule.upstream"
                    ),
                    ManualTrigger(),
                ]
            ),
        ]
    )
    mock_schedule_class.get.return_value = pinned_schedule(
        ConnectingTarget(
            inputRids=["ri.foundry.main.dataset.input"],
            targetRids=["ri.foundry.main.dataset.output"],
            ignoredRids=[],
        ),
        trigger=trigger,
        scope=ProjectScope(projectRids=["ri.compass.main.folder.project"]),
    )
    mock_schedule_class.get_affected_resources.return_value = AffectedResourcesResponse(
        datasets=["ri.foundry.main.dataset.affected-output"]
    )
    mock_schedule_class.runs.return_value = Mock(
        data=[
            pinned_run(
                "submitted",
                ScheduleRunSubmitted(
                    buildRid="ri.orchestration.main.build.submitted-build"
                ),
            ),
            pinned_run("ignored", ScheduleRunIgnored()),
            pinned_run(
                "error",
                ScheduleRunError(errorName="INTERNAL", description="failed safely"),
            ),
            pinned_run("absent", None),
        ],
        next_page_token=None,
    )
    mock_build_class.get.return_value = Build(
        rid="ri.orchestration.main.build.submitted-build",
        branchName="feature",
        createdTime=datetime.now(timezone.utc),
        createdBy=ACTOR_ID,
        fallbackBranches=[],
        jobRids=[],
        retryCount=0,
        retryBackoffDuration=Duration(value=1, unit="SECONDS"),
        abortOnFailure=True,
        status="SUCCEEDED",
        scheduleRid=SCHEDULE_RID,
    )
    mock_build_class.jobs.return_value = Mock(data=[], next_page_token=None)

    collector = DependencyGraphService(client=SimpleNamespace())
    analysis = AnalysisContext.create(
        profile="test",
        host="https://example.palantirfoundry.com",
        requested_branch="feature",
    )
    root_node = collector._add_node(
        analysis,
        "dataset",
        "input",
        {"resource_rid": "ri.foundry.main.dataset.input"},
        True,
    )
    root = DependencyTarget(
        "dataset",
        root_node.identifiers,
        root_node.display_name,
        root_node.id,
    )
    schedule_node = collector._add_node(
        analysis,
        "schedule",
        SCHEDULE_RID,
        {"schedule_rid": SCHEDULE_RID},
    )
    records = {
        surface: collector._coverage_record(
            analysis, "schedule", surface, schedule_node.id
        )
        for surface in (
            "schedule-detail-action",
            "schedule-trigger",
            "schedule-affected-resources",
            "schedule-runs",
        )
    }

    collector._collect_schedule(analysis, root, schedule_node, orchestration, records)

    edges = list(analysis.edges.values())
    assert sum(edge.relation_kind == "run-submitted-build" for edge in edges) == 1
    assert sum(node.kind == "build" for node in analysis.nodes.values()) == 1
    assert {edge.relation_kind for edge in edges} >= {
        "schedule-consumes-resource",
        "schedule-produces-resource",
        "schedule-triggered-by-resource",
        "project-scope",
        "schedule-run",
        "run-submitted-build",
    }
    evidence_locators = {evidence.locator for evidence in analysis.evidence.values()}
    assert {
        "action.target.input_rids[0]",
        "action.target.target_rids[0]",
        "scope_mode.project_rids[0]",
        "trigger.triggers[0].dataset_rid",
        "trigger.triggers[1].triggers[0].schedule_rid",
        "runs[0].result.buildRid",
    } <= evidence_locators
    assert all(record.complete for record in records.values())
    assert not any(
        gap.reason_code.startswith("unknown-schedule-trigger")
        for gap in analysis.gaps.values()
    )
    mock_schedule_class.get.assert_called_once()
    mock_schedule_class.get_affected_resources.assert_called_once()
    mock_schedule_class.runs.assert_called_once()
    mock_build_class.get.assert_called_once()
    mock_build_class.jobs.assert_called_once()
    schedule_get_kwargs = mock_schedule_class.get.call_args.kwargs
    assert set(schedule_get_kwargs) == {
        "schedule_rid",
        "preview",
        "request_timeout",
    }
    assert schedule_get_kwargs["schedule_rid"] == SCHEDULE_RID
    assert schedule_get_kwargs["preview"] is True
    assert isinstance(schedule_get_kwargs["request_timeout"], int)
    affected_kwargs = mock_schedule_class.get_affected_resources.call_args.kwargs
    assert set(affected_kwargs) == {
        "schedule_rid",
        "preview",
        "request_timeout",
    }
    assert affected_kwargs["schedule_rid"] == SCHEDULE_RID
    assert affected_kwargs["preview"] is True
    assert isinstance(affected_kwargs["request_timeout"], int)
    runs_kwargs = mock_schedule_class.runs.call_args.kwargs
    assert set(runs_kwargs) == {"schedule_rid", "page_size", "request_timeout"}
    assert runs_kwargs["schedule_rid"] == SCHEDULE_RID
    assert runs_kwargs["page_size"] == 100
    assert isinstance(runs_kwargs["request_timeout"], int)
    build_get_kwargs = mock_build_class.get.call_args.kwargs
    assert set(build_get_kwargs) == {"build_rid", "request_timeout"}
    assert (
        build_get_kwargs["build_rid"] == "ri.orchestration.main.build.submitted-build"
    )
    assert isinstance(build_get_kwargs["request_timeout"], int)
    jobs_kwargs = mock_build_class.jobs.call_args.kwargs
    assert set(jobs_kwargs) == {"build_rid", "page_size", "request_timeout"}
    assert jobs_kwargs["build_rid"] == "ri.orchestration.main.build.submitted-build"
    assert jobs_kwargs["page_size"] == 100
    assert isinstance(jobs_kwargs["request_timeout"], int)
