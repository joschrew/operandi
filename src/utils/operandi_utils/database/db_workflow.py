from operandi_utils import call_sync
from .models import DBWorkflow


# TODO: This also updates to satisfy the PUT method in the Workflow Manager - fix this
async def db_create_workflow(
        workflow_id: str,
        workflow_dir: str,
        workflow_script_base: str,
        workflow_script_path: str
) -> DBWorkflow:
    try:
        db_workflow = await db_get_workflow(workflow_id)
    except RuntimeError:
        db_workflow = DBWorkflow(
            workflow_id=workflow_id,
            workflow_dir=workflow_dir,
            workflow_script_base=workflow_script_base,
            workflow_script_path=workflow_script_path
        )
    else:
        db_workflow.workflow_id = workflow_id
        db_workflow.workflow_dir = workflow_dir
        db_workflow.workflow_script_base = workflow_script_base
        db_workflow.workflow_script_path = workflow_script_path
    await db_workflow.save()
    return db_workflow


@call_sync
async def sync_db_create_workflow(
        workflow_id: str,
        workflow_dir: str,
        workflow_script_base: str,
        workflow_script_path: str
) -> DBWorkflow:
    return await sync_db_create_workflow(workflow_id, workflow_dir, workflow_script_base, workflow_script_path)


async def db_get_workflow(workflow_id: str) -> DBWorkflow:
    db_workflow = await DBWorkflow.find_one(DBWorkflow.workflow_id == workflow_id)
    if not db_workflow:
        raise RuntimeError(f"No DB workflow entry found for id: {workflow_id}")
    return db_workflow


@call_sync
async def sync_db_get_workflow(workflow_id: str) -> DBWorkflow:
    return await db_get_workflow(workflow_id)


async def db_update_workflow(find_workflow_id: str, **kwargs) -> DBWorkflow:
    db_workflow = await db_get_workflow(workflow_id=find_workflow_id)
    model_keys = list(db_workflow.__dict__.keys())
    for key, value in kwargs.items():
        if key not in model_keys:
            raise ValueError(f"Field not available: {key}")
        if key == 'workflow_id':
            db_workflow.workflow_id = value
        elif key == 'workflow_dir':
            db_workflow.workflow_dir = value
        elif key == 'workflow_script_base':
            db_workflow.workflow_script_base = value
        elif key == 'workflow_script_path':
            db_workflow.workflow_script_path = value
        elif key == 'deleted':
            db_workflow.deleted = value
        else:
            raise ValueError(f"Field not updatable: {key}")
    await db_workflow.save()
    return db_workflow


@call_sync
async def sync_db_update_workflow(find_workflow_id: str, **kwargs) -> DBWorkflow:
    return await db_update_workflow(find_workflow_id=find_workflow_id, **kwargs)