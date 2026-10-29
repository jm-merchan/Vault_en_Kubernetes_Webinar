"""Add a 20-second audit failure window to the retained external series.

This retains the original 60-second metric, whose initial samples can overlap
device setup even when the resource summary starts at benchmark + 20 seconds.
"""
import json
import os
from pathlib import Path
from common import ROOT
from collect import collect

state=Path(os.environ.get('VBB_STATE_DIR','/tmp/vault/vbb-tcp-external'))
os.environ['VBB_TCP_ADDRESS']=json.loads((state/'deployment.json').read_text())['address']
base=ROOT.parent/'runs'
plan=json.loads((base/'20261029-tcp-external-plan.json').read_text())
added=0
for case in plan:
    if case.get('status')!='passed':continue
    folder=base/case['run_id']
    telemetry=json.loads((folder/'telemetry.json').read_text())
    name='audit_failures_during_measurement'
    if name in telemetry['queries']:continue
    result=json.loads((folder/'result.json').read_text())
    extra=collect(result['start'],result['end'],'unused',names=[name])
    assert extra['queries'][name]['summary'],case['run_id']
    telemetry['queries'].update(extra['queries'])
    (folder/'telemetry.json').write_text(json.dumps(telemetry,indent=2)+'\n')
    added+=1
print(f'Added historical audit failure windows to {added} cases; original metrics retained')
