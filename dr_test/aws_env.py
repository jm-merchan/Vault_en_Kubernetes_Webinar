#!/usr/bin/env python3
"""AWS resources for one Vault cluster that auto-unseals with KMS through AssumeRole.

    aws_env.py create <suffix> <credentials-file> <env-file>
    aws_env.py delete <suffix>

Least privilege: the bootstrap IAM user can only call sts:AssumeRole on the
role, and only the role can use the KMS key. Names are derived from <suffix>
("23" -> vault-autounseal-23, vault-kms-unseal-23, alias/vault-auto-unseal-23);
an empty suffix ("-") gives the unsuffixed names.

Provisioning credentials come from the CSV named by AWS_ADMIN_CSV (columns
"Access key ID" and "Secret access key"), or from the default boto3 chain when
AWS_ADMIN_CSV is not set. They are never written to the credentials file.
"""
import csv
import json
import os
import sys
import time

import boto3
from botocore.exceptions import ClientError

REGION = os.environ.get("REGION", "eu-west-3")


def names(suffix):
    tail = "" if suffix in ("", "-") else f"-{suffix}"
    return {
        "user": f"vault-autounseal{tail}",
        "role": f"vault-kms-unseal{tail}",
        "alias": f"alias/vault-auto-unseal{tail}",
        "policy": f"vault-autounseal{tail}-kms-policy",
        "inline": f"vault-assume-kms-role{tail}",
        "session": f"vault-auto-unseal{tail}",
    }


def admin_session():
    path = os.environ.get("AWS_ADMIN_CSV")
    if path:
        with open(path, encoding="utf-8-sig") as fh:
            row = next(csv.DictReader(fh))
        return boto3.Session(
            aws_access_key_id=row["Access key ID"].strip(),
            aws_secret_access_key=row["Secret access key"].strip(),
            region_name=REGION,
        )
    return boto3.Session(region_name=REGION)


def retry(fn, codes, attempts=12, wait=10):
    for attempt in range(1, attempts + 1):
        try:
            return fn()
        except ClientError as exc:
            code = exc.response["Error"]["Code"]
            if code not in codes or attempt == attempts:
                raise
            print(f"  waiting for IAM propagation ({code}, {attempt}/{attempts})", flush=True)
            time.sleep(wait)


def create(suffix, creds_file, env_file):
    n = names(suffix)
    session = admin_session()
    iam, kms, sts = session.client("iam"), session.client("kms"), session.client("sts")
    identity = sts.get_caller_identity()
    account = identity["Account"]
    user_arn = f"arn:aws:iam::{account}:user/{n['user']}"
    role_arn = f"arn:aws:iam::{account}:role/{n['role']}"
    if identity["Arn"] == user_arn:
        raise SystemExit("provision with an administrator identity, not the bootstrap user")

    try:
        iam.create_user(UserName=n["user"], Tags=[{"Key": "Purpose", "Value": "vault-auto-unseal"}])
        print(f"✓ IAM user {n['user']} created", flush=True)
        time.sleep(15)
    except ClientError as exc:
        if exc.response["Error"]["Code"] != "EntityAlreadyExists":
            raise
        for key in iam.list_access_keys(UserName=n["user"])["AccessKeyMetadata"]:
            iam.delete_access_key(UserName=n["user"], AccessKeyId=key["AccessKeyId"])
        print(f"✓ IAM user {n['user']} reused; old access keys deleted", flush=True)
    access_key = iam.create_access_key(UserName=n["user"])["AccessKey"]

    trust = {"Version": "2012-10-17", "Statement": [{
        "Effect": "Allow", "Principal": {"AWS": user_arn}, "Action": "sts:AssumeRole"}]}

    def ensure_role():
        try:
            iam.create_role(RoleName=n["role"], AssumeRolePolicyDocument=json.dumps(trust),
                            Description="Role assumed by Vault for AWS KMS auto-unseal",
                            MaxSessionDuration=3600,
                            Tags=[{"Key": "Purpose", "Value": "vault-auto-unseal"}])
            print(f"✓ IAM role {n['role']} created", flush=True)
            time.sleep(15)
        except ClientError as exc:
            if exc.response["Error"]["Code"] != "EntityAlreadyExists":
                raise
            iam.update_assume_role_policy(RoleName=n["role"], PolicyDocument=json.dumps(trust))
            print(f"✓ IAM role {n['role']} reused; trust updated", flush=True)

    retry(ensure_role, {"MalformedPolicyDocumentException"}, attempts=6)
    iam.put_user_policy(UserName=n["user"], PolicyName=n["inline"], PolicyDocument=json.dumps({
        "Version": "2012-10-17",
        "Statement": [{"Effect": "Allow", "Action": "sts:AssumeRole", "Resource": role_arn}]}))

    try:
        meta = kms.describe_key(KeyId=n["alias"])["KeyMetadata"]
        if meta["KeyState"] == "PendingDeletion":
            kms.cancel_key_deletion(KeyId=meta["KeyId"])
        if meta["KeyState"] in ("PendingDeletion", "Disabled"):
            kms.enable_key(KeyId=meta["KeyId"])
        print(f"✓ KMS key reused: {meta['KeyId']}", flush=True)
    except ClientError as exc:
        if exc.response["Error"]["Code"] != "NotFoundException":
            raise
        meta = kms.create_key(Description=f"Vault auto-unseal key ({n['alias']})",
                              KeyUsage="ENCRYPT_DECRYPT", Origin="AWS_KMS",
                              Tags=[{"TagKey": "Purpose", "TagValue": "vault-auto-unseal"}])["KeyMetadata"]
        kms.create_alias(AliasName=n["alias"], TargetKeyId=meta["KeyId"])
        print(f"✓ KMS key created: {meta['KeyId']} ({n['alias']})", flush=True)
    key_id, key_arn = meta["KeyId"], meta["Arn"]
    key_policy = {"Version": "2012-10-17", "Id": "vault-auto-unseal-key-policy", "Statement": [
        {"Sid": "EnableRootAccountFullAccess", "Effect": "Allow",
         "Principal": {"AWS": f"arn:aws:iam::{account}:root"}, "Action": "kms:*", "Resource": "*"},
        {"Sid": "AllowVaultAutoUnsealRole", "Effect": "Allow", "Principal": {"AWS": role_arn},
         "Action": ["kms:Encrypt", "kms:Decrypt", "kms:DescribeKey"], "Resource": "*"}]}
    retry(lambda: kms.put_key_policy(KeyId=key_id, PolicyName="default", Policy=json.dumps(key_policy)),
          {"MalformedPolicyDocumentException"}, attempts=6)

    policy_doc = json.dumps({"Version": "2012-10-17", "Statement": [{
        "Effect": "Allow", "Action": ["kms:Encrypt", "kms:Decrypt", "kms:DescribeKey"], "Resource": key_arn}]})
    policy_arn = f"arn:aws:iam::{account}:policy/{n['policy']}"
    try:
        iam.create_policy(PolicyName=n["policy"], PolicyDocument=policy_doc)
    except ClientError as exc:
        if exc.response["Error"]["Code"] != "EntityAlreadyExists":
            raise
        for version in iam.list_policy_versions(PolicyArn=policy_arn)["Versions"]:
            if not version["IsDefaultVersion"]:
                iam.delete_policy_version(PolicyArn=policy_arn, VersionId=version["VersionId"])
        iam.create_policy_version(PolicyArn=policy_arn, PolicyDocument=policy_doc, SetAsDefault=True)
    iam.attach_role_policy(RoleName=n["role"], PolicyArn=policy_arn)

    bootstrap = boto3.client("sts", aws_access_key_id=access_key["AccessKeyId"],
                             aws_secret_access_key=access_key["SecretAccessKey"])
    assumed = retry(lambda: bootstrap.assume_role(RoleArn=role_arn, RoleSessionName="vault-validation")["Credentials"],
                    {"AccessDenied", "InvalidClientTokenId"})
    retry(lambda: boto3.client("kms", region_name=REGION, aws_access_key_id=assumed["AccessKeyId"],
                               aws_secret_access_key=assumed["SecretAccessKey"],
                               aws_session_token=assumed["SessionToken"]).describe_key(KeyId=key_id),
          {"AccessDeniedException"})
    print("✓ AssumeRole + kms:DescribeKey validated with the bootstrap key", flush=True)

    os.makedirs(os.path.dirname(creds_file), exist_ok=True)
    fd = os.open(creds_file, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as fh:
        fh.write(f"[default]\naws_access_key_id={access_key['AccessKeyId']}\n"
                 f"aws_secret_access_key={access_key['SecretAccessKey']}\n\n"
                 f"[vault-bootstrap]\nrole_arn={role_arn}\nrole_session_name={n['session']}\n"
                 f"source_profile=default\n")
    with open(env_file, "w") as fh:
        fh.write(f"KMS_KEY_ID={key_id}\nROLE_ARN={role_arn}\nSESSION_NAME={n['session']}\n")
    print(f"✓ credentials file written (not printed); KMS key {key_id}", flush=True)


def delete(suffix):
    n = names(suffix)
    session = admin_session()
    iam, kms = session.client("iam"), session.client("kms")
    account = session.client("sts").get_caller_identity()["Account"]
    policy_arn = f"arn:aws:iam::{account}:policy/{n['policy']}"

    def attempt(label, fn):
        try:
            fn()
            print(f"✓ {label}", flush=True)
        except ClientError as exc:
            code = exc.response["Error"]["Code"]
            mark = "·" if code in ("NoSuchEntity", "NotFoundException") else "⚠"
            print(f"{mark} {label}: {code}", flush=True)

    try:
        for key in iam.list_access_keys(UserName=n["user"])["AccessKeyMetadata"]:
            attempt("access key deleted",
                    lambda k=key: iam.delete_access_key(UserName=n["user"], AccessKeyId=k["AccessKeyId"]))
        for name in iam.list_user_policies(UserName=n["user"])["PolicyNames"]:
            attempt(f"inline policy {name} deleted",
                    lambda p=name: iam.delete_user_policy(UserName=n["user"], PolicyName=p))
        for pol in iam.list_attached_user_policies(UserName=n["user"])["AttachedPolicies"]:
            attempt(f"policy {pol['PolicyName']} detached from user",
                    lambda p=pol: iam.detach_user_policy(UserName=n["user"], PolicyArn=p["PolicyArn"]))
    except ClientError as exc:
        print(f"· user {n['user']}: {exc.response['Error']['Code']}", flush=True)
    attempt(f"user {n['user']} deleted", lambda: iam.delete_user(UserName=n["user"]))
    try:
        for pol in iam.list_attached_role_policies(RoleName=n["role"])["AttachedPolicies"]:
            attempt(f"policy {pol['PolicyName']} detached from role",
                    lambda p=pol: iam.detach_role_policy(RoleName=n["role"], PolicyArn=p["PolicyArn"]))
        for name in iam.list_role_policies(RoleName=n["role"])["PolicyNames"]:
            attempt(f"inline role policy {name} deleted",
                    lambda p=name: iam.delete_role_policy(RoleName=n["role"], PolicyName=p))
    except ClientError as exc:
        print(f"· role {n['role']}: {exc.response['Error']['Code']}", flush=True)
    attempt(f"role {n['role']} deleted", lambda: iam.delete_role(RoleName=n["role"]))
    try:
        for version in iam.list_policy_versions(PolicyArn=policy_arn)["Versions"]:
            if not version["IsDefaultVersion"]:
                iam.delete_policy_version(PolicyArn=policy_arn, VersionId=version["VersionId"])
    except ClientError:
        pass
    attempt(f"policy {n['policy']} deleted", lambda: iam.delete_policy(PolicyArn=policy_arn))
    try:
        meta = kms.describe_key(KeyId=n["alias"])["KeyMetadata"]
    except ClientError as exc:
        print(f"· KMS {n['alias']}: {exc.response['Error']['Code']}", flush=True)
        return
    attempt(f"alias {n['alias']} deleted", lambda: kms.delete_alias(AliasName=n["alias"]))
    if meta["KeyState"] != "PendingDeletion":
        attempt(f"KMS key {meta['KeyId']} scheduled for deletion in 7 days",
                lambda: kms.schedule_key_deletion(KeyId=meta["KeyId"], PendingWindowInDays=7))


if __name__ == "__main__":
    if len(sys.argv) == 5 and sys.argv[1] == "create":
        create(sys.argv[2], sys.argv[3], sys.argv[4])
    elif len(sys.argv) == 3 and sys.argv[1] == "delete":
        delete(sys.argv[2])
    else:
        raise SystemExit(__doc__)
