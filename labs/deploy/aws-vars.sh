# Names used by every cloud lab. Load them into your terminal with:
#   source labs/deploy/aws-vars.sh
# (needs AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY, from your Codespaces secrets)

export AWS_REGION=ap-southeast-2          # the free plan gives you one region: Sydney
export AWS_DEFAULT_REGION=$AWS_REGION
export AWS_PAGER=""                       # print results, don't open a pager

export ACCOUNT=$(aws sts get-caller-identity --query Account --output text)
export REGISTRY=$ACCOUNT.dkr.ecr.$AWS_REGION.amazonaws.com
export REPO=shopkart-copilot              # the ECR repository
export TAG=$(git rev-parse --short HEAD)  # a clear version tag, not just "latest"
export IMAGE=$REGISTRY/$REPO:$TAG

export CLUSTER=shopkart
export SERVICE=shopkart-copilot           # the ECS Express service (Part 1)
export FUNCTION=shopkart-copilot          # the Lambda function (Part 2)
export SECRET=shopkart/anthropic-api-key  # in Secrets Manager (OpenAI: shopkart/openai-api-key)

echo "Account $ACCOUNT · region $AWS_REGION · image $IMAGE"
