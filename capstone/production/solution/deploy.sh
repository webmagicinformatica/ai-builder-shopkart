#!/usr/bin/env bash
# Deploy the document assistant to ECS Express Mode: the deploy lab's commands, with this
# project's image and settings. Run from the repo root, after the deploy lab's one-time setup
# (the ECR repository, the secret, the two roles and the cluster: labs/deploy/README.md, steps 3-5).
#
#   bash capstone/production/solution/deploy.sh            # create the service
#   bash capstone/production/solution/deploy.sh update     # roll out a new image or new settings
#   bash labs/deploy/teardown.sh all                       # when you're done: delete everything
set -euo pipefail
HERE=$(dirname "$0")
source labs/deploy/aws-vars.sh
set -a; source "$HERE/service.env"; set +a
export IMAGE=$REGISTRY/$REPO:docs-$TAG

# 1. Build for the cloud's CPU type, and push. The tag is the git commit: you know what's running.
docker build --platform linux/amd64 --provenance=false -f "$HERE/Dockerfile" -t "$IMAGE" .
docker push "$IMAGE"

# 2. The container: plain settings as environment, the key as a secrets REFERENCE.
SECRET_ARN=$(aws secretsmanager describe-secret --secret-id "$SECRET" --query ARN --output text)
ENV_JSON=$(python3 - "$HERE/service.env" <<'PY'
import json, sys
keep = ["LLM_PROVIDER", "MODEL", "PROMPT_VERSION", "RERANK_CANDIDATES", "USER_PER_MINUTE", "USER_DAILY_INR",
        "GLOBAL_DAILY_INR", "DAILY_BUDGET_USD"]
pairs = dict(l.strip().split("=", 1) for l in open(sys.argv[1]) if "=" in l and not l.lstrip().startswith("#"))
print(json.dumps([{"name": k, "value": pairs[k]} for k in keep]))
PY
)
CONTAINER="{\"image\": \"$IMAGE\", \"containerPort\": 8000, \"environment\": $ENV_JSON,
  \"secrets\": [{\"name\": \"ANTHROPIC_API_KEY\", \"valueFrom\": \"$SECRET_ARN\"}]}"
SCALING="minTaskCount=$MIN_TASKS,maxTaskCount=$MAX_TASKS,autoScalingMetric=$SCALE_METRIC,autoScalingTargetValue=$SCALE_TARGET"
SERVICE_ARN=arn:aws:ecs:$AWS_REGION:$ACCOUNT:service/$CLUSTER/$SERVICE

if [ "${1:-create}" = update ]; then
  # A rolling deployment: the old task answers until the new one is healthy (~10 min in the labs).
  aws ecs update-express-gateway-service --service-arn "$SERVICE_ARN" \
    --primary-container "$CONTAINER" --scaling-target "$SCALING" --query 'service.status.statusCode' --output text
else
  aws ecs create-express-gateway-service --cluster "$CLUSTER" --service-name "$SERVICE" \
    --execution-role-arn "arn:aws:iam::$ACCOUNT:role/shopkart-ecs-execution" \
    --infrastructure-role-arn "arn:aws:iam::$ACCOUNT:role/shopkart-ecs-infrastructure" \
    --primary-container "$CONTAINER" --health-check-path /health --cpu "$CPU" --memory "$MEMORY" \
    --scaling-target "$SCALING" \
    --query 'service.{arn: serviceArn, status: status.statusCode, url: activeConfigurations[0].ingressPaths[0].endpoint}'
fi

# 3. When /health answers (about 5 minutes): bash capstone/production/solution/observe.sh
