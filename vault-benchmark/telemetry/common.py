import json,os,subprocess,urllib.request,ssl
from pathlib import Path
ROOT=Path(__file__).resolve().parent
CTX=os.getenv('KUBE_CONTEXT','workshop-k8s');NS=os.getenv('VB_NAMESPACE','vault')
def kub(*args,input=None):
 return subprocess.check_output(['kubectl','--context',CTX,'-n',NS,*args],input=input,stderr=subprocess.PIPE).decode()
def apply(obj):return kub('apply','-f','-',input=json.dumps(obj).encode())
def vault(path,data=None,method=None):
 context=ssl.create_default_context(cafile=os.getenv('VAULT_CACERT','/tmp/vault/vault.ca'))
 req=urllib.request.Request(os.getenv('VAULT_ADDR','https://127.0.0.1:8200')+'/v1/'+path,data=json.dumps(data).encode() if data is not None else None,method=method,headers={'X-Vault-Token':os.environ['VAULT_TOKEN'],'Content-Type':'application/json'})
 with urllib.request.urlopen(req,context=context,timeout=30) as r:
  body=r.read();return json.loads(body) if body else {}
def resource(kind,name,spec=None,**fields):
 o={'apiVersion':'v1','kind':kind,'metadata':{'name':name,'namespace':NS,'labels':{'app.kubernetes.io/part-of':'vault-benchmark-telemetry'}}}
 if spec is not None:o['spec']=spec
 o.update(fields);return o
