import numpy as np
from wauxio.mixer import AudioMixer
from wauxio.output import AudioOutput
import sounddevice as sd

from bmaster import logs


logger = logs.main_logger.getChild('direct')

RATE = 48000
CHANNELS = 2
# Audio device callback block duration. Lower value -> lower latency, higher CPU load.
DELAY = 0.1

output_mixer: AudioMixer = AudioMixer()
output: AudioOutput = AudioOutput(
	channels=CHANNELS,
	rate=RATE
)
output.connect(output_mixer)

out_stream = None

async def start():
	global out_stream
	logger.info('Starting output stream...')

	def _out_callback(outdata, frames, time, status):
		outdata.fill(0)
		duration = frames/RATE
		frame = output.tick(duration)
		audio = frame.audio
		if not audio: return
		data = audio.data
		outdata[:len(data)] = data
	
	out_stream = sd.OutputStream(
		samplerate=RATE,
		blocksize=max(1, int(RATE * DELAY)),
		channels=CHANNELS,
		dtype=np.float32,
		callback=_out_callback
	)

	out_stream.start()
	logger.info('Output stream started')

async def stop():
	global out_stream
	logger.info('Closing output stream...')
	if out_stream is not None:
		out_stream.close()
	logger.info('Output stream closed')
