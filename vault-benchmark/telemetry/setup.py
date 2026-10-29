import base64,json,os,subprocess
from common import *
# Existing telemetry is enabled. Keep Vault's listener and credentials private.
config=json.loads(kub('get','cm','vault-config','-o','json'))['data']['extraconfig-from-values.hcl']
assert 'prometheus_retention_time' in config,'Enable Vault Prometheus telemetry before setup'
policy='path "sys/metrics" { capabilities = ["read", "list"] }'
vault('sys/policies/acl/vbb-prometheus',{'policy':policy})
token=vault('auth/token/create',{'policies':['vbb-prometheus'],'no_default_policy':True,'ttl':'24h','renewable':True,'display_name':'vbb-prometheus'})['auth']['client_token']
apply(resource('Secret','vbb-prometheus-auth',type='Opaque',data={'token':base64.b64encode(token.encode()).decode(),'ca.pem':base64.b64encode(Path(os.getenv('VAULT_CACERT','/tmp/vault/vault.ca')).read_bytes()).decode()}))
apply(resource('ServiceAccount','vbb-prometheus'))
role={'apiVersion':'rbac.authorization.k8s.io/v1','kind':'ClusterRole','metadata':{'name':'vbb-prometheus'},'rules':[{'apiGroups':[''],'resources':['nodes','nodes/proxy','pods','services','endpoints'],'verbs':['get','list','watch']}]}
apply(role);apply({'apiVersion':'rbac.authorization.k8s.io/v1','kind':'ClusterRoleBinding','metadata':{'name':'vbb-prometheus'},'roleRef':{'apiGroup':'rbac.authorization.k8s.io','kind':'ClusterRole','name':'vbb-prometheus'},'subjects':[{'kind':'ServiceAccount','name':'vbb-prometheus','namespace':NS}]})
apply(resource('ConfigMap','vbb-probe-code',data={x:(ROOT/x).read_text() for x in ['receiver.py','host_probe.py']}))
def svc(name,port):apply(resource('Service',name,{'selector':{'app':name},'ports':[{'port':port,'targetPort':port}]}))
def deploy(name,containers,volumes,extra=None):
 spec={'containers':containers,'volumes':volumes};spec.update(extra or {})
 apply({'apiVersion':'apps/v1','kind':'Deployment','metadata':{'name':name,'namespace':NS},'spec':{'strategy':{'type':'Recreate'},'replicas':1,'selector':{'matchLabels':{'app':name}},'template':{'metadata':{'labels':{'app':name,'app.kubernetes.io/part-of':'vault-benchmark-telemetry'}},'spec':spec}}})
code={'name':'code','configMap':{'name':'vbb-probe-code'}}
for i in range(3):
 name=f'vbb-socket-{i}'
 deploy(name,[{'name':'receiver','image':'python:3.13-alpine','command':['python','/code/receiver.py'],'ports':[{'containerPort':9102}], 'readinessProbe':{'httpGet':{'path':'/metrics','port':9102},'periodSeconds':2},'resources':{'requests':{'cpu':'20m','memory':'24Mi'},'limits':{'memory':'128Mi'}},'volumeMounts':[{'name':'code','mountPath':'/code','readOnly':True},{'name':'audit','mountPath':'/vault/audit'}]}],[code,{'name':'audit','persistentVolumeClaim':{'claimName':f'audit-vault-{i}'}}],{'nodeSelector':{'kubernetes.io/hostname':'workshop-k8s'},'securityContext':{'runAsUser':100,'runAsGroup':1000,'runAsNonRoot':True,'fsGroup':1000}})
 svc(name,9102)
vols=[code,{'name':'cgroup','hostPath':{'path':'/sys/fs/cgroup','type':'Directory'}}]+[{'name':f'audit-{i}','persistentVolumeClaim':{'claimName':f'audit-vault-{i}'}} for i in range(3)]
mounts=[{'name':'code','mountPath':'/code','readOnly':True},{'name':'cgroup','mountPath':'/host-cgroup','readOnly':True}]+[{'name':f'audit-{i}','mountPath':f'/audit-{i}','readOnly':True} for i in range(3)]
deploy('vbb-host-probe',[{'name':'probe','image':'python:3.13-alpine','command':['python','/code/host_probe.py'],'resources':{'requests':{'cpu':'10m','memory':'24Mi'},'limits':{'memory':'96Mi'}},'volumeMounts':mounts}],vols,{'nodeSelector':{'kubernetes.io/hostname':'workshop-k8s'}});svc('vbb-host-probe',9103)
deploy('vbb-node-exporter',[{'name':'node-exporter','image':'prom/node-exporter:v1.9.1','args':['--path.procfs=/host/proc','--path.sysfs=/host/sys','--path.rootfs=/host/root','--collector.disable-defaults','--collector.cpu','--collector.meminfo','--collector.diskstats','--collector.pressure','--collector.vmstat','--collector.loadavg'],'resources':{'requests':{'cpu':'10m','memory':'32Mi'},'limits':{'memory':'96Mi'}},'volumeMounts':[{'name':x,'mountPath':'/host/'+x,'readOnly':True} for x in ['proc','sys','root']]}],[{'name':'proc','hostPath':{'path':'/proc'}},{'name':'sys','hostPath':{'path':'/sys'}},{'name':'root','hostPath':{'path':'/'}}]);svc('vbb-node-exporter',9100)
scrapes=[{'job_name':'vault','scheme':'https','metrics_path':'/v1/sys/metrics','params':{'format':['prometheus']},'authorization':{'credentials_file':'/auth/token'},'tls_config':{'ca_file':'/auth/ca.pem','server_name':'vault-0.vault-internal'},'static_configs':[{'targets':[f'vault-{i}.vault-internal:8200'],'labels':{'pod':f'vault-{i}'}} for i in range(3)]},
 {'job_name':'kubelet-cadvisor','scheme':'https','metrics_path':'/api/v1/nodes/workshop-k8s/proxy/metrics/cadvisor','authorization':{'credentials_file':'/var/run/secrets/kubernetes.io/serviceaccount/token'},'tls_config':{'ca_file':'/var/run/secrets/kubernetes.io/serviceaccount/ca.crt'},'static_configs':[{'targets':['kubernetes.default.svc:443']}],'honor_timestamps':False},
 {'job_name':'node','static_configs':[{'targets':['vbb-node-exporter:9100']}]},
 {'job_name':'host-quota','static_configs':[{'targets':['vbb-host-probe:9103']}]},
 {'job_name':'socket','static_configs':[{'targets':[f'vbb-socket-{i}:9102'],'labels':{'pod':f'vault-{i}'}} for i in range(3)]}]
resource_scrape=dict(scrapes[1]);resource_scrape['job_name']='kubelet-resource';resource_scrape['metrics_path']='/api/v1/nodes/workshop-k8s/proxy/metrics/resource';scrapes.append(resource_scrape)
config={'global':{'scrape_interval':'5s','scrape_timeout':'4s','evaluation_interval':'5s'},'scrape_configs':scrapes}
apply(resource('ConfigMap','vbb-prometheus-config',data={'prometheus.yml':json.dumps(config)}))
apply(resource('PersistentVolumeClaim','vbb-prometheus-data',{'accessModes':['ReadWriteOnce'],'resources':{'requests':{'storage':'2Gi'}}}))
deploy('vbb-prometheus',[{'name':'prometheus','image':'prom/prometheus:v3.5.0','args':['--config.file=/etc/prometheus/prometheus.yml','--storage.tsdb.path=/prometheus','--storage.tsdb.retention.time=3d','--storage.tsdb.retention.size=1GB'],'resources':{'requests':{'cpu':'100m','memory':'256Mi'},'limits':{'memory':'768Mi'}},'volumeMounts':[{'name':'config','mountPath':'/etc/prometheus','readOnly':True},{'name':'auth','mountPath':'/auth','readOnly':True},{'name':'data','mountPath':'/prometheus'}]}],[{'name':'config','configMap':{'name':'vbb-prometheus-config'}},{'name':'auth','secret':{'secretName':'vbb-prometheus-auth'}},{'name':'data','persistentVolumeClaim':{'claimName':'vbb-prometheus-data'}}],{'serviceAccountName':'vbb-prometheus','securityContext':{'fsGroup':65534}});svc('vbb-prometheus',9090)
print('Prometheus, exporters and three persistent UNIX receivers configured; no Vault restart.')
