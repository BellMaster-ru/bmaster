from datetime import date, datetime, timedelta
from typing import Optional
from sqlalchemy import select
import bmaster
from bmaster import icoms
from bmaster.database import LocalSession
from bmaster.icoms.queries import QueryAuthor, SoundQuery
from bmaster.logs import main_logger
from bmaster.scheduling import scheduler
from plugins.school.models import Automation, Schedule, ScheduleAssignment, ScheduleLesson, ScheduleOverride


logger = main_logger.getChild('school')
ICOM_ID = 'main'


async def start():
	logger.info('Starting...')
	from plugins.school.api import router
	from bmaster.api import api
	api.include_router(router)
	bmaster.on_post_start.connect(reschedule_lessons)
	bmaster.on_post_start.connect(reschedule_automations)
	logger.info('Started')


async def get_today_schedule() -> Optional[Schedule]:
	today = date.today()
	async with LocalSession() as session:
		# Get most actual assignment
		assignment = (await session.execute(
			select(ScheduleAssignment)
			.where(ScheduleAssignment.start_date <= today)
			.order_by(ScheduleAssignment.start_date.desc())
			.limit(1)
		)).scalar()
		# Return if there's no active assignments
		if assignment is None: return None

		# Get schedule for current weekday in active assignment
		schedule_id = assignment.get_schedule_id_by_weekday_id(today.weekday())
		if schedule_id is not None:
			return await session.get(Schedule, schedule_id)

async def get_today_override() -> Optional[ScheduleOverride]:
	today = date.today()
	async with LocalSession() as session:
		return (await session.execute(
			select(ScheduleOverride)
			.where(ScheduleOverride.at == today)
		)).scalar()

async def is_lesson_muted(lesson_num: int) -> bool:
	override = await get_today_override()
	if override is None: return False
	return override.mute_all_lessons or lesson_num in override.mute_lessons

async def on_lesson(lesson_num: int, lesson_info: ScheduleLesson, is_start: bool):
	sound_name = lesson_info.start_sound if is_start else lesson_info.end_sound
	# Skip if there's no sound setup
	if sound_name is None: return

	# Skip if this lesson is muted for today
	if await is_lesson_muted(lesson_num): return

	SoundQuery(
		icom=icoms.get(ICOM_ID),
		sound_name=sound_name,
		priority=0,
		force=False,
		author=QueryAuthor(
			type='service',
			name='Звонки'
		)
	)

async def on_precall(lesson_num: int, sound_name: str):
	# Skip if this lesson is muted for today (no point pre-calling a muted lesson)
	if await is_lesson_muted(lesson_num): return

	SoundQuery(
		icom=icoms.get(ICOM_ID),
		sound_name=sound_name,
		priority=0,
		force=False,
		author=QueryAuthor(
			type='service',
			name='Предзвонок'
		)
	)

async def reschedule_lessons():
	logger.info('Rescheduling lessons...')

	# Clear old jobs
	for job in scheduler.get_jobs(jobstore='temp'):
		if job.id.startswith('school.lesson'):
			job.remove()
	
	schedule = await get_today_schedule()

	if schedule is None:
		logger.info('There is no schedule for today, skipping...')
		return

	for i, lesson in enumerate(schedule.data.lessons):
		scheduler.add_job(
			jobstore='temp',
			id=f'school.lesson.start#{i}',
			func=on_lesson,
			trigger='cron',
			hour=lesson.start_at.hour,
			minute=lesson.start_at.minute,
			kwargs={
				'lesson_num': i,
				'lesson_info': lesson,
				'is_start': True
			}
		)
		# Precalls are the schedule's own precall sequence, played before every lesson start
		# (never before lesson end)
		for j, precall in enumerate(schedule.data.precalls):
			precall_at = (
				datetime.combine(date.today(), lesson.start_at)
				- timedelta(minutes=precall.minutes_before)
			).time()
			scheduler.add_job(
				jobstore='temp',
				id=f'school.lesson.precall#{i}.{j}',
				func=on_precall,
				trigger='cron',
				hour=precall_at.hour,
				minute=precall_at.minute,
				kwargs={
					'lesson_num': i,
					'sound_name': precall.sound_name
				}
			)
		scheduler.add_job(
			jobstore='temp',
			id=f'school.lesson.end#{i}',
			func=on_lesson,
			trigger='cron',
			hour=lesson.end_at.hour,
			minute=lesson.end_at.minute,
			kwargs={
				'lesson_num': i,
				'lesson_info': lesson,
				'is_start': False
			}
		)

	logger.info('Lessons rescheduled')


async def on_automation(automation_id: int, name: str, sound_name: str):
	logger.info(f'Playing automation #{automation_id} \'{name}\'')
	# Automations are independent of lessons, so lesson mutes are not applied here
	SoundQuery(
		icom=icoms.get(ICOM_ID),
		sound_name=sound_name,
		priority=0,
		force=False,
		author=QueryAuthor(
			type='service',
			name='Автоматизация',
			label=name
		)
	)

async def reschedule_automations():
	logger.info('Rescheduling automations...')

	# Clear old jobs
	for job in scheduler.get_jobs(jobstore='temp'):
		if job.id.startswith('school.automation'):
			job.remove()

	async with LocalSession() as session:
		automations = (await session.execute(
			select(Automation).where(Automation.enabled == True)
		)).scalars().all()

	for automation in automations:
		# Automation without weekdays would never be triggered
		if not automation.weekdays: continue

		scheduler.add_job(
			jobstore='temp',
			id=f'school.automation#{automation.id}',
			func=on_automation,
			trigger='cron',
			day_of_week=','.join(map(str, sorted(automation.weekdays))),
			hour=automation.at.hour,
			minute=automation.at.minute,
			kwargs={
				'automation_id': automation.id,
				'name': automation.name,
				'sound_name': automation.sound_name
			}
		)

	logger.info(f'Automations rescheduled ({len(automations)} enabled)')
