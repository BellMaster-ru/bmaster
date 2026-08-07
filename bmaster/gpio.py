"""Optional GPIO relay mode.

While any icom is playing something (sound, audio or stream), a configured
GPIO pin is held active, and it is released after playback ends. Typically
used to switch on an amplifier through a relay.

The feature is fully optional: if it is disabled in the config or no GPIO
backend is available (running not on a Raspberry Pi), the module stays idle
and playback works as usual.
"""

import threading
from typing import Optional, Protocol
from pydantic import BaseModel, Field

from bmaster import configs, logs


logger = logs.main_logger.getChild('gpio')

CONSUMER = 'bmaster'
# Chip labels of the Raspberry Pi header controller (rp1 is Pi 5)
CHIP_LABEL_PREFIXES = ('pinctrl-', 'gpio-brcmstb')


class GpioConfig(BaseModel):
	enabled: bool = False
	# GPIO (BCM) number, not a physical header pin number
	pin: int = Field(default=17, ge=0, le=53)
	# many relay boards are switched on by a low level
	active_high: bool = True
	# keeps the pin active between two subsequent queries so the relay
	# does not click on every queue item
	off_delay: float = Field(default=0.5, ge=0, le=60)
	# explicit gpiochip path, autodetected when not set
	chip: Optional[str] = None


class PinDriver(Protocol):
	def set(self, value: bool) -> None: ...
	def close(self) -> None: ...


class GpiodDriver:
	"""libgpiod v2 backend (Raspberry Pi OS Bookworm and newer, works on Pi 5)"""

	def __init__(self, config: GpioConfig):
		import gpiod
		from gpiod.line import Direction, Value

		self._gpiod = gpiod
		self._Value = Value
		self._pin = config.pin

		chip_path = config.chip or self._find_chip()
		self._request = gpiod.request_lines(
			chip_path,
			consumer=CONSUMER,
			config={
				config.pin: gpiod.LineSettings(
					direction=Direction.OUTPUT,
					active_low=not config.active_high,
					output_value=Value.INACTIVE
				)
			}
		)
		logger.info(f'Using gpiod backend, chip: {chip_path}, pin: {config.pin}')

	def _find_chip(self) -> str:
		gpiod = self._gpiod
		from pathlib import Path

		paths = sorted(Path('/dev').glob('gpiochip*'))
		fallback: Optional[str] = None
		for path in paths:
			path = str(path)
			if not gpiod.is_gpiochip_device(path):
				continue
			if fallback is None:
				fallback = path
			with gpiod.Chip(path) as chip:
				label = chip.get_info().label
			if label.startswith(CHIP_LABEL_PREFIXES):
				return path
		if fallback is None:
			raise RuntimeError('No gpiochip devices found')
		return fallback

	def set(self, value: bool):
		Value = self._Value
		self._request.set_value(self._pin, Value.ACTIVE if value else Value.INACTIVE)

	def close(self):
		self._request.release()


class GpiozeroDriver:
	"""gpiozero backend, used when gpiod is unavailable"""

	def __init__(self, config: GpioConfig):
		from gpiozero import OutputDevice

		self._device = OutputDevice(
			config.pin,
			active_high=config.active_high,
			initial_value=False
		)
		logger.info(f'Using gpiozero backend, pin: {config.pin}')

	def set(self, value: bool):
		if value: self._device.on()
		else: self._device.off()

	def close(self):
		self._device.close()


_DRIVERS = (GpiodDriver, GpiozeroDriver)

config: GpioConfig = GpioConfig()
_lock = threading.RLock()
_driver: Optional[PinDriver] = None
_error: Optional[str] = None
_value: bool = False
_active_icoms: set[str] = set()
_off_timer: Optional[threading.Timer] = None


class GpioState(BaseModel):
	enabled: bool
	pin: int
	active_high: bool
	off_delay: float
	chip: Optional[str] = None
	# whether a GPIO backend has been opened successfully
	available: bool
	# current pin state
	active: bool
	# reason why the pin is unavailable, if any
	detail: Optional[str] = None


def _open_driver():
	"""Opens the first available GPIO backend. Requires the lock to be held."""
	global _driver, _error, _value

	errors: list[str] = []
	for driver_type in _DRIVERS:
		try:
			_driver = driver_type(config)
		except Exception as e:
			errors.append(f'{driver_type.__name__}: {e}')
			logger.debug(f'GPIO backend {driver_type.__name__} is unavailable: {e}')
		else:
			_error = None
			_value = False
			return

	_driver = None
	_error = '; '.join(errors) or 'No GPIO backends available'
	logger.warning(f'GPIO mode is enabled, but no backend could be opened ({_error})')


def _close_driver():
	"""Requires the lock to be held."""
	global _driver, _value

	driver = _driver
	if driver is None: return
	_driver = None
	try:
		driver.set(False)
		driver.close()
	except Exception as e:
		logger.error('Failed to close GPIO backend', exc_info=e)
	_value = False


def _apply(value: bool):
	"""Requires the lock to be held."""
	global _value

	driver = _driver
	if driver is None or value == _value: return
	try:
		driver.set(value)
	except Exception as e:
		logger.error(f'Failed to set GPIO pin {config.pin} to {value}', exc_info=e)
		return
	_value = value
	logger.debug(f'GPIO pin {config.pin} is {"active" if value else "inactive"}')


def _cancel_timer():
	"""Requires the lock to be held."""
	global _off_timer

	timer = _off_timer
	if timer is None: return
	_off_timer = None
	timer.cancel()


def _delayed_off():
	global _off_timer

	with _lock:
		_off_timer = None
		if _active_icoms: return
		_apply(False)


def _refresh():
	"""Requires the lock to be held."""
	global _off_timer

	if _active_icoms:
		_cancel_timer()
		_apply(True)
		return

	if not _value or _off_timer is not None: return

	off_delay = config.off_delay
	if off_delay <= 0:
		_apply(False)
		return

	timer = threading.Timer(off_delay, _delayed_off)
	timer.daemon = True
	_off_timer = timer
	timer.start()


def set_icom_active(icom_id: str, active: bool):
	"""Marks an icom as playing or idle. Safe to call from any thread."""
	with _lock:
		if not config.enabled: return
		if active: _active_icoms.add(icom_id)
		else: _active_icoms.discard(icom_id)
		_refresh()


def get_state() -> GpioState:
	with _lock:
		return GpioState(
			enabled=config.enabled,
			pin=config.pin,
			active_high=config.active_high,
			off_delay=config.off_delay,
			chip=config.chip,
			available=_driver is not None,
			active=_value,
			detail=_error
		)


def apply_config(new_config: GpioConfig, save: bool = True) -> GpioState:
	"""Applies a new config at runtime and persists it to the main config."""
	global config, _error

	with _lock:
		_cancel_timer()
		_close_driver()

		config = new_config
		if save:
			configs.set('gpio', new_config.model_dump())

		if new_config.enabled:
			_open_driver()
			_refresh()
		else:
			_error = None
			_active_icoms.clear()

		logger.info(f'GPIO mode is {"enabled" if new_config.enabled else "disabled"}')
		return get_state()


async def start():
	global config

	with _lock:
		config = GpioConfig.model_validate(configs.get('gpio', {}))
		if not config.enabled:
			logger.info('GPIO mode is disabled')
			return
		logger.info('Starting GPIO mode...')
		_open_driver()


async def stop():
	with _lock:
		_cancel_timer()
		_active_icoms.clear()
		_close_driver()
