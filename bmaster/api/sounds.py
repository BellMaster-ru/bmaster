import os
from pathlib import Path
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, UploadFile, status
from fastapi.responses import FileResponse
from pydantic import BaseModel
import re
import anyio

from bmaster import sounds
from bmaster.api import api
from bmaster.api.auth import require_permissions


router = APIRouter(tags=['sounds'])

SOUNDS_DIR = Path('data/sounds')


class SoundSpecs(BaseModel):
	duration: float

class SoundInfo(BaseModel):
	name: str
	size: int
	sound_specs: Optional[SoundSpecs] = None

def is_sound_name_valid(name: str) -> bool:
	return re.fullmatch(r'[a-zA-Zа-яА-Я\d_\- ]+\.[a-z\d]+', name) is not None


@router.get('/info')
async def get_sounds() -> list[SoundInfo]:
	res: list[SoundInfo] = []
	for file in SOUNDS_DIR.iterdir():
		if not file.is_file():
			continue
		name = file.name
		dur = await sounds.get_duration(name)
		res.append(
			SoundInfo(
				name=name,
				size=file.stat().st_size,
				sound_specs=SoundSpecs(duration=dur) if dur is not None else None,
			)
		)
	return res


@router.get('/file/{name}')
async def get_sound_file(name: str) -> FileResponse:
	if not is_sound_name_valid(name):
		raise HTTPException(status.HTTP_400_BAD_REQUEST, 'Invalid file name')

	file_path = SOUNDS_DIR / name
	if not file_path.exists() or not file_path.is_file():
		raise HTTPException(status.HTTP_404_NOT_FOUND, 'File not found')

	return FileResponse(file_path)


@router.delete('/file/{name}', dependencies=[
	Depends(require_permissions('bmaster.sounds.manage'))
])
async def delete_sound_file(name: str):
	if not is_sound_name_valid(name):
		raise HTTPException(status.HTTP_400_BAD_REQUEST, 'Invalid file name')

	file_path = SOUNDS_DIR / name
	if not file_path.exists() or not file_path.is_file():
		raise HTTPException(status.HTTP_404_NOT_FOUND, 'File not found')

	os.remove(file_path)
	sounds.invalidate(name)


@router.post('/file', dependencies=[
	Depends(require_permissions('bmaster.sounds.manage'))
])
async def upload_sound_file(file: UploadFile):
	name = file.filename
	if not is_sound_name_valid(name):
		raise HTTPException(status.HTTP_400_BAD_REQUEST, 'Invalid file name')

	file_path = SOUNDS_DIR / name
	if file_path.exists():
		raise HTTPException(
			status.HTTP_409_CONFLICT, 'File with this name already exists'
		)

	async with await anyio.open_file(file_path, 'wb') as f:
		await f.write(await file.read())
