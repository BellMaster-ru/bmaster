import asyncio
import logging
from typing import Coroutine


logger = logging.getLogger('bmaster.aio')


class AIONoLoop(Exception):
	"""Exception raised when no running event loop is found."""
	pass


def _log_task_exception(task: asyncio.Task):
	if not task.cancelled() and task.exception():
		logger.error('Unhandled exception in background task', exc_info=task.exception())


def run(body: Coroutine | None, ignore: bool = False):
	if asyncio.iscoroutine(body):
		try: loop = asyncio.get_running_loop()
		except RuntimeError: loop = None
		if loop:
			task = loop.create_task(body)
			task.add_done_callback(_log_task_exception)
		else:
			body.close()
			if not ignore: raise AIONoLoop()
