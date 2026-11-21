#!/usr/bin/env bash
# Delete what the cloud labs created, so nothing keeps billing you.
#
#   bash labs/deploy/teardown.sh service   # Part 1: the ECS Express service, its load balancer, logs
#   bash labs/deploy/teardown.sh lambda    # Part 2: the Lambda functions, their URLs and logs
#   bash labs/deploy/teardown.sh all       # everything: also images, secrets, roles, the dashboard,
#                                          # the alarm and the ticket table (mcp-remote)
#
# Safe to run twice: whatever is already gone is skipped. It ends with leftovers.sh,
# which lists anything still there.
set -uo pipefail
export AWS_REGION=${AWS_REGION:-ap-southeast-2} AWS_DEFAULT_REGION=${AWS_REGION:-ap-southeast-2} AWS_PAGER=""
WHAT=${1:-all}
CLUSTER=${CLUSTER:-shopkart}
q() { aws "$@" 2>/dev/null; }   # quiet: "not found" is fine here
say() { printf '%s\n' "- $*"; }

delete_service() {
  for arn in $(q ecs list-services --cluster "$CLUSTER" --query 'serviceArns[]' --output text); do
    say "deleting ECS Express service ${arn##*/} (the load balancer goes with it; takes a few minutes)"
    q ecs delete-express-gateway-service --service-arn "$arn" >/dev/null
  done
  # Wait until each service is INACTIVE: only then are its tasks and load balancer gone.
  for _ in $(seq 1 80); do
    busy=$(q ecs describe-services --cluster "$CLUSTER" --services ${SERVICE:-shopkart-copilot} \
      --query 'services[?status!=`INACTIVE`] | length(@)' --output text)
    [ "${busy:-0}" = 0 ] && break
    sleep 15
  done
  for lg in $(q logs describe-log-groups --log-group-name-prefix "/aws/ecs/$CLUSTER/" --query 'logGroups[].logGroupName' --output text); do
    say "deleting log group $lg"; q logs delete-log-group --log-group-name "$lg"
  done
  # Task definitions: Express names the family <cluster>-<service>. Deregister, then delete.
  for fam in $(q ecs list-task-definition-families --family-prefix "$CLUSTER-" --query 'families[]' --output text); do
    for td in $(q ecs list-task-definitions --family-prefix "$fam" --status ACTIVE --query 'taskDefinitionArns[]' --output text); do
      q ecs deregister-task-definition --task-definition "$td" >/dev/null
    done
    tds=$(q ecs list-task-definitions --family-prefix "$fam" --status INACTIVE --query 'taskDefinitionArns[]' --output text)
    [ -n "$tds" ] && { say "deleting task definitions of $fam"; q ecs delete-task-definitions --task-definitions $tds >/dev/null; }
  done
  if [ "$(q ecs describe-clusters --clusters "$CLUSTER" --query 'clusters[0].status' --output text)" = ACTIVE ]; then
    say "deleting cluster $CLUSTER"; q ecs delete-cluster --cluster "$CLUSTER" >/dev/null
  fi
}

sweep_logs() {
  # Late log lines can re-create a log group a few seconds after its function or task is gone.
  for lg in $(q logs describe-log-groups --log-group-name-prefix /aws/lambda/shopkart- --query 'logGroups[].logGroupName' --output text) \
            $(q logs describe-log-groups --log-group-name-prefix "/aws/ecs/$CLUSTER/" --query 'logGroups[].logGroupName' --output text); do
    say "deleting log group $lg"; q logs delete-log-group --log-group-name "$lg"
  done
}

delete_lambdas() {
  for fn in $(q lambda list-functions --query 'Functions[?starts_with(FunctionName, `shopkart-`)].FunctionName' --output text); do
    say "deleting Lambda function $fn (and its function URL)"
    q lambda delete-function-url-config --function-name "$fn"
    q lambda delete-function --function-name "$fn" >/dev/null
  done
  sleep 10
  sweep_logs
}

delete_shared() {
  for repo in $(q ecr describe-repositories --query 'repositories[?starts_with(repositoryName, `shopkart-`)].repositoryName' --output text); do
    say "deleting ECR repository $repo and its images"; q ecr delete-repository --repository-name "$repo" --force >/dev/null
  done
  for s in $(q secretsmanager list-secrets --query 'SecretList[?starts_with(Name, `shopkart/`)].Name' --output text); do
    say "deleting secret $s (no recovery window)"; q secretsmanager delete-secret --secret-id "$s" --force-delete-without-recovery >/dev/null
  done
  for t in $(q dynamodb list-tables --query 'TableNames[?starts_with(@, `shopkart-`)]' --output text); do
    say "deleting DynamoDB table $t"; q dynamodb delete-table --table-name "$t" >/dev/null
  done
  for d in $(q cloudwatch list-dashboards --dashboard-name-prefix shopkart --query 'DashboardEntries[].DashboardName' --output text); do
    say "deleting dashboard $d"; q cloudwatch delete-dashboards --dashboard-names "$d"
  done
  alarms=$(q cloudwatch describe-alarms --alarm-name-prefix shopkart --query 'MetricAlarms[].AlarmName' --output text)
  [ -n "$alarms" ] && { say "deleting alarms"; q cloudwatch delete-alarms --alarm-names $alarms; }
  for role in $(q iam list-roles --query 'Roles[?starts_with(RoleName, `shopkart-`)].RoleName' --output text); do
    say "deleting IAM role $role"
    for p in $(q iam list-attached-role-policies --role-name "$role" --query 'AttachedPolicies[].PolicyArn' --output text); do
      q iam detach-role-policy --role-name "$role" --policy-arn "$p"
    done
    for p in $(q iam list-role-policies --role-name "$role" --query 'PolicyNames[]' --output text); do
      q iam delete-role-policy --role-name "$role" --policy-name "$p"
    done
    q iam delete-role --role-name "$role"
  done
}

case "$WHAT" in
  service) delete_service ;;
  lambda) delete_lambdas ;;
  all) delete_service; delete_lambdas; delete_shared; sleep 10; sweep_logs ;;
  *) echo "usage: $0 service|lambda|all" >&2; exit 2 ;;
esac
echo
bash "$(dirname "$0")/leftovers.sh"
