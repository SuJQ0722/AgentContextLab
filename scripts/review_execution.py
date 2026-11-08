"""The user's explicit review-before-run boundary for the repaired version."""
import ipaddress
import json
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
VERSION = 'hermes-parity-v3'


def loopback(url):
    host = urlsplit(url).hostname
    if host == 'localhost':
        return True
    try:
        return ipaddress.ip_address(host or '').is_loopback
    except ValueError:
        return False


def enforce(cfg, env, out, *, offline_fixture=False):
    """Reject paid runs before any network call while the user review is pending."""
    if cfg.get('execution_version') != VERSION:
        raise ValueError('Repaired workers require a separately versioned configuration')
    out = Path(out).resolve()
    if not offline_fixture:
        old_roots = [ROOT/'outputs/campaigns/bc100-r3-all-strategies',
                     ROOT/'outputs/campaigns/rq3-deepseek-bc100-r3',
                     ROOT/'outputs/experiment3/controlled-native-v2']
        if any(out.is_relative_to(p) for p in old_roots):
            raise ValueError('Never place repaired-version results in a frozen historical campaign')
        if (ROOT/'outputs/PAUSED_BY_USER.json').exists():
            raise ValueError('Experiments are paused by the user; review is required before resuming')
        if cfg.get('review_approved') is not True:
            raise ValueError('The repaired experiment configuration has not been approved')
        return
    if not out.is_relative_to(ROOT/'outputs/preflight'):
        raise ValueError('Offline fixtures must write under outputs/preflight')
    web = cfg.get('web', {})
    if not all(loopback(url) for url in [env.get('TOKENHUB_BASE_URL', ''),
                web.get('fetch_base_url', ''), 'http://'+str(web.get('search_host', ''))]):
        raise ValueError('Offline fixture model and web endpoints must all be loopback')


def enforce_resolved_web(env, *, offline_fixture=False):
    """Validate final provider settings after environment/config overrides."""
    if not offline_fixture:
        return
    selected = json.loads(env.get('ACL_WEB_SECRETS', '{}'))
    search = selected.get('search', {})
    fetch = selected.get('fetch', {})
    effective_fetch = env.get('FETCH_SERVER_URL') or fetch.get('base_url', '')
    if not all(loopback(url) for url in ('http://' + str(search.get('url', '')), effective_fetch)):
        raise ValueError('Resolved offline fixture web endpoints must all be loopback')
    if str(fetch.get('extract_mode', 'markdown')).strip().lower() != 'text':
        raise ValueError('Offline fixture Reader must use explicit text mode without a model')
