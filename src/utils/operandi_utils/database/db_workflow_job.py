from operandi_utils import call_sync
from .models import DBWorkflowJob


async def db_create_workflow_job(
        job_id: str,
        job_dir: str,
        job_state: str,
        workflow_id: str,
        workspace_id: str
) -> DBWorkflowJob:
    db_workflow_job = DBWorkflowJob(
        job_id=job_id,
        job_dir=job_dir,
        job_state=job_state,
        workflow_id=workflow_id,
        workspace_id=workspace_id
    )
    await db_workflow_job.save()
    return db_workflow_job


@call_sync
async def sync_db_create_workflow_job(
        job_id: str,
        workflow_id: str,
        workspace_id: str,
        job_dir: str,
        job_state: str
) -> DBWorkflowJob:
    return await db_create_workflow_job(job_id, workflow_id, workspace_id, job_dir, job_state)


async def db_get_workflow_job(job_id: str) -> DBWorkflowJob:
    db_workflow_job = await DBWorkflowJob.find_one(DBWorkflowJob.job_id == job_id)
    if not db_workflow_job:
        raise RuntimeError(f"No DB workflow job entry found for id: {job_id}")
    return db_workflow_job


@call_sync
async def sync_db_get_workflow_job(job_id: str) -> DBWorkflowJob:
    return await db_get_workflow_job(job_id)


async def db_update_workflow_job(find_job_id: str, **kwargs) -> DBWorkflowJob:
    db_workflow_job = await db_get_workflow_job(job_id=find_job_id)
    model_keys = list(db_workflow_job.__dict__.keys())
    for key, value in kwargs.items():
        if key not in model_keys:
            raise ValueError(f"Field not available: {key}")
        if key == 'job_id':
            db_workflow_job.job_id = value
        elif key == 'job_dir':
            db_workflow_job.job_dir = value
        elif key == 'job_state':
            db_workflow_job.job_state = value
        elif key == 'workflow_id':
            db_workflow_job.workflow_id = value
        elif key == 'workspace_id':
            db_workflow_job.workspace_id = value
        elif key == 'workflow_dir':
            db_workflow_job.workflow_dir = value
        elif key == 'workspace_dir':
            db_workflow_job.workspace_dir = value
        elif key == 'hpc_slurm_job_id':
            db_workflow_job.hpc_slurm_job_id = value
        elif key == 'deleted':
            db_workflow_job.deleted = value
        else:
            raise ValueError(f"Field not updatable: {key}")
    await db_workflow_job.save()
    return db_workflow_job


@call_sync
async def sync_db_update_workflow_job(find_job_id: str, **kwargs) -> DBWorkflowJob:
    return await db_update_workflow_job(find_job_id=find_job_id, **kwargs)
