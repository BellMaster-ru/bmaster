import asyncio
from asyncio import Task
from pathlib import Path
from typing import List, Optional
from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
import uvicorn

from bmaster import configs, logs


logger = logs.main_logger.getChild('server')


class CORSConfig(BaseModel):
	allow_origins: List[str] = ['*']
	allow_credentials: bool = True
	allow_methods: List[str] = Field(default_factory=lambda: ['*'])
	allow_headers: List[str] = Field(default_factory=lambda: ['*'])

class SSLConfig(BaseModel):
	enabled: bool = True
	cert_path: Path = Path('data/cert.pem')
	key_path: Path = Path('data/key.pem')

class ServerConfig(BaseModel):
	cors: CORSConfig = Field(default_factory=CORSConfig)
	ssl: SSLConfig = Field(default_factory=SSLConfig)

config: Optional[ServerConfig] = None


app = FastAPI(
	title="bmaster"
)

serving_task: Optional[Task] = None


async def start():
	global serving_task, config

	config = ServerConfig.model_validate(configs.get('server', None) or ServerConfig())

	cors_config = config.cors
	app.add_middleware(
		CORSMiddleware,
		allow_origins=cors_config.allow_origins,
		allow_credentials=cors_config.allow_credentials,
		allow_methods=cors_config.allow_methods,
		allow_headers=cors_config.allow_headers,
	)

	logger.info('Configuring uvicorn...')

	uvicorn_config = uvicorn.Config(
		app,
		host="0.0.0.0",
		port=8000,
		loop="asyncio",
		log_config=None
	)

	ssl_config = config.ssl
	if ssl_config.enabled:
		cert_path = ssl_config.cert_path
		key_path = ssl_config.key_path

		if not (cert_path.exists() and key_path.exists()):
			raise RuntimeError('Configured certificate or key file not found')
		uvicorn_config.ssl_keyfile = key_path
		uvicorn_config.ssl_certfile = cert_path
	
	logger.info("Starting uvicorn...")

	server = uvicorn.Server(uvicorn_config)
	serving_task = asyncio.create_task(server.serve())

	logger.info("Uvicorn started")

	# Serve React SPA for any other path
	@app.get("/{full_path:path}")
	async def serve_spa(request: Request, full_path: str):
		if not index_path.exists():
			return HTMLResponse("""
				<h1>React App Not Built</h1>
				<p>Run 'npm run build' in client directory first</p>
			""", status_code=404)
		
		return FileResponse(index_path)


# Serve static files from React build
app.mount('/assets', StaticFiles(directory='static/assets'), name='assets')
index_path = Path('static/index.html')


