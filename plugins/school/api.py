import json
from typing import Annotated, List, Optional, Set
from fastapi import APIRouter, Depends, File, HTTPException, Response, UploadFile
from pydantic import BaseModel
from sqlalchemy import delete, select, and_
from sqlalchemy.orm.attributes import flag_modified
from datetime import date, timedelta

from bmaster.api.auth import require_permissions
from bmaster.api.sounds import SOUNDS_DIR, is_sound_name_valid
from bmaster.database import LocalSession
from bmaster.utils import TimeHHMM
from plugins.school.models import (
	Schedule, ScheduleData, ScheduleInfo, ScheduleLesson, PrecallEntry,
	ScheduleAssignment, ScheduleAssignmentInfo,
	ScheduleOverride, ScheduleOverrideInfo,
	Automation, AutomationInfo, WeekdaySet
)
from plugins.school import logger, on_automation, reschedule_automations, reschedule_lessons


router = APIRouter(prefix='/school', tags=['school'])


# SCHEDULE

class ScheduleCreateRequest(BaseModel):
	name: str
	lessons: List[ScheduleLesson]
	precalls: List[PrecallEntry] = []

class ScheduleUpdateRequest(BaseModel):
	name: str | None = None
	lessons: List[ScheduleLesson] | None = None
	precalls: List[PrecallEntry] | None = None

@router.get('/schedules')
async def get_schedules() -> List[ScheduleInfo]:
	async with LocalSession() as session:
		schedules = (await session.execute(select(Schedule))).scalars()
	return map(Schedule.get_info, schedules)

@router.post('/schedules/dupe/{schedule_id}', dependencies=[
	Depends(require_permissions('school.manage'))
])
async def dupe_schedule(schedule_id: int) -> ScheduleInfo:
	async with LocalSession() as session:
		async with session.begin():
			schedule: Optional[Schedule] = await session.get(Schedule, schedule_id)
			if schedule is None:
				raise HTTPException(404, 'school.schedules.not_found')
			new_schedule = Schedule(
				name='copy '+schedule.name,
				data=schedule.data
			)
			session.add(new_schedule)
	return new_schedule.get_info()

@router.get('/schedules/{schedule_id}')
async def get_schedule(schedule_id: int) -> ScheduleInfo:
	async with LocalSession() as session:
		schedule = await session.get(Schedule, schedule_id)
	if schedule is None: raise HTTPException(404, 'school.schedules.not_found')
	return schedule.get_info()

@router.post('/schedules', dependencies=[
	Depends(require_permissions('school.manage'))
])
async def create_schedule(req: ScheduleCreateRequest) -> ScheduleInfo:
	async with LocalSession() as session:
		async with session.begin():
			schedule = Schedule(
				name=req.name,
				data=ScheduleData(
					lessons=req.lessons,
					precalls=req.precalls
				)
			)
			session.add(schedule)
	return schedule.get_info()

@router.patch('/schedules/{schedule_id}', dependencies=[
	Depends(require_permissions('school.manage'))
])
async def update_schedule(schedule_id: int, req: ScheduleUpdateRequest) -> ScheduleInfo:
	async with LocalSession() as session:
		async with session.begin():
			schedule = await session.get(Schedule, schedule_id)
			if schedule is None:
				raise HTTPException(404, 'school.schedules.not_found')
			if req.name is not None:
				schedule.name = req.name
			if req.lessons is not None:
				schedule.data.lessons = req.lessons
				flag_modified(schedule, "data")
			if req.precalls is not None:
				schedule.data.precalls = req.precalls
				flag_modified(schedule, "data")
	await reschedule_lessons()
	return schedule.get_info()

@router.delete('/schedules/{schedule_id}', dependencies=[
	Depends(require_permissions('school.manage'))
])
async def delete_schedule(schedule_id: int):
	async with LocalSession() as session:
		async with session.begin():
			schedule = await session.get(Schedule, schedule_id)
			if schedule is None:
				raise HTTPException(404, 'school.schedules.not_found')
			await session.delete(schedule)
	await reschedule_lessons()


# SCHEDULE ASSIGNMENT

class ScheduleAssignmentCreateRequest(BaseModel):
	start_date: date
	monday: Optional[int] = None
	tuesday: Optional[int] = None
	wednesday: Optional[int] = None
	thursday: Optional[int] = None
	friday: Optional[int] = None
	saturday: Optional[int] = None
	sunday: Optional[int] = None

class ScheduleAssignmentUpdateRequest(BaseModel):
	start_date: Optional[date] = None
	monday: Optional[int] = None
	tuesday: Optional[int] = None
	wednesday: Optional[int] = None
	thursday: Optional[int] = None
	friday: Optional[int] = None
	saturday: Optional[int] = None
	sunday: Optional[int] = None

@router.get('/assignments')
async def get_schedule_assignments() -> List[ScheduleAssignmentInfo]:
	async with LocalSession() as session:
		assignments = (await session.execute(select(ScheduleAssignment))).scalars()
	return map(ScheduleAssignment.get_info, assignments)

@router.get('/assignments/query')
async def get_schedule_assignments_by_date_range(start_date: date, end_date: date) -> List[ScheduleAssignmentInfo]:
	async with LocalSession() as session:
		assignments = (await session.execute(
			select(ScheduleAssignment).where(
				and_(ScheduleAssignment.start_date >= start_date, ScheduleAssignment.start_date <= end_date)
			)
		)).scalars()
	return map(ScheduleAssignment.get_info, assignments)

@router.get('/assignments/active')
async def get_active_assignment(at: date | None = None) -> ScheduleAssignmentInfo | None:
	async with LocalSession() as session:
		# Get most actual assignment
		assignment: ScheduleAssignment | None = (await session.execute(
			select(ScheduleAssignment)
			.where(ScheduleAssignment.start_date <= (at or date.today()))
			.order_by(ScheduleAssignment.start_date.desc())
			.limit(1)
		)).scalar()
	
	if assignment is None: return None
	return assignment.get_info()

@router.get('/assignments/{assignment_id}')
async def get_schedule_assignment(assignment_id: int) -> ScheduleAssignmentInfo:
	async with LocalSession() as session:
		assignment = await session.get(ScheduleAssignment, assignment_id)
	if assignment is None:
		raise HTTPException(404, 'school.schedule_assignments.not_found')
	return assignment.get_info()

@router.post('/assignments', dependencies=[
	Depends(require_permissions('school.manage'))
])
async def create_schedule_assignment(req: ScheduleAssignmentCreateRequest) -> ScheduleAssignmentInfo:
	async with LocalSession() as session:
		async with session.begin():
			assignment = ScheduleAssignment(
				start_date=req.start_date,
				monday=req.monday,
				tuesday=req.tuesday,
				wednesday=req.wednesday,
				thursday=req.thursday,
				friday=req.friday,
				saturday=req.saturday,
				sunday=req.sunday
			)
			session.add(assignment)
	await reschedule_lessons()
	return assignment.get_info()

@router.patch('/assignments/{assignment_id}', dependencies=[
	Depends(require_permissions('school.manage'))
])
async def update_schedule_assignment(assignment_id: int, req: ScheduleAssignmentUpdateRequest) -> ScheduleAssignmentInfo:
	async with LocalSession() as session:
		async with session.begin():
			assignment = await session.get(ScheduleAssignment, assignment_id)
			if assignment is None:
				raise HTTPException(404, 'school.schedule_assignments.not_found')
			if req.start_date is not None:
				assignment.start_date = req.start_date
			for day in ['monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday']:
				val = getattr(req, day)
				# if val is not None:
				setattr(assignment, day, val)
	await reschedule_lessons()
	return assignment.get_info()

@router.delete('/assignments/{assignment_id}', dependencies=[
	Depends(require_permissions('school.manage'))
])
async def delete_schedule_assignment(assignment_id: int):
	async with LocalSession() as session:
		async with session.begin():
			assignment = await session.get(ScheduleAssignment, assignment_id)
			if assignment is None:
				raise HTTPException(404, 'school.schedule_assignments.not_found')
			await session.delete(assignment)
	await reschedule_lessons()


# SCHEDULE OVERRIDE

class ScheduleOverrideCreateRequest(BaseModel):
	at: date
	mute_all_lessons: bool
	mute_lessons: Set[int]

class ScheduleOverrideUpdateRequest(BaseModel):
	at: Optional[date] = None
	mute_all_lessons: Optional[bool] = None
	mute_lessons: Optional[Set[int]] = None

@router.get('/overrides')
async def get_schedule_overrides() -> List[ScheduleOverrideInfo]:
	async with LocalSession() as session:
		overrides = (await session.execute(select(ScheduleOverride))).scalars()
	return map(ScheduleOverride.get_info, overrides)

@router.get('/overrides/query')
async def get_schedule_overrides_by_date(start_date: date, end_date: date) -> List[ScheduleOverrideInfo]:
	async with LocalSession() as session:
		overrides = (await session.execute(
			select(ScheduleOverride).where(
				and_(ScheduleOverride.at >= start_date, ScheduleOverride.at <= end_date)
			)
		)).scalars()
	return map(ScheduleOverride.get_info, overrides)

@router.get('/overrides/{override_id}')
async def get_schedule_override(override_id: int) -> ScheduleOverrideInfo:
	async with LocalSession() as session:
		override = await session.get(ScheduleOverride, override_id)
	if override is None:
		raise HTTPException(404, 'school.schedule_overrides.not_found')
	return override.get_info()

@router.post('/overrides', dependencies=[
	Depends(require_permissions('school.manage'))
])
async def create_schedule_override(req: ScheduleOverrideCreateRequest, end_date: date | None = None) -> ScheduleOverrideInfo | List[ScheduleOverrideInfo] | None:
	mute_all_lessons = req.mute_all_lessons
	mute_lessons = req.mute_lessons
	deleting = mute_all_lessons == False and not mute_lessons
	overrides = None
	async with LocalSession() as session:
		async with session.begin():
			if end_date is not None:
				start_date = req.at
				overrides = []

				old_overrides = (await session.execute(
					select(ScheduleOverride)
					.where(and_(ScheduleOverride.at >= start_date, ScheduleOverride.at <= end_date))
					.order_by(ScheduleOverride.at)
				)).scalars()
				
				last_old_override: ScheduleOverride | None = next(old_overrides, None)

				cur_date = req.at
				while cur_date <= end_date:
					if last_old_override is not None and last_old_override.at == cur_date:
						if deleting:
							await session.delete(last_old_override)
						else:
							last_old_override.mute_all_lessons = mute_all_lessons
							last_old_override.mute_lessons = mute_lessons
						overrides.append(last_old_override)

						last_old_override = next(old_overrides, None)
					else:
						override = ScheduleOverride(
							at=cur_date,
							mute_all_lessons=mute_all_lessons,
							mute_lessons=mute_lessons
						)
						session.add(override)
						overrides.append(override)
					cur_date += timedelta(days=1)
			else:
				old_override: ScheduleOverride = (await session.execute(
					select(ScheduleOverride)
					.where(ScheduleOverride.at == req.at)
				)).scalar()
				if old_override:
					if deleting:
						await session.delete(old_override)
					else:
						old_override.mute_all_lessons = mute_all_lessons
						old_override.mute_lessons = mute_lessons
					overrides = old_override
				elif not deleting:
					override = ScheduleOverride(
						at=req.at,
						mute_all_lessons=req.mute_all_lessons,
						mute_lessons=req.mute_lessons
					)
					session.add(override)
					overrides = override
	
	if type(overrides) is list:
		return map(ScheduleOverride.get_info, overrides)
	elif overrides is not None:
		return overrides.get_info()

@router.patch('/overrides/{override_id}', dependencies=[
	Depends(require_permissions('school.manage'))
])
async def update_schedule_override(override_id: int, req: ScheduleOverrideUpdateRequest) -> ScheduleOverrideInfo:
	async with LocalSession() as session:
		async with session.begin():
			override = await session.get(ScheduleOverride, override_id)
			if override is None:
				raise HTTPException(404, 'school.schedule_overrides.not_found')
			if req.at is not None:
				override.at = req.at
			if req.mute_lessons is not None:
				override.mute_lessons = req.mute_lessons
	return override.get_info()

@router.delete('/overrides/{override_id}', dependencies=[
	Depends(require_permissions('school.manage'))
])
async def delete_schedule_override(override_id: int):
	async with LocalSession() as session:
		async with session.begin():
			override = await session.get(ScheduleOverride, override_id)
			if override is None:
				raise HTTPException(404, 'school.schedule_overrides.not_found')
			await session.delete(override)


# AUTOMATION

class AutomationCreateRequest(BaseModel):
	name: str
	sound_name: str
	at: TimeHHMM
	weekdays: WeekdaySet
	enabled: bool = True

class AutomationUpdateRequest(BaseModel):
	name: Optional[str] = None
	sound_name: Optional[str] = None
	at: Optional[TimeHHMM] = None
	weekdays: Optional[WeekdaySet] = None
	enabled: Optional[bool] = None

def check_sound_name(sound_name: str):
	'''Raises 404 if there is no such sound in the sound storage directory'''
	if not is_sound_name_valid(sound_name) or not (SOUNDS_DIR / sound_name).is_file():
		raise HTTPException(404, 'school.automations.sound_not_found')

@router.get('/automations')
async def get_automations() -> List[AutomationInfo]:
	async with LocalSession() as session:
		automations = (await session.execute(select(Automation))).scalars()
	return map(Automation.get_info, automations)

@router.get('/automations/{automation_id}')
async def get_automation(automation_id: int) -> AutomationInfo:
	async with LocalSession() as session:
		automation = await session.get(Automation, automation_id)
	if automation is None:
		raise HTTPException(404, 'school.automations.not_found')
	return automation.get_info()

@router.post('/automations', dependencies=[
	Depends(require_permissions('school.manage'))
])
async def create_automation(req: AutomationCreateRequest) -> AutomationInfo:
	check_sound_name(req.sound_name)
	async with LocalSession() as session:
		async with session.begin():
			automation = Automation(
				name=req.name,
				enabled=req.enabled,
				sound_name=req.sound_name,
				at=req.at,
				weekdays=req.weekdays
			)
			session.add(automation)
	await reschedule_automations()
	return automation.get_info()

@router.patch('/automations/{automation_id}', dependencies=[
	Depends(require_permissions('school.manage'))
])
async def update_automation(automation_id: int, req: AutomationUpdateRequest) -> AutomationInfo:
	if req.sound_name is not None:
		check_sound_name(req.sound_name)
	async with LocalSession() as session:
		async with session.begin():
			automation = await session.get(Automation, automation_id)
			if automation is None:
				raise HTTPException(404, 'school.automations.not_found')
			if req.name is not None:
				automation.name = req.name
			if req.sound_name is not None:
				automation.sound_name = req.sound_name
			if req.at is not None:
				automation.at = req.at
			if req.weekdays is not None:
				automation.weekdays = req.weekdays
			if req.enabled is not None:
				automation.enabled = req.enabled
	await reschedule_automations()
	return automation.get_info()

@router.delete('/automations/{automation_id}', dependencies=[
	Depends(require_permissions('school.manage'))
])
async def delete_automation(automation_id: int):
	async with LocalSession() as session:
		async with session.begin():
			automation = await session.get(Automation, automation_id)
			if automation is None:
				raise HTTPException(404, 'school.automations.not_found')
			await session.delete(automation)
	await reschedule_automations()

@router.post('/automations/{automation_id}/run', dependencies=[
	Depends(require_permissions('school.manage'))
])
async def run_automation(automation_id: int):
	'''Plays automation's sound right now, ignoring its schedule and `enabled` state'''
	async with LocalSession() as session:
		automation = await session.get(Automation, automation_id)
	if automation is None:
		raise HTTPException(404, 'school.automations.not_found')
	await on_automation(
		automation_id=automation.id,
		name=automation.name,
		sound_name=automation.sound_name
	)


class SchoolSettings(BaseModel):
	schedules: list[ScheduleInfo] | None = None
	assignments: list[ScheduleAssignmentInfo] | None = None
	overrides: list[ScheduleOverrideInfo] | None = None
	automations: list[AutomationInfo] | None = None

@router.get('/settings')
async def export_settings(schedules: bool = False, assignments: bool = False, overrides: bool = False, automations: bool = False):
	result = SchoolSettings()

	async with LocalSession() as session:

		if schedules:
			schedules_q = (await session.execute(select(Schedule))).scalars()
			result.schedules = list(map(Schedule.get_info, schedules_q))

		if assignments:
			assignments_q = (await session.execute(select(ScheduleAssignment))).scalars()
			result.assignments = list(map(ScheduleAssignment.get_info, assignments_q))

		if overrides:
			overrides_q = (await session.execute(select(ScheduleOverride))).scalars()
			result.overrides = list(map(ScheduleOverride.get_info, overrides_q))

		if automations:
			automations_q = (await session.execute(select(Automation))).scalars()
			result.automations = list(map(Automation.get_info, automations_q))

	return Response(
		content=result.model_dump_json(),
		media_type="application/json",
		headers={"Content-Disposition": "attachment; filename=school.json"}
	)

@router.post('/settings', dependencies=[
	Depends(require_permissions('school.manage'))
])
async def import_settings(file: UploadFile):
	settings = SchoolSettings.model_validate_json((await file.read()).decode('utf-8'))

	async with LocalSession() as session:
		async with session.begin():
			await session.execute(delete(Schedule))
			await session.execute(delete(ScheduleAssignment))
			await session.execute(delete(ScheduleOverride))
			await session.execute(delete(Automation))

			if schedules := settings.schedules:
				for info in schedules:
					session.add(Schedule.from_info(info))

			if assignments := settings.assignments:
				for info in assignments:
					session.add(ScheduleAssignment.from_info(info))

			if overrides := settings.overrides:
				for info in overrides:
					session.add(ScheduleOverride.from_info(info))

			if automations := settings.automations:
				for info in automations:
					session.add(Automation.from_info(info))
	await reschedule_lessons()
	await reschedule_automations()
