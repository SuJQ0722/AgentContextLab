"""Load the existing Hermes local-web service settings without persisting secrets."""
import json
import subprocess
from pathlib import Path
import yaml


def configure_web(root, env, config_path=None):
    source = Path(env.get('ACL_HERMES_WEB_CONFIG', root / 'hermes-agent/config.yaml'))
    cfg = yaml.safe_load(source.read_text())['web']['local_web']
    search = dict(cfg['search'])
    fetch = dict(cfg['fetch']['fetch_server'])
    selected = json.loads(Path(config_path or root / 'configs/experiment.json').read_text()).get('web', {})
    search['url'] = selected.get('search_host', search.get('url'))
    search['port'] = selected.get('search_port', search.get('port'))
    fetch['base_url'] = selected.get('fetch_base_url', fetch.get('base_url'))
    search['api_key'] = env.get('SERPER_API_KEY') or search.get('api_key', '')
    fetch['base_url'] = env.get('FETCH_SERVER_URL') or fetch.get('base_url', '')
    for field, key in [('jina_api_key', 'JINA_API_KEY'), ('llm_api_key', 'LLM_API_KEY')]:
        fetch[field] = env.get(key) or fetch.get(field, '')
    if not all([search.get('url'), search.get('port'), search.get('api_key'), fetch.get('base_url')]):
        raise ValueError('Hermes local-web configuration is incomplete')
    env['ACL_WEB_SECRETS'] = json.dumps({'search': search, 'fetch': fetch})
    env['DSH_WEB_SEARCH_PROVIDER'] = 'acl-serper-cache'
    env['DSH_WEB_FETCH_PROVIDER'] = 'acl-jina-reader'
    return {'config_source': str(source), 'search': 'Hermes Serper cache proxy',
            'fetch': 'Hermes Reader server (Jina fallback)',
            'search_endpoint': f"http://{search['url']}:{search['port']}/search",
            'fetch_endpoint': fetch['base_url'].rstrip('/') + '/fetch',
            'extract_mode': fetch.get('extract_mode', 'markdown')}


def validate_web(root, env):
    """Check both real backends before starting any model run; no LLM request."""
    code = """
      import {providers} from './plugins/dsh-local-web/index.mjs';
      const p=providers(JSON.parse(process.env.ACL_WEB_SECRETS),'outputs/preflight/web-metrics');
      const checks=await Promise.allSettled([
        p.search.search({query:'Example Domain IANA',maxResults:1}),
        p.fetch.fetch({url:'https://example.com'}),
      ]);
      const result=checks.map((r,i)=>({service:i?'fetch':'search',ok:r.status==='fulfilled',
        error:r.status==='rejected'?r.reason?.cause?.code??r.reason?.name:null}));
      for(let i=0;i<checks.length;i++) if(checks[i].status==='fulfilled') {
        const usable=i ? checks[i].value.body.content.trim().length>0 : checks[i].value.sources.length>0;
        if(!usable){result[i].ok=false;result[i].error='empty_evidence';}
      }
      console.log(JSON.stringify(result));
      if(result.some(r=>!r.ok)) process.exitCode=1;
    """
    result = subprocess.run(['node', '--input-type=module', '-e', code], cwd=root,
                            env=env, capture_output=True, text=True, timeout=200)
    try:
        checks = json.loads(result.stdout)
    except ValueError:
        checks = [{'ok': False, 'error': 'provider_preflight_process_failed'}]
    (root / 'outputs/preflight').mkdir(parents=True, exist_ok=True)
    (root / 'outputs/preflight/web-readiness.json').write_text(json.dumps(checks, indent=2))
    if result.returncode:
        raise RuntimeError('Web backend preflight failed: ' + json.dumps(checks))
    return checks
