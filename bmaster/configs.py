import yaml
from pathlib import Path
from typing import Optional

from bmaster.logs import main_logger


logger = main_logger.getChild('configs')

CONFIG_PATH = Path('data/config.yml')
_UNDEFINED = {}
main_config: Optional[dict] = None

def _require_loaded_config() -> dict:
	if main_config is None:
		raise RuntimeError('Main config is not loaded yet')
	return main_config

def load_configs():
	global main_config

	logger.info('Loading main config...')

	try:
		with open(CONFIG_PATH, 'r', encoding='utf8') as f:
			config = yaml.safe_load(f)
		if not isinstance(config, dict):
			raise ValueError('Config root node should be a dictionary')
		main_config = config
	except Exception as e:
		logger.error('Failed to load main config', exc_info=e)
		raise

	logger.info('Main config loaded')

def get(name: str, default = _UNDEFINED):
	config = _require_loaded_config()
	
	try:
		data = config[name]
		return data
	except KeyError:
		if default is _UNDEFINED:
			logger.error(f'Main config partition "{name}" is missing')
			raise
		else:
			return default

# def save_configs():
# 	config = _require_loaded_config()
# 	tmp_path = CONFIG_PATH.with_suffix(CONFIG_PATH.suffix + '.tmp')

# 	with open(tmp_path, 'w', encoding='utf8') as f:
# 		yaml.safe_dump(config, f, allow_unicode=True, sort_keys=False)

# 	tmp_path.replace(CONFIG_PATH)

# def update_network_settings(ip: str, mask: str, gateway: str, dns: str):
# 	config = _require_loaded_config()
# 	config['network'] = {
# 		'ip': ip,
# 		'mask': mask,
# 		'gateway': gateway,
# 		'dns': dns,
# 	}
# 	save_configs()
