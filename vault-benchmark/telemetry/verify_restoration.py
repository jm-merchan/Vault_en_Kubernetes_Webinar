"""Verify the saved audit configuration is restored without printing credentials."""
import json
import sys
from datetime import datetime, timezone

from common import ROOT, kub, vault
from scenarios import STATE, audit

suite = sys.argv[1] if len(sys.argv) > 1 else '20261028-prometheus-final'
state = json.loads((STATE / 'original.json').read_text())
current = audit()
errors = []
if not state.get('restored'):
    errors.append('Session not marked restored')
if set(current) != set(state['audit']):
    errors.append('Audit device names differ from original state')
for name, original in state['audit'].items():
    if name not in current or any(current[name].get(k) != original.get(k)
                                  for k in ['type', 'description', 'local', 'options']):
        errors.append('Audit configuration differs: ' + name)
tune = vault('sys/mounts/transit/tune')['data']
if tune.get('audit_non_hmac_response_keys', []) != state['tune'].get('audit_non_hmac_response_keys', []):
    errors.append('Transit response HMAC tuning differs')
pods = json.loads(kub('get', 'pods', '-l', 'app.kubernetes.io/name=vault', '-o', 'json'))['items']
pod_status = []
for p in pods:
    containers = [{k: c.get(k) for k in ['name', 'ready', 'restartCount']}
                  for c in p['status'].get('containerStatuses', [])]
    if not containers or not all(c['ready'] for c in containers):
        errors.append('Vault pod not ready: ' + p['metadata']['name'])
    pod_status.append({'pod': p['metadata']['name'], 'uid': p['metadata']['uid'],
                       'containers': containers})
if len(pods) != 3:
    errors.append('Expected three Vault pods')
result = {
    'suite_id': suite,
    'checked_at': datetime.now(timezone.utc).isoformat(),
    'passed': not errors,
    'errors': errors,
    'audit_device_names': sorted(current),
    'original_audit_configuration_matches': not any('Audit' in x for x in errors),
    'transit_response_non_hmac_keys': tune.get('audit_non_hmac_response_keys', []),
    'pods': pod_status,
    'note': 'Original audit devices were recreated with new HMAC salts, as authorized. Transit/orders and monitoring remain for inspection.'
}
out = ROOT.parent / 'runs' / f'{suite}-restoration-verification.json'
out.write_text(json.dumps(result, indent=2) + '\n')
print(json.dumps(result, indent=2))
sys.exit(bool(errors))
