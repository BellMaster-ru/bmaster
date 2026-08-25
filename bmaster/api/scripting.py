import asyncio
from typing import Optional
from fastapi import Depends, HTTPException, status
from pydantic import BaseModel, Field, SerializeAsAny
from sqlalchemy import select

from bmaster import logs
from bmaster.api.auth import require_permissions
from bmaster.scheduling import JobTrigger
from bmaster.scripting import BaseScript, Script, ScriptData, ScriptTask, ScriptTaskInfo, ScriptInfo
from bmaster.api import api

logger = logs.main_logger.getChild('api.scripting')


@api.get('/scripting/scripts/{script_id}', tags=['scripting'])
async def get_script(script_id: int) -> ScriptInfo:
	from bmaster.database import LocalSession
	async with LocalSession() as session:
		script = await session.get(Script, script_id)
	if not script: raise HTTPException(status.HTTP_404_NOT_FOUND, 'Task not found')
	return script.get_info()

@api.get('/scripting/scripts', tags=['scripting'])
async def get_scripts() -> list[ScriptInfo]:
	from bmaster.database import LocalSession
	async with LocalSession() as session:
		scripts = (await session.execute(select(Script))).scalars()
	return list(map(lambda s: s.get_info(), scripts))

class ScriptCreateRequest(BaseModel):
	name: str
	script: BaseScript

@api.post('/scripting/scripts', tags=['scripting'], dependencies=[
	Depends(require_permissions('bmaster.scripting.manage'))
])
async def create_script(req: ScriptCreateRequest) -> ScriptInfo:
	from bmaster.database import LocalSession
	script = Script(
		name=req.name,
		data=ScriptData(
			script=req.script
		)
	)
	async with LocalSession() as session, session.begin():
		session.add(script)
	return script.get_info()

@api.delete('/scripting/scripts/{script_id}', tags=['scripting'], dependencies=[
	Depends(require_permissions('bmaster.scripting.manage'))
])
async def delete_script(script_id: int):
	from bmaster.database import LocalSession
	async with LocalSession() as session, session.begin():
		script = await session.get(Script, script_id)
		if not script: raise HTTPException(status.HTTP_404_NOT_FOUND, 'Script not found')
		await session.delete(script)

class ScriptUpdateRequest(BaseModel):
	name: Optional[str] = None
	script: Optional[BaseScript] = None

@api.patch('/scripting/scripts/{script_id}', tags=['scripting'], dependencies=[
	Depends(require_permissions('bmaster.scripting.manage'))
])
async def update_script(script_id: int, req: ScriptUpdateRequest) -> ScriptInfo:
	from bmaster.database import LocalSession
	async with LocalSession() as session, session.begin():
		script = await session.get(Script, script_id)
		if not script: raise HTTPException(status.HTTP_404_NOT_FOUND, 'Script not found')

		if req.name is not None:
			script.name = req.name
		if req.script is not None:
			script.data = ScriptData(script=req.script)
	
	return script.get_info()

@api.get('/scripting/scripts/execute/{script_id}', tags=['scripting'], dependencies=[
	Depends(require_permissions('bmaster.scripting.execute'))
])
async def execute_script(script_id: int):
	from bmaster.database import LocalSession
	async with LocalSession() as session, session.begin():
		script = await session.get(Script, script_id)
		if not script: raise HTTPException(status.HTTP_404_NOT_FOUND, 'Script not found')
	def _on_script_done(t: asyncio.Task):
		if not t.cancelled() and t.exception():
			logger.error('Script #%d execution failed', script_id, exc_info=t.exception())
	asyncio.create_task(script.execute()).add_done_callback(_on_script_done)


@api.get('/scripting/tasks/{task_id}', tags=['scripting'])
async def get_task(task_id: int) -> ScriptTaskInfo:
	from bmaster.database import LocalSession
	async with LocalSession() as session:
		task = await session.get(ScriptTask, task_id)
	if not task: raise HTTPException(status.HTTP_404_NOT_FOUND, 'Task not found')
	
	return task.get_info()

@api.get('/scripting/tasks', tags=['scripting'])
async def get_tasks() -> list[ScriptTaskInfo]:
	from bmaster.database import LocalSession
	async with LocalSession() as session:
		scripts = (await session.execute(select(ScriptTask))).scalars()
	return list(map(lambda s: s.get_info(), scripts))

class ScriptTaskCreateRequest(BaseModel):
	script_id: int
	trigger: SerializeAsAny[JobTrigger]
	tags: set[str] = Field(default_factory=lambda: set())

@api.post('/scripting/tasks', tags=['scripting'], dependencies=[
	Depends(require_permissions('bmaster.scripting.manage'))
])
async def create_task(req: ScriptTaskCreateRequest) -> ScriptTaskInfo:
	from bmaster.database import LocalSession
	task = ScriptTask(tags=req.tags, trigger=req.trigger)

	async with LocalSession() as session, session.begin():
		script = await session.get(Script, req.script_id)
		if not script: raise HTTPException('Script not found')
		task.script = script
		session.add(task)

	task.post_create()
	return task.get_info()

@api.delete('/scripting/tasks/{task_id}', tags=['scripting'], dependencies=[
	Depends(require_permissions('bmaster.scripting.manage'))
])
async def delete_task(task_id: int):
	from bmaster.database import LocalSession
	async with LocalSession() as session, session.begin():
		task = await session.get(ScriptTask, task_id)
		if not task: raise HTTPException(status.HTTP_404_NOT_FOUND, 'Task not found')
		await session.delete(task)
	task.post_delete()

class ScriptTaskUpdateRequest(BaseModel):
	script_id: Optional[int] = None
	trigger: Optional[SerializeAsAny[JobTrigger]] = None
	tags: Optional[set[str]] = None

@api.patch('/scripting/tasks/{task_id}', tags=['scripting'], dependencies=[
	Depends(require_permissions('bmaster.scripting.manage'))
])
async def update_task(task_id: int, req: ScriptTaskUpdateRequest) -> ScriptTaskInfo:
	from bmaster.database import LocalSession
	async with LocalSession() as session, session.begin():
		task = await session.get(ScriptTask, task_id)
		if not task: raise HTTPException(status.HTTP_404_NOT_FOUND, 'Task not found')

		new_script_id = req.script_id
		if new_script_id is not None:
			script = await session.get(Script, new_script_id)
			if not script: raise HTTPException(status.HTTP_404_NOT_FOUND, 'Script not found')
			task.script = script
		if req.trigger is not None:
			task.trigger = req.trigger
	
	if req.trigger is not None:
		task.post_trigger_update()

	return task.get_info()
