#!/usr/bin/env python3
"""Add opt-in existing Transit mount support to vault-benchmark 0.3.0.
Preserves existing mounts/keys even if cleanup is accidentally enabled.
"""
from pathlib import Path
import sys
p=Path(sys.argv[1])/"benchmarktests/target_secret_transit.go"
s=p.read_text()
if 'hcl:"use_existing_mount,optional"' in s:
    print("Existing Transit mount support already installed")
    sys.exit(0)
def replace_once(old,new):
    global s
    if s.count(old)!=1: raise SystemExit("Unsupported source layout: "+repr(old[:100]))
    s=s.replace(old,new,1)
replace_once("type TransitTest struct {", "type TransitTest struct {\n\tpreserveMount bool")
replace_once("type TransitTestConfig struct {", 'type TransitTestConfig struct {\n\tUseExistingMount bool `hcl:"use_existing_mount,optional"`')
replace_once("func (t *TransitTest) Cleanup(client *api.Client) error {", "func (t *TransitTest) Cleanup(client *api.Client) error {\n\tif t.preserveMount { return nil }")
replace_once("\tsecretPath := mountName", '\tsecretPath := strings.Trim(mountName, "/")\n\tif t.config.UseExistingMount && topLevelConfig.RandomMounts {\n\t\treturn nil, fmt.Errorf("use_existing_mount requires random_mounts=false")\n\t}\n\tif t.config.UseExistingMount && secretPath == "" {\n\t\treturn nil, fmt.Errorf("use_existing_mount requires a nonempty mount_name")\n\t}')
a=s.index('\tt.logger.Trace(mountLogMessage("secrets", "transit", secretPath))')
b=s.index('\n\t// Generate our payload and context',a)
old=s[a:b]
old=old.replace('\n\tsetupLogger := t.logger.Named(secretPath)','')
s=s[:a]+ '\tsetupLogger := t.logger.Named(secretPath)\n\tif t.config.UseExistingMount {\n\t\tif err := t.prepareExistingMount(client, secretPath); err != nil { return nil, err }\n\t} else {\n'+old+'\n\t}\n'+s[b:]
needle='return &TransitTest{'
if s.count(needle)!=8: # Four constructors in init and four prepared targets.
    raise SystemExit("Unexpected TransitTest constructor count")
# Only multiline prepared targets need the ownership flag.
s=s.replace('return &TransitTest{\n','return &TransitTest{\n\t\t\tpreserveMount: t.config.UseExistingMount,\n')
s+='\n// prepareExistingMount validates resources without creating or updating them.\nfunc (t *TransitTest) prepareExistingMount(client *api.Client, path string) error {\n mounts, err := client.Sys().ListMounts()\n if err != nil { return fmt.Errorf("inspect existing transit mount: %w", err) }\n mount, ok := mounts[path+"/"]\n if !ok || mount.Type != "transit" { return fmt.Errorf("existing mount %q must exist and have type transit", path) }\n keyName := t.config.TransitConfigKeys.Name\n var operationKey string\n switch t.action {\n case "encrypt": operationKey = t.config.TransitConfigEncrypt.Name\n case "decrypt": operationKey = t.config.TransitConfigDecrypt.Name\n case "sign": operationKey = t.config.TransitConfigSign.Name\n case "verify": operationKey = t.config.TransitConfigVerify.Name\n }\n if operationKey != keyName { return fmt.Errorf("existing mount: operation key %q differs from keys.name %q", operationKey, keyName) }\n key, err := client.Logical().Read(filepath.Join(path, "keys", keyName))\n if err != nil { return fmt.Errorf("read existing transit key: %w", err) }\n if key == nil { return fmt.Errorf("existing transit key %q does not exist; no key was created", keyName) }\n if key.Data["type"] != t.config.TransitConfigKeys.Type || key.Data["derived"] != t.config.TransitConfigKeys.Derived {\n  return fmt.Errorf("existing key %q type/derived does not match benchmark config", keyName)\n }\n return nil\n}\n'
p.write_text(s)
print("Installed opt-in existing Transit mount support")
