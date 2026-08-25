import asyncio
from typing import Optional
from pydantic import BaseModel, ValidationError
from fastapi import WebSocket, WebSocketDisconnect
from wauxio import StreamData
from wauxio.utils import AudioDrain

from bmaster.server import app
from bmaster import icoms
from bmaster.api import api


class APIListenRequest(BaseModel):
	icom: str
	rate: Optional[int] = None
	channels: Optional[int] = None
	chunk_size: int



@api.websocket('/icoms/listen')
async def listen_icom(ws: WebSocket):
	await ws.accept()

	try:
		try:
			request = APIListenRequest.model_validate_json(await ws.receive_text())
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

		icom_output = icom.output

		channels = request.channels or icom_output.channels
		# TODO: Implement multi-channels
		if channels != 1:
			await ws.send_json({
				'type': 'error',
				'error': 'only 1 channel supported'
			})
			await ws.close()
			return

		rate = request.rate or icom_output.rate

		chunk_size = request.chunk_size

		await ws.send_json({
			'type': 'listening',
			'rate': rate,
			'channels': channels,
			'chunk_size': chunk_size
		})
	except WebSocketDisconnect: return
	
	
	loop = asyncio.get_running_loop()
	# IAudioWriter
	def _write(frame: StreamData):
		audio = frame.audio
		if not audio: return
		loop.create_task(ws.send_bytes(audio.data.tobytes())).add_done_callback(lambda t: None)
	
	drain = AudioDrain(
		rate=rate,
		channels=channels,
		samples=chunk_size,
		output=_write
	)

	icom.output.listen(drain.push)

	try:
		while True:
			try: msg = await ws.receive_json()
			except WebSocketDisconnect: break
			except RuntimeError: break
	finally:
		icom.output.outputs.remove(drain.push)
