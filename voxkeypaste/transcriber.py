"""Speech to text: a local faster-whisper model or any OpenAI-compatible API
(OpenAI itself, or a self-hosted server such as faster-whisper-server/speaches)."""
import io
import os
import threading
import time

import numpy as np
import soundfile as sf

from . import config


class TranscriptionError(Exception):
    pass


class Transcriber:
    def __init__(self, cfg):
        self.cfg = cfg
        self._model = None
        self._model_error = None
        self._model_ready = threading.Event()

    def _t(self, key):
        return self.cfg.get('transcription', key)

    # --- local ---------------------------------------------------------------------------------
    def preload(self):
        """Load the local model in the background (it can take a while the first time)."""
        if self._t('backend') != 'local':
            self._model_ready.set()
            return
        threading.Thread(target=self._load_model, name='model-loader', daemon=True).start()

    def _load_model(self):
        try:
            from faster_whisper import WhisperModel
            model, device, compute = self._t('local_model'), self._t('local_device'), self._t('local_compute_type')
            config.log(f'Loading local model {model} ({device}, {compute})...')
            started = time.time()
            try:
                self._model = WhisperModel(model, device=device, compute_type=compute)
                if device != 'cpu':
                    # On a PC with an NVIDIA card the model "loads" on the GPU even when the CUDA libraries
                    # (cuBLAS/cuDNN) are missing, and only fails when transcribing. Find out now.
                    self._warm_up()
            except Exception as e:
                if device == 'cpu':
                    raise
                config.log(f'The model does not work on {device} ({e}); using the CPU.')
                self._model = WhisperModel(model, device='cpu',
                                           compute_type='int8' if compute in ('default', 'float16', 'int8_float16')
                                           else compute)
            config.log(f'Model loaded in {time.time() - started:.1f} s.')
        except Exception as e:
            self._model_error = e
            config.log(f'Local model not available: {type(e).__name__}: {e}')
        finally:
            self._model_ready.set()

    def _warm_up(self):
        """Transcribe half a second of silence: raises if the device cannot really run the model."""
        segments, _ = self._model.transcribe(np.zeros(8000, dtype=np.float32), language='en', vad_filter=False)
        list(segments)

    def _transcribe_local(self, audio, sample_rate):
        self._model_ready.wait()
        if self._model is None:
            raise TranscriptionError(f'local model not available ({self._model_error})')
        samples = audio.astype(np.float32) / 32768.0
        if sample_rate != 16000:                      # faster-whisper expects 16 kHz
            n = int(len(samples) * 16000 / sample_rate)
            samples = np.interp(np.linspace(0, len(samples) - 1, n), np.arange(len(samples)), samples).astype(np.float32)
        segments, _ = self._model.transcribe(samples, language=self._t('language') or None,
                                             initial_prompt=self._t('initial_prompt') or None,
                                             temperature=self._t('temperature'),
                                             vad_filter=self._t('local_vad_filter'))
        return ''.join(segment.text for segment in segments)

    # --- API -----------------------------------------------------------------------------------
    def api_key(self):
        key = self._t('api_key') or os.environ.get('OPENAI_API_KEY', '')
        return key or 'not-needed'           # self-hosted servers usually ignore it

    def _transcribe_api(self, audio, sample_rate):
        import httpx
        wav = io.BytesIO()
        sf.write(wav, audio, sample_rate, format='WAV', subtype='PCM_16')
        url = self._t('api_base_url').rstrip('/') + '/audio/transcriptions'
        if not url.lower().startswith(('http://', 'https://')):
            raise TranscriptionError('api_base_url must start with http:// or https://')
        data = {'model': self._t('api_model'), 'temperature': str(self._t('temperature')), 'response_format': 'json'}
        if self._t('language'):
            data['language'] = self._t('language')
        if self._t('initial_prompt'):
            data['prompt'] = self._t('initial_prompt')
        # No overall time limit on purpose (long dictations on a busy server must not be thrown away);
        # only the connection attempt is bounded.
        timeout = httpx.Timeout(None, connect=10.0)
        response = httpx.post(url, data=data, files={'file': ('audio.wav', wav.getvalue(), 'audio/wav')},
                              headers={'Authorization': f'Bearer {self.api_key()}'}, timeout=timeout)
        if response.status_code != 200:
            raise TranscriptionError(f'HTTP {response.status_code}: {response.text[:200]}')
        return response.json().get('text', '')

    def transcribe(self, audio, sample_rate):
        if self._t('backend') == 'api':
            return self._transcribe_api(audio, sample_rate)
        return self._transcribe_local(audio, sample_rate)


def list_models(base_url, api_key=''):
    """Model ids offered by an OpenAI-compatible server (GET /models). Raises on any failure."""
    import httpx
    base_url = (base_url or '').strip().rstrip('/')
    if not base_url.lower().startswith(('http://', 'https://')):
        raise TranscriptionError('the URL must start with http:// or https://')
    key = api_key or os.environ.get('OPENAI_API_KEY', '') or 'not-needed'
    response = httpx.get(base_url + '/models', headers={'Authorization': f'Bearer {key}'},
                         timeout=httpx.Timeout(8.0, connect=5.0))
    if response.status_code != 200:
        raise TranscriptionError(f'HTTP {response.status_code}: {response.text[:200]}')
    data = response.json().get('data', [])
    return sorted({m.get('id') for m in data if isinstance(m, dict) and m.get('id')})


def post_process(text, cfg):
    text = (text or '').strip()
    if not text:
        return ''
    if cfg.get('output', 'remove_trailing_period') and text.endswith('.') and not text.endswith('...'):
        text = text[:-1]
    if cfg.get('output', 'lowercase'):
        text = text.lower()
    if cfg.get('output', 'add_trailing_space'):
        text += ' '
    return text
