#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
source "$ROOT_DIR/scripts/aws/rds_pilot_common.sh"

require_command aws

aws rds describe-db-instances \
  --region "$AWS_REGION" \
  --db-instance-identifier "$BRAINRH_RDS_IDENTIFIER" \
  --query 'DBInstances[0].{Identifier:DBInstanceIdentifier,Status:DBInstanceStatus,Engine:Engine,Version:EngineVersion,Class:DBInstanceClass,Endpoint:Endpoint.Address,Port:Endpoint.Port,PubliclyAccessible:PubliclyAccessible,StorageEncrypted:StorageEncrypted,MultiAZ:MultiAZ,StorageType:StorageType,AllocatedStorage:AllocatedStorage,SubnetGroup:DBSubnetGroup.DBSubnetGroupName,VpcSecurityGroups:VpcSecurityGroups[*].VpcSecurityGroupId,DeletionProtection:DeletionProtection,BackupRetentionPeriod:BackupRetentionPeriod}' \
  --output table
