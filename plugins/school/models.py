from datetime import date
from typing import List, Optional, Self, Set
from sqlalchemy import Boolean, Date, ForeignKey, Integer, Text
from sqlalchemy.orm import Mapped, mapped_column
from pydantic import BaseModel, Field

from bmaster.database import Base, JSONModel, ReprArray
from bmaster.utils import TimeHHMM


# SCHEDULE

class ScheduleLesson(BaseModel):
	'''One lesson in a `Schedule`'''
	start_at: TimeHHMM
	start_sound: Optional[str] = None
	end_at: TimeHHMM
	end_sound: Optional[str] = None

class PrecallEntry(BaseModel):
	'''One pre-call (предзвонок) in a `Schedule`'s pre-call sequence, played before every lesson start'''
	sound_name: str
	minutes_before: int = Field(ge=0)

class ScheduleInfo(BaseModel):
	'''Info snapshot of `Schedule`'''
	id: int
	name: str
	lessons: List[ScheduleLesson]
	precalls: List[PrecallEntry] = []

class ScheduleData(BaseModel):
	'''`Schedule` metadata'''
	lessons: List[ScheduleLesson]
	precalls: List[PrecallEntry] = []

class Schedule(Base):
	'''Stores full schedule for a day, contains `ScheduleLesson`s and its `PrecallEntry` sequence'''
	__tablename__ = 'school_schedule'

	id: Mapped[int] = mapped_column(Integer, primary_key=True)
	name: Mapped[str] = mapped_column(Text)
	data: Mapped[ScheduleData] = mapped_column(JSONModel(ScheduleData))

	def get_info(self) -> ScheduleInfo:
		return ScheduleInfo(
			id=self.id,
			name=self.name,
			lessons=self.data.lessons,
			precalls=self.data.precalls
		)

	def from_info(info: ScheduleInfo) -> Self:
		return Schedule(
			id=info.id,
			name=info.name,
			data=ScheduleData(lessons=info.lessons, precalls=info.precalls)
		)


# SCHEDULE ASSIGNMENT

class ScheduleAssignmentInfo(BaseModel):
	'''`ScheduleAssignment` info snapshot'''
	id: int
	start_date: date
	monday: Optional[int] = None
	tuesday: Optional[int] = None
	wednesday: Optional[int] = None
	thursday: Optional[int] = None
	friday: Optional[int] = None
	saturday: Optional[int] = None
	sunday: Optional[int] = None

class ScheduleAssignment(Base):
	'''Represents schedule change date, assigning new schedules for weekdays'''
	__tablename__ = 'school_schedule_assignment'

	id: Mapped[int] = mapped_column(Integer, primary_key=True)
	start_date: Mapped[date] = mapped_column(Date, unique=True)

	monday: Mapped[Optional[int]] = mapped_column(ForeignKey(Schedule.id), nullable=True)
	tuesday: Mapped[Optional[int]] = mapped_column(ForeignKey(Schedule.id), nullable=True)
	wednesday: Mapped[Optional[int]] = mapped_column(ForeignKey(Schedule.id), nullable=True)
	thursday: Mapped[Optional[int]] = mapped_column(ForeignKey(Schedule.id), nullable=True)
	friday: Mapped[Optional[int]] = mapped_column(ForeignKey(Schedule.id), nullable=True)
	saturday: Mapped[Optional[int]] = mapped_column(ForeignKey(Schedule.id), nullable=True)
	sunday: Mapped[Optional[int]] = mapped_column(ForeignKey(Schedule.id), nullable=True)

	def get_schedule_id_by_weekday_id(self, weekday_id: int):
		match weekday_id:
			case 0: return self.monday
			case 1: return self.tuesday
			case 2: return self.wednesday
			case 3: return self.thursday
			case 4: return self.friday
			case 5: return self.saturday
			case 6: return self.sunday

	def get_info(self) -> ScheduleAssignmentInfo:
		return ScheduleAssignmentInfo(
			id=self.id,
			start_date=self.start_date,
			monday=self.monday,
			tuesday=self.tuesday,
			wednesday=self.wednesday,
			thursday=self.thursday,
			friday=self.friday,
			saturday=self.saturday,
			sunday=self.sunday
		)

	def from_info(info: ScheduleAssignmentInfo) -> Self:
		return ScheduleAssignment(
			id=info.id,
			start_date=info.start_date,
			monday=info.monday,
			tuesday=info.tuesday,
			wednesday=info.wednesday,
			thursday=info.thursday,
			friday=info.friday,
			saturday=info.saturday,
			sunday=info.sunday
		)


# SCHEDULE OVERRIDE

class ScheduleOverrideInfo(BaseModel):
	'''`ScheduleOverride` info snapshot'''
	id: int
	at: date
	mute_all_lessons: bool = False
	mute_lessons: Set[int]

class ScheduleOverride(Base):
	'''Represents unusual schedule order assigned to specific day, like a bell mute'''
	__tablename__ = 'school_schedule_override'

	id: Mapped[int] = mapped_column(Integer, primary_key=True)
	at: Mapped[date] = mapped_column(Date, unique=True)
	mute_all_lessons: Mapped[bool] = mapped_column(Boolean)
	mute_lessons: Mapped[Set[int]] = mapped_column(ReprArray(int, unique_set=True))

	def get_info(self) -> ScheduleOverrideInfo:
		return ScheduleOverrideInfo(
			id=self.id,
			at=self.at,
			mute_all_lessons=self.mute_all_lessons,
			mute_lessons=self.mute_lessons
		)

	def from_info(info: ScheduleOverrideInfo) -> Self:
		return ScheduleOverride(
			id=info.id,
			at=info.at,
			mute_all_lessons=info.mute_all_lessons,
			mute_lessons=info.mute_lessons
		)
