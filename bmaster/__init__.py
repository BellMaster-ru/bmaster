from wsignals import Signal

# init
from bmaster import configroles
import bmaster.plugins
from bmaster.logs import main_logger

import bmaster.configs
import bmaster.database
import bmaster.direct
import bmaster.sounds
import bmaster.icoms
import bmaster.scheduling
import bmaster.server
import bmaster.scripting
import bmaster.api


on_post_start = Signal()

async def start():
	main_logger.info('Starting...')

	# START
	bmaster.configs.load_configs()
	await bmaster.database.start()
	await bmaster.direct.start()
	await bmaster.sounds.start()
	await bmaster.icoms.start()
	await bmaster.scheduling.start()
	await bmaster.scripting.start()
	await bmaster.plugins.mount_plugins()
	await bmaster.api.start()
	await bmaster.server.start()

	# POST START
	await bmaster.database.update_models()
	
	main_logger.info('Started')

	on_post_start.connect(configroles.create_config_roles)
	on_post_start.call()

async def stop():
	main_logger.info("Stopping...")

	await bmaster.scheduling.stop()
	await bmaster.direct.stop()

	main_logger.info("Stopped")
