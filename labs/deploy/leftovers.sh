#!/usr/bin/env bash
# List everything the cloud labs might have left behind. Every line should say "none".
#   bash labs/deploy/leftovers.sh
set -uo pipefail
export AWS_REGION=${AWS_REGION:-ap-southeast-2} AWS_DEFAULT_REGION=${AWS_REGION:-ap-southeast-2} AWS_PAGER=""
show() { printf '%-22s %s\n' "$1" "${2:-none}"; }
t() { aws "$@" --output text 2>/dev/null | tr '\t' ' '; }

show "ECS clusters:"       "$(t ecs list-clusters --query 'clusterArns[]')"
show "ECS services:"       "$(t ecs list-services --cluster shopkart --query 'serviceArns[]')"
show "Load balancers:"     "$(t elbv2 describe-load-balancers --query 'LoadBalancers[].LoadBalancerName')"
show "Target groups:"      "$(t elbv2 describe-target-groups --query 'TargetGroups[].TargetGroupName')"
show "Task definitions:"   "$(for f in $(t ecs list-task-definition-families --family-prefix shopkart- --query 'families[]'); do
  t ecs list-task-definitions --family-prefix "$f" --query 'taskDefinitionArns[]'; t ecs list-task-definitions --family-prefix "$f" --status INACTIVE --query 'taskDefinitionArns[]'; done | xargs)"
show "ECR repositories:"   "$(t ecr describe-repositories --query 'repositories[].repositoryName')"
show "Lambda functions:"   "$(t lambda list-functions --query 'Functions[].FunctionName')"
show "Secrets:"            "$(t secretsmanager list-secrets --query 'SecretList[].Name')"
show "Log groups:"         "$(t logs describe-log-groups --query 'logGroups[].logGroupName')"
show "DynamoDB tables:"    "$(t dynamodb list-tables --query 'TableNames[]')"
show "Dashboards:"         "$(t cloudwatch list-dashboards --query 'DashboardEntries[].DashboardName')"
show "Alarms:"             "$(t cloudwatch describe-alarms --query 'MetricAlarms[].AlarmName')"
show "IAM roles (shopkart):" "$(t iam list-roles --query 'Roles[?starts_with(RoleName, `shopkart-`)].RoleName')"
