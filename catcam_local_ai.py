"""Authenticated Pi 4 local detector client. Never falls back to Google Vision."""
import json
from pathlib import Path
import requests

TOKEN_FILE = Path('/home/pi/catcam_local_ai_token')


class LocalAIError(RuntimeError):
    pass


def detect(event_dir, settings, roi):
    """Request one synchronized burst; failure is not a negative detection."""
    token = TOKEN_FILE.read_text(encoding='utf-8').strip()
    if len(token) < 32:
        raise LocalAIError('Local AI authentication token missing or invalid')
    relative = '/'.join(event_dir.parts[-2:])
    if len(event_dir.parts) < 2 or not all(part.replace('-', '').isdigit() for part in event_dir.parts[-2:]):
        raise LocalAIError('Unexpected burst folder naming')
    payload = {
        'photo_base': settings['local_ai_photo_root'],
        'folder': relative,
        'confidence': settings['local_ai_confidence'],
        'roi': list(roi),
        'timeout': settings['local_ai_timeout'],
        'identify_species': settings['local_ai_species_enabled'],
    }
    url = 'http://{}:{}/detect'.format(settings['local_ai_host'], settings['local_ai_port'])
    try:
        response = requests.post(url, json=payload,
                                 headers={'X-CatCam-Token': token},
                                 timeout=settings['local_ai_timeout'] + 35)
        response.raise_for_status()
        result = response.json()
    except (requests.RequestException, ValueError) as exc:
        raise LocalAIError('Pi 4 detection request failed: {}'.format(exc)) from exc
    if not isinstance(result, dict) or result.get('classification') not in ('bird','no_bird'):
        raise LocalAIError('Pi 4 returned invalid classification')
    if result['classification'] == 'bird':
        photo = result.get('photo')
        if not isinstance(photo, str) or photo not in ['{:02d}.jpg'.format(i) for i in range(1,7)]:
            raise LocalAIError('Pi 4 returned invalid bird photo')
    return result
