"""Export PromQL and raw samples. Missing telemetry is never coerced to zero."""
import json,math,os,statistics,urllib.parse,urllib.request,time
PROM=os.getenv('VBB_PROM_URL','http://127.0.0.1:19090')
def api(path,params=None):
 url=PROM+'/api/v1/'+path+('?' + urllib.parse.urlencode(params) if params else '')
 with urllib.request.urlopen(url,timeout=30) as r:d=json.load(r)
 if d['status']!='success':raise RuntimeError(str(d))
 return d['data']
def queries(pod):
 cpu='rate(container_cpu_usage_seconds_total{namespace="vault",container!="",container!="POD"}[20s])'
 result={
 'host_cpu_cores':'rate(vbb_host_cpu_usage_usec_total[20s])/1e6',
 'host_cpu_quota_cores':'vbb_host_cpu_quota_cores',
 'host_throttled_periods_pct':'100*rate(vbb_host_cpu_nr_throttled_total[20s])/clamp_min(rate(vbb_host_cpu_nr_periods_total[20s]),0.001)',
 'host_throttled_seconds_per_second':'rate(vbb_host_cpu_throttled_usec_total[20s])/1e6',
 'host_memory_bytes':'vbb_host_memory_current_bytes','host_memory_limit_bytes':'vbb_host_memory_max_bytes',
 'host_cpu_pressure_pct':'100*rate(vbb_host_cpu_pressure_seconds_total{stall="some"}[20s])',
 'host_io_pressure_pct':'100*rate(vbb_host_io_pressure_seconds_total{stall="some"}[20s])',
 'host_memory_pressure_pct':'100*rate(vbb_host_memory_pressure_seconds_total{stall="some"}[20s])',
 'host_oom_events':'increase(vbb_host_memory_events_oom_kill_total[60s])',
 'cpu_by_namespace':'sum by(namespace)(rate(container_cpu_usage_seconds_total{container!="",container!="POD"}[20s]))',
 'cpu_system_pods':'sum by(namespace,pod,container)(rate(container_cpu_usage_seconds_total{namespace!="vault",container!="",container!="POD"}[20s]))',
 'cpu_by_container':'sum by(pod,container)('+cpu+')',
 'vault_cpu_cores':'sum('+cpu.replace('container!="",container!="POD"','container="vault"')+')',
 'benchmark_cpu_cores':'sum('+cpu.replace('container!="",container!="POD"',f'container="vault-benchmark",pod="{pod}"')+')',
 'receiver_cpu_cores':'sum('+cpu.replace('container!="",container!="POD"','container="receiver"')+')',
 'rotator_cpu_cores':'sum('+cpu.replace('container!="",container!="POD"','container="auditlog-rotator"')+')',
 'prometheus_cpu_cores':'sum('+cpu.replace('container!="",container!="POD"','container="prometheus"')+')',
 'monitoring_cpu_cores':'sum('+cpu.replace('container!="",container!="POD"','pod=~"vbb-.*",container!="",container!="POD"')+')',
 'memory_by_container':'sum by(pod,container)(container_memory_working_set_bytes{namespace="vault",container!="",container!="POD"})',
 'vault_heap_alloc_bytes':'sum(vault_runtime_alloc_bytes)',
 'vault_runtime_sys_bytes':'sum(vault_runtime_sys_bytes)',
 'vault_gc_pause_seconds_per_second':'sum(rate(vault_runtime_total_gc_pause_ns[20s]))/1e9',
 'vault_gc_runs_per_second':'sum(rate(vault_runtime_total_gc_runs[20s]))',
 'vault_memory_bytes':'sum(container_memory_working_set_bytes{namespace="vault",container="vault"})',
 'container_throttled_seconds_per_second':'sum by(pod,container)(rate(container_cpu_cfs_throttled_seconds_total{namespace="vault",container!="",container!="POD"}[20s]))',
 'disk_iops':'rate(node_disk_reads_completed_total{device="vda"}[20s])+rate(node_disk_writes_completed_total{device="vda"}[20s])',
 'disk_write_bytes_per_second':'rate(node_disk_written_bytes_total{device="vda"}[20s])',
 'disk_busy_pct':'100*rate(node_disk_io_time_seconds_total{device="vda"}[20s])',
 'disk_queue_depth':'rate(node_disk_io_time_weighted_seconds_total{device="vda"}[20s])',
 'disk_await_ms':'1000*(rate(node_disk_read_time_seconds_total{device="vda"}[20s])+rate(node_disk_write_time_seconds_total{device="vda"}[20s])) / clamp_min(rate(node_disk_reads_completed_total{device="vda"}[20s])+rate(node_disk_writes_completed_total{device="vda"}[20s]),0.001)',
 'audit_request_ms':'sum(rate(vault_audit_log_request_sum[20s]))/clamp_min(sum(rate(vault_audit_log_request_count[20s])),0.001)',
 'audit_response_ms':'sum(rate(vault_audit_log_response_sum[20s]))/clamp_min(sum(rate(vault_audit_log_response_count[20s])),0.001)',
 'audit_device_request_ms':'sum(rate(vault_audit_vbb__log_request_sum[20s]))/clamp_min(sum(rate(vault_audit_vbb__log_request_count[20s])),0.001)',
 'audit_device_response_ms':'sum(rate(vault_audit_vbb__log_response_sum[20s]))/clamp_min(sum(rate(vault_audit_vbb__log_response_count[20s])),0.001)',
 'audit_requests_per_node':'sum by(pod)(rate(vault_audit_log_request_count[20s]))',
 'vault_requests_per_node':'sum by(pod)(rate(vault_core_handle_request_count[20s]))',
 'audit_failures':'sum(increase(vault_audit_log_request_failure[60s]))+sum(increase(vault_audit_log_response_failure[60s]))',
 'socket_bytes_per_second':'sum(rate(vbb_socket_bytes_written_total[20s]))',
 'socket_entries_per_second':'sum(rate(vbb_socket_entries_written_total[20s]))',
 'socket_write_errors':'sum(increase(vbb_socket_write_errors_total[60s]))',
 'audit_file_bytes':'vbb_host_audit_files_bytes',
 'audit_rotation_mtime':'vbb_host_audit_last_rotation_mtime_seconds',
 'target_up':'up',
 }
 if os.getenv('VBB_TCP_ADDRESS'):
  result.update({
   'audit_failures_during_measurement':'sum(increase(vault_audit_log_request_failure[20s]))+sum(increase(vault_audit_log_response_failure[20s]))',
   'vm_cpu_cores':'sum(rate(node_cpu_seconds_total{mode!~\"idle|iowait|guest|guest_nice\"}[20s]))',
   'vm_memory_available_bytes':'node_memory_MemAvailable_bytes',
   'external_cpu_cores':'rate(vbb_external_cpu_usage_usec_total[20s])/1e6',
   'external_cpu_quota_cores':'vbb_external_cpu_quota_cores',
   'external_throttled_periods_pct':'100*rate(vbb_external_cpu_nr_throttled_total[20s])/clamp_min(rate(vbb_external_cpu_nr_periods_total[20s]),0.001)',
   'external_memory_bytes':'vbb_external_memory_current_bytes',
   'external_cpu_pressure_pct':'100*rate(vbb_external_cpu_pressure_seconds_total{stall="some"}[20s])',
   'external_io_pressure_pct':'100*rate(vbb_external_io_pressure_seconds_total{stall="some"}[20s])',
   'external_memory_pressure_pct':'100*rate(vbb_external_memory_pressure_seconds_total{stall="some"}[20s])',
   'external_write_bytes_per_second':'sum(rate(vbb_external_io_wbytes_total[20s]))',
   'external_write_iops':'sum(rate(vbb_external_io_wios_total[20s]))',
   'external_received_bytes_per_second':'rate(vbb_external_bytes_written_total[20s])',
   'external_entries_per_second':'rate(vbb_external_entries_written_total[20s])',
   'external_write_errors':'increase(vbb_external_write_errors_total[60s])',
   'external_compression_cpu_cores':'rate(vbb_external_compression_cpu_seconds_total[20s])',
   'external_compression_active':'vbb_external_compression_active',
   'external_oom_kills':'increase(vbb_external_memory_events_oom_kill_total[60s])',
  })
 if os.getenv('VBB_UDP_ADDRESS'):
  result.update({
   'audit_failures_during_measurement':'sum(increase(vault_audit_log_request_failure[20s]))+sum(increase(vault_audit_log_response_failure[20s]))',
   'udp_cpu_cores':'rate(vbb_udp_cpu_usage_usec_total[20s])/1e6',
   'udp_cpu_quota_cores':'vbb_udp_cpu_quota_cores',
   'udp_memory_bytes':'vbb_udp_memory_current_bytes',
   'udp_received_bytes_per_second':'rate(vbb_udp_bytes_written_total[20s])',
   'udp_datagrams_per_second':'rate(vbb_udp_datagrams_total[20s])',
   'udp_write_errors':'increase(vbb_udp_write_errors_total[60s])',
   'udp_truncated_datagrams':'increase(vbb_udp_truncated_datagrams_total[60s])',
   'udp_kernel_receive_errors':'increase(vbb_udp_kernel_inerrors_total[60s])',
   'udp_kernel_receive_buffer_errors':'increase(vbb_udp_kernel_rcvbuferrors_total[60s])',
   'udp_kernel_no_ports':'increase(vbb_udp_kernel_noports_total[60s])',
  })
 return result

def collect(start,end,pod,names=None):
 result={'start':start,'end':end,'rate_window_seconds':20,'scrape_interval_seconds':5,'summary_window':'start+20s to end (avoid mixing setup/previous test)','queries':{}}
 for name,q in queries(pod).items():
  if names is not None and name not in names:continue
  try:
   d=api('query_range',{'query':q,'start':start-20,'end':end+5,'step':5});summary=[]
   for series in d['result']:
    v=[float(v) for t,v in series['values'] if start+20<=t<=end and math.isfinite(float(v))]
    summary.append({'labels':series['metric'],'samples':len(v),'mean':statistics.fmean(v) if v else None,'max':max(v) if v else None,'min':min(v) if v else None})
   result['queries'][name]={'promql':q,'summary':summary,'data':d}
  except Exception as e:result['queries'][name]={'promql':q,'error':str(e),'summary':[]}
 return result
