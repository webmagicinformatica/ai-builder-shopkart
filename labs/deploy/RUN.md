# Live run: deploy lab (2026-11-21, AWS free plan, ap-southeast-2)

A real run of `done/` on a fresh AWS account (free plan, Sydney). Commands are the README's; the output is exactly what they printed, except long streams, where `...` marks lines left out. Your URLs, IDs and timings will differ.

## Part 1: ECS Express Mode

### Push the image

```text
$ source labs/deploy/aws-vars.sh
Account 045510280991 · region ap-southeast-2 · image 045510280991.dkr.ecr.ap-southeast-2.amazonaws.com/shopkart-copilot:0cb0212

$ aws ecr create-repository --repository-name $REPO --image-scanning-configuration scanOnPush=true --query repository.repositoryUri --output text
045510280991.dkr.ecr.ap-southeast-2.amazonaws.com/shopkart-copilot

$ aws ecr get-login-password | docker login --username AWS --password-stdin $REGISTRY
Login Succeeded

$ docker build --platform linux/amd64 --provenance=false -f labs/deploy/done/Dockerfile -t $IMAGE .
...
$ docker push $IMAGE
...
0cb0212: digest: sha256:6f8d063a135fc64eeadf30ff0d04c5ba87f5c2111eaca4d10665dba79408f5c6 size: 2384
```

The image is 353 MB on disk (the `python:3.12-slim` base is most of it; the packages are 137 MB).

### Secret, roles, cluster

```text
$ aws secretsmanager create-secret --name $SECRET --secret-string "$ANTHROPIC_API_KEY" --query Name --output text
shopkart/anthropic-api-key
$ aws iam create-role --role-name shopkart-ecs-execution ... --query Role.Arn --output text
arn:aws:iam::045510280991:role/shopkart-ecs-execution
$ aws iam create-role --role-name shopkart-ecs-infrastructure ... --query Role.Arn --output text
arn:aws:iam::045510280991:role/shopkart-ecs-infrastructure
$ aws ecs create-cluster --cluster-name $CLUSTER --query cluster.status --output text
ACTIVE
```

On a brand-new account, the first `create-express-gateway-service` failed with `Unable to assume the service linked role` because the ECS service-linked role didn't exist yet. `aws iam create-service-linked-role --aws-service-name ecs.amazonaws.com` (in the README) fixes it once per account.

### Create the service (09:17:01)

```text
$ aws ecs create-express-gateway-service --cluster $CLUSTER --service-name $SERVICE ... \
    --query 'service.{arn: serviceArn, status: status.statusCode, url: activeConfigurations[0].ingressPaths[0].endpoint}'
{
    "arn": "arn:aws:ecs:ap-southeast-2:045510280991:service/shopkart/shopkart-copilot",
    "status": "ACTIVE",
    "url": "https://sh-37b54bb0838a4a9982cddfdb562ccef4.ecs.ap-southeast-2.on.aws"
}

$ aws ecs monitor-express-gateway-service --service-arn ... --mode TEXT-ONLY
...
[2026-11-21 09:18:02Z] LoadBalancer arn:aws:elasticloadbalancing:ap-southeast-2:045510280991:loadbalancer/app/ecs-express-gateway-alb-3ec882fc/1bf9464e2eb06433 [PROVISIONING]
  Last Updated At: 2026-11-21 09:17:57Z
[2026-11-21 09:18:02Z] LoadBalancerSecurityGroup [PROVISIONING]
[2026-11-21 09:18:02Z] Certificate [PROVISIONING]
[2026-11-21 09:18:02Z] Listener [PROVISIONING]
[2026-11-21 09:18:02Z] Rule [PROVISIONING]
[2026-11-21 09:18:08Z] ScalableTarget [PROVISIONING]
[2026-11-21 09:18:08Z] ApplicationAutoScalingPolicy [PROVISIONING]
[2026-11-21 09:18:25Z] MetricAlarm shopkart/shopkart-copilot/RollbackAlarm [PROVISIONING]
  Reason: Target Group is not provisioned yet
...
```

`/health` answered at **09:22:13**, about 5 minutes after the create call.

### Use it

```text
$ aws ecs describe-express-gateway-service --service-arn ... --query 'service.{status: status.statusCode, url: ..., cpu: ..., memory: ...}'
{
    "status": "ACTIVE",
    "url": "https://sh-37b54bb0838a4a9982cddfdb562ccef4.ecs.ap-southeast-2.on.aws",
    "cpu": "256",
    "memory": "512"
}

$ curl -i $URL/health
HTTP/2 200
date: Sat, 21 Nov 2026 09:22:14 GMT
content-type: application/json
content-length: 15
server: uvicorn
x-request-id: c748bf6a4b94

{"status":"ok"}

$ curl -sN $URL/chat -H 'Content-Type: application/json' -d '{"session_id": "demo-1", "message": "Where is my refund for order 4512?"}'
data: {"type": "text", "text": "Your refund of"}

data: {"type": "text", "text": " ₹3,499 for"}

data: {"type": "text", "text": " order SK04512 was init"}

data: {"type": "text", "text": "iated on 16"}

data: {"type": "text", "text": " November 2026 under"}

data: {"type": "text", "text": " reference ARN74418820"}

data: {"type": "text", "text": "551, and it goes back"}

data: {"type": "text", "text": " to your card."}

...

data: {"type": "text", "text": " connect you with a teammate"}

data: {"type": "text", "text": "."}

data: {"type": "done", "request_id": "4e8bc10e5a31", "model": "claude-haiku-5-5", "tokens_in": 473, "tokens_out": 150, "cost_usd": 0.000122, "ttft_ms": 774, "latency_ms": 1371}

$ curl -s -w '\nHTTP %{http_code}\n' $URL/chat -H 'Content-Type: application/json' -d '{"session_id": "demo-1", "message": ""}'
{"detail":[{"type":"string_too_short","loc":["body","message"],"msg":"String should have at least 1 character","input":"","ctx":{"min_length":1}}]}
HTTP 422
```

The full answer: *"Your refund of ₹3,499 for order SK04512 was initiated on 16 November 2026 under reference ARN74418820551, and it goes back to your card. Refunds usually take 5 to 7 working days from pickup, and your return was picked up on 12 November and passed quality checks. Since this refund is under ₹5,000, no further approval is needed, but if it hasn't reached your card by about 24 November, reply here and I can connect you with a teammate."*

```text
$ aws logs tail $LOG --since 10m --format short | grep -v "GET /health"
2026-11-21T09:21:40 {"event": "startup", "provider": "anthropic", "model": "claude-haiku-5-5"}
2026-11-21T09:21:40 INFO:     Application startup complete.
2026-11-21T09:21:40 INFO:     Uvicorn running on http://0.0.0.0:8000 (Press CTRL+C to quit)
2026-11-21T09:22:25 INFO:     172.31.4.175:10508 - "POST /chat HTTP/1.1" 200 OK
2026-11-21T09:22:27 {"event": "chat", "session_id": "demo-1", "provider_request_id": "req_011ChFq2PMuByyfwuj7Hx67i", "request_id": "4e8bc10e5a31", "model": "claude-haiku-5-5", "tokens_in": 473, "tokens_out": 150, "cost_usd": 0.000122, "ttft_ms": 774, "latency_ms": 1371}
2026-11-21T09:22:27 INFO:     172.31.45.115:5072 - "POST /chat HTTP/1.1" 422 Unprocessable Entity

$ aws ecs describe-express-gateway-service --service-arn ... --query 'service.activeConfigurations[0].primaryContainer.secrets'
[
    {
        "name": "ANTHROPIC_API_KEY",
        "valueFrom": "arn:aws:secretsmanager:ap-southeast-2:045510280991:secret:shopkart/anthropic-api-key-Hqj2da"
    }
]

$ docker run --rm --entrypoint ls $IMAGE -a /app
.
..
.venv
app.py
data
shopkart
```

### Tear down Part 1

The run below is from the later tracing/load-test service (same commands). Deleting took about 8 minutes, most of it waiting for the load balancer.

```text
$ bash labs/deploy/teardown.sh service
- deleting ECS Express service shopkart-copilot (the load balancer goes with it; takes a few minutes)
- deleting log group /aws/ecs/shopkart/shopkart-copilot-6ff1
- deleting task definitions of shopkart-shopkart-copilot
- deleting cluster shopkart
```

## Part 2: Lambda

```text
$ aws iam create-role --role-name shopkart-lambda ... --query Role.Arn --output text
arn:aws:iam::045510280991:role/shopkart-lambda

$ aws lambda create-function --function-name $FUNCTION --package-type Image --code ImageUri=$IMAGE ... \
    --query '{name: FunctionName, state: State, memory: MemorySize, timeout: Timeout}'
{
    "name": "shopkart-copilot",
    "state": "Pending",
    "memory": 512,
    "timeout": 60
}
$ time aws lambda wait function-active-v2 --function-name $FUNCTION
real	0m8.849s

$ aws lambda create-function-url-config --function-name $FUNCTION --auth-type NONE --invoke-mode RESPONSE_STREAM --query '{url: FunctionUrl, mode: InvokeMode}'
{
    "url": "https://aynuuhi3yufij27f4nip5qh42m0cexth.lambda-url.ap-southeast-2.on.aws/",
    "mode": "RESPONSE_STREAM"
}
$ aws lambda add-permission ... (both statements)
permissions added
```

### Cold, warm, streaming

```text
$ curl -s -o /dev/null -w 'health: %{http_code} in %{time_total}s\n' ${FURL}health      # cold
health: 200 in 8.848813s
$ curl -s -o /dev/null -w 'health: %{http_code} in %{time_total}s\n' ${FURL}health      # warm
health: 200 in 0.550810s

$ curl -sN ${FURL}chat -H 'Content-Type: application/json' -d '{"session_id": "demo-2", "message": "Where is my refund for order 4512?"}' -w '\n[time to first byte %{time_starttransfer}s, total %{time_total}s]\n'
...
data: {"type": "done", "request_id": "6588fda91d87", "model": "claude-haiku-5-5", "tokens_in": 473, "tokens_out": 125, "cost_usd": 0.00011, "ttft_ms": 847, "latency_ms": 1252}
[time to first byte 0.553884s, total 1.814868s]

$ aws logs tail /aws/lambda/$FUNCTION --since 10m --format short | grep -E "REPORT|startup|chat\""
2026-11-21T09:34:25 {"event": "startup", "provider": "anthropic", "model": "claude-haiku-5-5"}
2026-11-21T09:34:25 REPORT RequestId: 6c7a498e-...	Duration: 44.57 ms	Billed Duration: 8001 ms	Memory Size: 512 MB	Max Memory Used: 204 MB	Init Duration: 7955.51 ms
2026-11-21T09:34:26 REPORT RequestId: fce7f551-...	Duration: 2.75 ms	Billed Duration: 3 ms	Memory Size: 512 MB	Max Memory Used: 204 MB
2026-11-21T09:34:27 {"event": "chat", "session_id": "demo-2", "provider_request_id": "req_011ChFqwXQKH4kHP1RJndHwv", "request_id": "6588fda91d87", "model": "claude-haiku-5-5", "tokens_in": 473, "tokens_out": 125, "cost_usd": 0.00011, "ttft_ms": 847, "latency_ms": 1252}
2026-11-21T09:34:27 REPORT RequestId: 1dc09de3-...	Duration: 1266.68 ms	Billed Duration: 1267 ms	Memory Size: 512 MB	Max Memory Used: 205 MB
```

The first cold start pulled the image too: **Init Duration 7,956 ms, billed 8,001 ms** (the start-up is billed). A second cold start (after a configuration change, which retires the warm environments):

```text
$ aws lambda update-function-configuration --function-name $FUNCTION --description "cold start test 2" --query LastUpdateStatus --output text
InProgress
$ for i in 1 2 3; do curl -s -o /dev/null -w "health: %{http_code} in %{time_total}s\n" ${FURL}health; done
health: 200 in 4.190687s
health: 200 in 0.606035s
health: 200 in 0.542442s
REPORT RequestId: 7a13c6ac-...	Duration: 45.57 ms	Billed Duration: 3430 ms	Memory Size: 512 MB	Max Memory Used: 204 MB	Init Duration: 3383.55 ms
```

For comparison, the always-warm ECS service from our machine: `ECS health: 200 in 0.579911s`, `0.640242s`, `0.592771s` (TCP connect to Sydney alone was 0.18 s).

### Tear down Part 2

```text
$ bash labs/deploy/teardown.sh lambda
- deleting Lambda function shopkart-copilot (and its function URL)
- deleting log group /aws/lambda/shopkart-copilot
...
```

And at the very end of all four cloud labs:

```text
$ bash labs/deploy/teardown.sh all
- deleting Lambda function shopkart-tickets-mcp (and its function URL)
- deleting log group /aws/lambda/shopkart-tickets-mcp
- deleting ECR repository shopkart-tickets-mcp and its images
- deleting ECR repository shopkart-copilot and its images
- deleting secret shopkart/anthropic-api-key (no recovery window)
- deleting secret shopkart/openai-api-key (no recovery window)
- deleting DynamoDB table shopkart-ticket-state
- deleting dashboard shopkart-copilot
- deleting alarms
- deleting IAM role shopkart-ecs-execution
- deleting IAM role shopkart-ecs-infrastructure
- deleting IAM role shopkart-lambda
- deleting IAM role shopkart-mcp-lambda

ECS clusters:          none
ECS services:          none
Load balancers:        none
Target groups:         none
Task definitions:      none
ECR repositories:      none
Lambda functions:      none
Secrets:               none
Log groups:            none
DynamoDB tables:       none
Dashboards:            none
Alarms:                none
IAM roles (shopkart):  none
```

## OpenAI (`lab-deploy-openai`)

The same service, with the secret swapped (09:22:54). The new task started at 09:24:23 and the rollout finished at about 09:32 (the old task keeps serving until then).

```text
$ aws secretsmanager create-secret --name shopkart/openai-api-key --secret-string "$OPENAI_API_KEY" --query Name --output text
shopkart/openai-api-key
$ aws ecs update-express-gateway-service --service-arn ... --primary-container "{... LLM_PROVIDER=openai, OPENAI_API_KEY from the secret ...}" --query 'service.status.statusCode' --output text
ACTIVE
$ aws logs tail $LOG --since 15m --format short | grep startup
2026-11-21T09:21:40 {"event": "startup", "provider": "anthropic", "model": "claude-haiku-5-5"}
2026-11-21T09:24:23 {"event": "startup", "provider": "openai", "model": "gpt-6-luna"}

$ curl -sN $URL/chat -H 'Content-Type: application/json' -d '{"session_id": "demo-openai", "message": "Where is my refund for order 4512?"}'
data: {"type": "text", "text": "Your"}

data: {"type": "text", "text": " ₹"}

data: {"type": "text", "text": "3"}

data: {"type": "text", "text": ","}

data: {"type": "text", "text": "499"}

data: {"type": "text", "text": " refund"}

...

data: {"type": "text", "text": "51"}

data: {"type": "text", "text": "."}

data: {"type": "done", "request_id": "99c82f00b59b", "model": "gpt-6-luna", "tokens_in": 356, "tokens_out": 54, "cost_usd": 6.3e-05, "ttft_ms": 534, "latency_ms": 1772}
```

The full answer: *"Your ₹3,499 refund was initiated to your original card on 16 November. It usually takes 5–7 working days after pickup (12 November), so it should arrive by 23 November; your reference is ARN74418820551."* The very first OpenAI call on the new task took 5.8 s to its first token; the next one 0.53 s.

## Spend for this lab

- Anthropic: 4 calls on `claude-haiku-5-5`, **$0.00046**. OpenAI: 2 calls on `gpt-6-luna`, **$0.00012**.
- AWS: the ECS service ran about 20 minutes and the Lambda function was used for a few minutes. Estimated well under $0.05 (Fargate 0.25 vCPU, the load balancer and its public IPs, by the hour; Lambda and Secrets Manager are fractions of a cent).
