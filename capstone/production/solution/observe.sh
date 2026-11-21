#!/usr/bin/env bash
# The dashboard and two alarms for the deployed assistant. Run after deploy.sh, once /health answers
# and a few questions have been asked (the log group and the metrics appear with the first requests).
set -euo pipefail
source labs/deploy/aws-vars.sh
set -a; source "$(dirname "$0")/service.env"; set +a
LOG=$(aws logs describe-log-groups --log-group-name-prefix /aws/ecs/$CLUSTER/ --query 'logGroups[0].logGroupName' --output text)
DIMS="Name=Service,Value=shopkart-copilot Name=Model,Value=$MODEL"

# The tracing lab's dashboard: P95 latency, requests and errors, cost, tokens, the slowest requests
# with their trace IDs, and cost by prompt version. Same metric names, so it works unchanged.
aws cloudwatch put-dashboard --dashboard-name shopkart-copilot \
  --dashboard-body "$(sed "s|LOG_GROUP|$LOG|" labs/tracing/dashboard.json)" --query 'DashboardValidationMessages'

# Slow: P95 of the whole answer above 8 s for 10 minutes. (There's no first token here:
# the checked answer arrives in one piece, so the full answer is what the customer waits for.)
aws cloudwatch put-metric-alarm --alarm-name shopkart-docs-latency-p95 \
  --alarm-description "P95 answer time above 8 s for 10 minutes. Check: the slowest traces (retrieve or chat span?), CPU, the provider's status page." \
  --namespace ShopKart/Copilot --metric-name LatencyMs --dimensions $DIMS \
  --extended-statistic p95 --period 300 --evaluation-periods 2 --threshold 8000 \
  --comparison-operator GreaterThanThreshold --treat-missing-data notBreaching

# Expensive: more than $0.25 of model spend in one hour (a quarter of the daily cap). The app's own
# ladder protects the money; this alarm tells a person early, while there's still time to look.
aws cloudwatch put-metric-alarm --alarm-name shopkart-docs-cost-hour \
  --alarm-description "Model spend above \$0.25 in an hour. Check: /budget, the cost-by-prompt-version table, the top users in the logs." \
  --namespace ShopKart/Copilot --metric-name CostUSD --dimensions $DIMS \
  --statistic Sum --period 3600 --evaluation-periods 1 --threshold 0.25 \
  --comparison-operator GreaterThanThreshold --treat-missing-data notBreaching
echo "dashboard + 2 alarms for $LOG"
