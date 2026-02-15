from typing import Optional
from fastapi import HTTPException, WebSocket, WebSocketDisconnect, status
import numpy as np
from pydantic import BaseModel, ValidationError
from wauxio import Audio, StreamData
from wauxio.utils import AudioStack

from bmaster.api.auth import require_auth_token, require_bearer_jwt, require_permissions, require_user
from bmaster.api.auth.users import User
from bmaster.api.icoms.queries import query_author_from_user
import bmaster.icoms as icoms
from bmaster.icoms import Icom
from bmaster.icoms.queries import PlayOptions, Query, QueryStatus
from bmaster.api import api

# Frontend commonly sends chunks around 16k samples (~0.34s @48kHz).
# Keep this buffer above a single chunk to avoid regular underruns.
STREAM_STACK_SECONDS = 0.6


class APIStreamRequest(BaseModel):
	icom: str
	priority: int = 0
	force: bool = False
	rate: int
	channels: int

class APIStreamQuery(Query):
	type = 'api.stream'
	priority: int
	force: bool
	stack: AudioStack

	def __init__(self, icom: Icom, priority: int, force: bool, rate: int, channels: int, author: Optional[User] = None):
		self.description = "Playing plain audio stream"
		self.priority = priority
		self.force = force
		self.author = query_author_from_user(author) if author else None

		self.stack = AudioStack(
			rate=rate,
			channels=channels,
			samples=max(1, int(rate * STREAM_STACK_SECONDS))
		)

		super().__init__(icom)

	def play(self, options: PlayOptions):
		super().play(options)
		mixer = options.mixer
		mixer.add(self.stack.pull)
	
	def stop(self):
		super().stop()

def _get_ws_bearer_token(ws: WebSocket) -> Optional[str]:
	auth_header = ws.headers.get('authorization')
	if auth_header:
		scheme, _, token = auth_header.partition(' ')
		if scheme.lower() == 'bearer' and token:
			return token
		if scheme and not token:
			# Allow raw token in header for non-standard clients.
			return scheme
	return ws.query_params.get('token')

async def _require_stream_user(ws: WebSocket) -> Optional[User]:
	token = _get_ws_bearer_token(ws)
	if not token:
		await ws.send_json({
			'type': 'error',
			'error': 'missing bearer token'
		})
		await ws.close(code=status.WS_1008_POLICY_VIOLATION)
		return None

	try:
		jwt_data = require_bearer_jwt(token)
		auth_token = require_auth_token(jwt_data)
		user = await require_user(auth_token)
		require_permissions('bmaster.icoms.queries.stream')(user)
		return user
	except HTTPException as e:
		await ws.send_json({
			'type': 'error',
			'error': e.detail
		})
		await ws.close(code=status.WS_1008_POLICY_VIOLATION)
		return None

@api.websocket('/queries/stream')
async def play_stream(ws: WebSocket):
	await ws.accept()

	try:
		user = await _require_stream_user(ws)
	except WebSocketDisconnect:
		return
	if not user:
		return
	
	try:
		try:
			request = APIStreamRequest.model_validate_json(await ws.receive_text())
			print(request)
		except ValidationError as e:
			await ws.send_json({
				'type': 'error',
				'error': 'validation error',
				'validation.errors': e.errors()
			})
			await ws.close()
			return

		icom = icoms.get(request.icom)
		if not icom:
			await ws.send_json({
				'type': 'error',
				'error': 'icom not found'
			})
			await ws.close()
			return

		channels = request.channels
		# TODO: Implement multi-channels
		if channels != 1:
			await ws.send_json({
				'type': 'error',
				'error': 'only 1 channel supported'
			})
			await ws.close()
			return
		
		rate = request.rate
	except WebSocketDisconnect: return

	q = APIStreamQuery(
		icom=icom,
		priority=request.priority,
		force=request.force,
		rate=rate,
		channels=channels,
		author=user
	)
	
	try:
		await ws.send_json({
			'type': 'waiting' if q.status == QueryStatus.WAITING else 'started',
			'query': q.get_info().model_dump(mode='json')
		})
	except WebSocketDisconnect:
		q.cancel()
		return
	
	@q.on_cancel
	async def on_cancel():
		try:
			await ws.send_json({
				'type': 'cancelled',
				'query': q.get_info().model_dump(mode='json')
			})
			await ws.close()
		except WebSocketDisconnect: pass
		except RuntimeError: pass
	
	@q.on_stop
	async def on_stop():
		try:
			await ws.send_json({
				'type': 'stopped',
				'query': q.get_info().model_dump(mode='json')
			})
		except WebSocketDisconnect: pass
		except RuntimeError: pass
	
	@q.on_play
	async def on_play():
		try:
			await ws.send_json({
				'type': 'started',
				'query': q.get_info().model_dump(mode='json')
			})
		except WebSocketDisconnect: pass

	async for msg in ws.iter_bytes():
		# print(msg)
		arr = np.frombuffer(msg, dtype=np.float32).reshape((-1, channels))
		# TODO: Implement multi-channel support
		audio = Audio(arr, rate)
		q.stack.push(StreamData(audio))
	
	if q.status in (QueryStatus.WAITING, QueryStatus.PLAYING):
		q.cancel()
