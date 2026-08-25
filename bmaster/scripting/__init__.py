from types import CoroutineType
from typing import Optional
from pydantic import BaseModel, Field, SerializeAsAny

from sqlalchemy import ForeignKey, Integer, Select, Text, and_, or_, select
from sqlalchemy.orm import Mapped, mapped_column, relationship

from bmaster import configs, logs, database
from bmaster.database import Base, JSONModel, TextArray
from bmaster.scheduling import JobTrigger, scheduler

from bmaster.scripting.commands import ScriptCommand


class ScriptingConfig(BaseModel):
	pass

config: Optional[ScriptingConfig] = None

logger = logs.main_logger.getChild('scripting')

async def start():
	logger.debug('Starting scripting...')
	global config
	config = ScriptingConfig.model_validate(configs.get('scripting', None) or ScriptingConfig())
	logger.debug('Scripting started')


# --  SCRIPTS  -- #

class BaseScript(BaseModel):
	commands: list[SerializeAsAny[ScriptCommand]]

	async def execute(self) -> None:
		for cmd in self.commands:
			await cmd.execute()

class ScriptData(BaseModel):
	script: BaseScript

class ScriptInfo(BaseModel):
	id: int
	name: str
	script: BaseScript


class Script(Base):
	__tablename__ = 'script'

	id: Mapped[int] = mapped_column(Integer, primary_key=True)
	name: Mapped[str] = mapped_column(Text, nullable=False)
	data: Mapped[ScriptData] = mapped_column(JSONModel(ScriptData), nullable=False)

	tasks: Mapped[list["ScriptTask"]] = relationship(back_populates='script')

	def execute(self) -> CoroutineType:
		return self.data.script.execute()
	
	def get_info(self) -> ScriptInfo:
		return ScriptInfo(
			id=self.id,
			name=self.name,
			script=self.data.script
		)



# --  TASKS  -- #

class ScriptTaskInfo(BaseModel):
	id: int
	script_id: int
	tags: set[str]
	trigger: SerializeAsAny[JobTrigger]

class ScriptTask(Base):
	__tablename__ = 'script_task'

	id: Mapped[int] = mapped_column(Integer, primary_key=True)
	script_id: Mapped[int] = mapped_column(ForeignKey(Script.id))
	tags: Mapped[set[str]] = mapped_column(TextArray(unique_set=True))
	trigger: Mapped[SerializeAsAny[JobTrigger]] = mapped_column(JSONModel(SerializeAsAny[JobTrigger]))

	script: Mapped[Script] = relationship(back_populates='tasks', lazy='joined')
	
	def post_create(self):
		scheduler.add_job(
			func=execute_script_task_by_id,
			id=f'bmaster.scripting.script_task#{self.id}',
			kwargs={ 'task_id': self.id },
			**self.trigger.job_kwargs()
		)

	def post_trigger_update(self):
		scheduler.remove_job(f'bmaster.scripting.script_task#{self.id}')
		if self.trigger:
			scheduler.add_job(
				func=execute_script_task_by_id,
				id=f'bmaster.scripting.script_task#{self.id}',
				kwargs={ 'task_id': self.id },
				**self.trigger.job_kwargs()
			)

	def post_delete(self):
		scheduler.remove_job(f'bmaster.scripting.script_task#{self.id}')

	def search_tags(self, search_tags: list[str]) -> Select:
		# search_tags = [tag.strip().lower() for tag in search_tags if tag.strip()]
		conditions = []
		for tag in search_tags:
			# Match tags at start, middle, or end of the string
			conditions.append(
				or_(
					self.tags.ilike(f'%,{tag},%'),
					self.tags.ilike(f'{tag},%'),
					self.tags.ilike(f'%,{tag}'),
					self.tags == tag
				)
			)
		
		return select(self.__class__).where(and_(*conditions))
	
	def get_info(self) -> ScriptTaskInfo:
		return ScriptTaskInfo(
			id=self.id,
			script_id=self.script_id,
			tags=self.tags,
			trigger=self.trigger
		)

async def execute_script_task_by_id(task_id: int):
	async with database.LocalSession() as session:
		task = await session.get(ScriptTask, task_id)
	
	if task:
		await task.script.execute()
	else:
		logger.warning(f'Removing orphan job bounded to unknown script task #{task_id}')
		try: scheduler.remove_job(f'bmaster.scripting.script_task#{task_id}')
		except Exception: pass
