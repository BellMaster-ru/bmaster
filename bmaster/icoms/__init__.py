import asyncio
from typing import Mapping, Optional
from pydantic import BaseModel, SerializeAsAny
from wauxio.output import AudioOutput
from wauxio.mixer import AudioMixer
from wauxio.utils import AudioStack

from bmaster import direct, logs
from bmaster.utils import aio
from .queries import PlayOptions, Query, QueryInfo
from bmaster import configs


logger = logs.main_logger.getChild('icoms')

ICOM_TICK_DELAY = 0.01
DIRECT_MIN_BUFFER_SECONDS = 0.2
DIRECT_BUFFER_FACTOR = 2.0

class IcomInfo(BaseModel):
	id: str
	name: Optional[str] = None
	playing: Optional[SerializeAsAny[QueryInfo]]
	queue: list[SerializeAsAny[QueryInfo]]
	paused: bool


class Icom:
	id: str
	name: Optional[str] = None
	queue: list[Query]
	playing: Optional[Query] = None
	mixer: AudioMixer
	paused: bool = False
	output: AudioOutput

	def __init__(self, icom_id: str):
		self.id = icom_id
		mixer = AudioMixer()
		output = AudioOutput(
			rate=48000,
			channels=1
		)
		output.connect(mixer.mix)
		self.queue = list()
		self.mixer = mixer
		self.output = output
	
	def run(self):
		return self.output.run(ICOM_TICK_DELAY)

	def start(self):
		if not self.paused: ValueError("Icom is not paused")
		self.paused = False
		next_query = self._take_next_query()
		if next_query: self._play_query(next_query)

	def stop(self):
		if self.paused: ValueError("Icom is paused")
		self.paused = True

		playing = self.playing
		if playing:
			playing.stop()
			self.playing = None
			self._add_query(playing)

	def _add_query(self, query: Query):
		if not self.paused:
			# directly play new query without queue if icom is free
			if not self.playing:
				self._play_query(query)
				return
			
			# check if new query can interrupt playing queries (is force)
			if query.force:
				playing = self.playing
				# check if new query has a higher priority than playing query
				if query.force > playing.force or query.priority > playing.priority:
					# stop playing query and play new query instead
					playing.stop()
					self.playing = None
					self._play_query(query)
					self._add_query(playing)
					return
		
		# insert a new request into the queue by sorting priority
		for i, playing in enumerate(self.queue):
			if query.force > playing.force or query.priority > playing.priority:
				self.queue.insert(i, query)
				break
		else:
			self.queue.append(query)
	
	def _remove_query(self, query: Query):
		self.queue.remove(query)
	
	def _take_next_query(self) -> Optional[Query]:
		queue = self.queue
		if len(queue) == 0: return None
		query = queue[0]
		del queue[0]
		return query

	def _play_query(self, query: Query):
		if self.playing: raise RuntimeError("There's already playing query")
		options = PlayOptions(
			mixer=self.mixer
		)
		self.playing = query
		aio.run(query.play(options))

	def _on_playing_finished(self):
		self.playing = None
		query = self._take_next_query()
		if query: self._play_query(query)
	
	def get_info(self) -> IcomInfo:
		playing = self.playing
		return IcomInfo(
			id=self.id,
			playing=playing.get_info() if self.playing else None,
			queue=list(map(lambda q: q.get_info(), self.queue)),
			paused=self.paused,
			name=self.name
		)


_icoms_map: Mapping[str, Icom] = dict()

def get(icom_id: str) -> Optional[Icom]:
	return _icoms_map.get(icom_id, None)


class IcomConfig(BaseModel):
	name: Optional[str] = None
	direct: bool = False

class IcomsConfig(BaseModel):
	icoms: dict[str, IcomConfig]

config: Optional[IcomsConfig] = None

async def start():
	global config

	config = IcomsConfig.model_validate(configs.get('icoms'))

	logger.debug('Initializing icoms from config...')
	
	for icom_id, icom_config in config.icoms.items():
		icom = Icom(icom_id)
		icom.name = icom_config.name
		if icom_config.direct:
			rate = icom.output.rate
			channels = icom.output.channels
			buffer_seconds = max(direct.DELAY * DIRECT_BUFFER_FACTOR, DIRECT_MIN_BUFFER_SECONDS)
			stack = AudioStack(
				rate=rate,
				channels=channels,
				samples=max(1, int(rate * buffer_seconds))
			)
			icom.output.listen(stack.push)
			direct.output_mixer.add(stack.pull)
		_icoms_map[icom_id] = icom
		asyncio.create_task(icom.run())

	logger.debug('Icoms initialized')
