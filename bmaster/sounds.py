import asyncio
import json
from pathlib import Path
from typing import Optional

from bmaster import logs


logger = logs.main_logger.getChild('sounds')

root = Path('data/sounds')

_duration_cache: dict[str, float] = {}


async def _ffprobe_duration(path: Path) -> Optional[float]:
	try:
		proc = await asyncio.create_subprocess_exec(
			'ffprobe', '-v', 'quiet',
			'-print_format', 'json',
			'-show_streams', str(path),
			stdout=asyncio.subprocess.PIPE,
			stderr=asyncio.subprocess.DEVNULL,
		)
		stdout, _ = await proc.communicate()
		if proc.returncode != 0:
			return None
		data = json.loads(stdout)
		for stream in data.get('streams', []):
			dur = stream.get('duration')
			if dur is not None:
				return float(dur)
	except Exception:
		pass
	return None


async def get_duration(name: str) -> Optional[float]:
	if name in _duration_cache:
		return _duration_cache[name]
	path = root / name
	if not path.is_file():
		return None
	dur = await _ffprobe_duration(path)
	if dur is not None:
		_duration_cache[name] = dur
	return dur


def invalidate(name: str):
	_duration_cache.pop(name, None)


async def start():
	logger.info('Sound storage ready')
