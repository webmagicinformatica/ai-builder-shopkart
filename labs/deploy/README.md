# Lab: containerise and deploy the Copilot with a live URL (2 parts)

**Part 1:** put the Copilot's FastAPI backend in a Docker image, push it to Amazon ECR, and run it on **ECS Express Mode** behind HTTPS, with the API key in **Secrets Manager**.
**Part 2:** run the same image **serverless on AWS Lambda** with a function URL, and compare cold start, cost and limits.

```text
labs/deploy/
  start/app.py                   the Copilot backend (given), with TODO 1
  start/Dockerfile               the image recipe, with TODO 2–5
  start/Dockerfile.dockerignore  what the build must never see, with TODO 6
  done/                          the finished answer
  aws-vars.sh                    names used by every cloud lab (region, repo, service...)
  iam/                           the role trust policies and the "read only these two secrets" policy
  teardown.sh, leftovers.sh      delete everything, then check nothing is left
  tests/                         the checkpoints (no key, no network, no AWS)
```

**Region.** The AWS free plan gives your account one region. Ours is **Sydney, `ap-southeast-2`**. When you upgrade, pick the region nearest your users (for ShopKart, Mumbai, `ap-south-1`).
**Cost.** Part 1 runs a 0.25 vCPU task and a load balancer: a few US cents an hour while it's up. Part 2 costs almost nothing. Tear down at the end of each part. A $3 budget alert on the account is a good safety net.

## Before you start

Add three Codespaces secrets ([github.com/settings/codespaces](https://github.com/settings/codespaces)) for your repo: `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY` (an IAM user's access key, not your root login) and `AWS_DEFAULT_REGION` = `ap-southeast-2`. Your `ANTHROPIC_API_KEY` secret is already there. The Codespace has Docker and the AWS CLI.

```bash
aws sts get-caller-identity --query Arn --output text     # who am I?
source labs/deploy/aws-vars.sh                              # names for this lab, in this terminal
```

## Part 1: containers on ECS Express Mode

### 1. The backend (`start/app.py`)

It's the FastAPI app from the backend lesson: typed requests, `POST /chat` streaming server-sent events, a request ID on every request and in every log line, a 30 s timeout per wait and 60 s for the whole answer, and keys read from the environment at start-up.

**TODO 1:** add `GET /health` returning `{"status": "ok"}`. The load balancer calls it every 30 seconds, so it must never call the model.

```bash
uv run uvicorn app:app --app-dir labs/deploy/start --port 8000 &
curl -sN localhost:8000/chat -H 'Content-Type: application/json' \
  -d '{"session_id": "demo-1", "message": "Where is my refund for order 4512?"}'
curl -s -o /dev/null -w '%{http_code}\n' localhost:8000/chat -H 'Content-Type: application/json' -d '{"session_id": "x", "message": ""}'   # 422, no model call
kill %1
```

`LLM_PROVIDER=fake` streams a canned answer with no model call and no cost. The load-test lab uses it.

### 2. The image (`start/Dockerfile`)

- **TODO 2:** `FROM python:3.12-slim AS build`, not the 1 GB full image.
- **TODO 3:** copy only `pyproject.toml` and `uv.lock`, then `RUN uv sync --frozen --only-group serve`. Packages before code: a code change rebuilds in seconds. `--only-group serve` installs just what the server needs (FastAPI, the SDKs, boto3), not the RAG and PDF tools.
- **TODO 4:** `RUN useradd --create-home app` and `USER app`. Not root.
- **TODO 6** (`Dockerfile.dockerignore`): add `.env`. Anyone who can pull an image can read every file in it.

A `Dockerfile.dockerignore` next to a Dockerfile works like a `.dockerignore` at the repo root, for that Dockerfile only. The build context is the repo root, because the image needs `shopkart/` and `data/orders.json`. The final stage copies only the finished `.venv`, so uv itself isn't in the image (about 350 MB, most of it the Python base).

```bash
docker build -f labs/deploy/start/Dockerfile -t shopkart-copilot .
docker run --rm -p 8000:8000 -e ANTHROPIC_API_KEY shopkart-copilot      # the key comes from your env, not the image
docker run --rm --entrypoint ls shopkart-copilot -a /app                 # no .env in there
LAB=start uv run pytest labs/deploy -q                                    # checkpoints
```

`-e ANTHROPIC_API_KEY` with no `=value` passes the variable from your Codespace without printing it.

### 3. Push to ECR, with a clear tag

```bash
aws ecr create-repository --repository-name $REPO --image-scanning-configuration scanOnPush=true
aws ecr get-login-password | docker login --username AWS --password-stdin $REGISTRY
docker build --platform linux/amd64 --provenance=false -f labs/deploy/start/Dockerfile -t $IMAGE .
docker push $IMAGE
```

The tag is your git commit (`$TAG`), so you always know what's running and can roll back. `--provenance=false` keeps a plain single-platform image, which Lambda needs in Part 2.

### 4. The key goes into Secrets Manager

```bash
aws secretsmanager create-secret --name $SECRET --secret-string "$ANTHROPIC_API_KEY"
```

### 5. Two roles

The **task execution role** pulls the image, writes logs and reads *only our two secrets*. The **infrastructure role** lets Express Mode build the load balancer, security groups and scaling for you.

```bash
aws iam create-role --role-name shopkart-ecs-execution --assume-role-policy-document file://labs/deploy/iam/ecs-tasks-trust.json
aws iam attach-role-policy --role-name shopkart-ecs-execution --policy-arn arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy
aws iam put-role-policy --role-name shopkart-ecs-execution --policy-name read-llm-secrets \
  --policy-document "$(sed "s/ACCOUNT/$ACCOUNT/" labs/deploy/iam/read-llm-secrets.json)"
aws iam create-role --role-name shopkart-ecs-infrastructure --assume-role-policy-document file://labs/deploy/iam/ecs-infrastructure-trust.json
aws iam attach-role-policy --role-name shopkart-ecs-infrastructure --policy-arn arn:aws:iam::aws:policy/service-role/AmazonECSInfrastructureRoleforExpressGatewayServices
aws iam create-service-linked-role --aws-service-name ecs.amazonaws.com 2>/dev/null   # once per account; "taken" is fine
aws ecs create-cluster --cluster-name $CLUSTER
```

### 6. Create the Express service

```bash
SECRET_ARN=$(aws secretsmanager describe-secret --secret-id $SECRET --query ARN --output text)
aws ecs create-express-gateway-service \
  --cluster $CLUSTER --service-name $SERVICE \
  --execution-role-arn arn:aws:iam::$ACCOUNT:role/shopkart-ecs-execution \
  --infrastructure-role-arn arn:aws:iam::$ACCOUNT:role/shopkart-ecs-infrastructure \
  --primary-container "{
      \"image\": \"$IMAGE\",
      \"containerPort\": 8000,
      \"environment\": [{\"name\": \"LLM_PROVIDER\", \"value\": \"anthropic\"},
                        {\"name\": \"DAILY_BUDGET_USD\", \"value\": \"0.50\"}],
      \"secrets\": [{\"name\": \"ANTHROPIC_API_KEY\", \"valueFrom\": \"$SECRET_ARN\"}]
    }" \
  --health-check-path /health \
  --cpu 256 --memory 512 \
  --scaling-target minTaskCount=1,maxTaskCount=2,autoScalingMetric=REQUEST_COUNT_PER_TARGET,autoScalingTargetValue=50 \
  --query 'service.{arn: serviceArn, status: status.statusCode, url: activeConfigurations[0].ingressPaths[0].endpoint}'
```

- Port **8000**, not the default 80. Health check **`/health`**, not the default `/ping`.
- Plain settings are `environment`. The key is a **`secrets` reference**: the service settings hold only the secret's ARN, and ECS hands the value to the app as an environment variable when a task starts.
- **Scale on requests, not CPU.** The Copilot mostly waits for the model, and waiting uses almost no CPU.
- 0.25 vCPU and 0.5 GB is plenty for a test copy.

Watch it build (Ctrl+C to stop watching). It took about 5 minutes in our run:

```bash
aws ecs monitor-express-gateway-service --service-arn arn:aws:ecs:$AWS_REGION:$ACCOUNT:service/$CLUSTER/$SERVICE --mode TEXT-ONLY
```

### 7. Use the live URL

```bash
URL=$(aws ecs describe-express-gateway-service --service-arn arn:aws:ecs:$AWS_REGION:$ACCOUNT:service/$CLUSTER/$SERVICE \
  --query 'service.activeConfigurations[0].ingressPaths[0].endpoint' --output text)
curl -i $URL/health
curl -sN $URL/chat -H 'Content-Type: application/json' -d '{"session_id": "demo-1", "message": "Where is my refund for order 4512?"}'
```

Open `$URL` in a browser (or on your phone) for a tiny chat page that streams the answer. Then find your request in the logs, by its request ID:

```bash
LOG=$(aws logs describe-log-groups --log-group-name-prefix /aws/ecs/$CLUSTER/ --query 'logGroups[0].logGroupName' --output text)
aws logs tail $LOG --since 10m --format short | grep '"event": "chat"'
aws ecs describe-express-gateway-service --service-arn arn:aws:ecs:$AWS_REGION:$ACCOUNT:service/$CLUSTER/$SERVICE \
  --query 'service.activeConfigurations[0].primaryContainer.secrets'       # only a reference, never the key
```

Each log line has our request ID **and** Anthropic's (`req_...`), the one their support asks for.

### 8. Tear down Part 1

```bash
bash labs/deploy/teardown.sh service
```

It deletes the service (the load balancer, target groups and security groups go with it), the log group, the task definitions and the cluster, then lists what's left. Keep the image, the secret and the roles for Part 2.

## Part 2: the same image on AWS Lambda

### 1. One line in the Dockerfile

**TODO 5:** add the Lambda Web Adapter. It turns each Lambda event back into a normal HTTP request on port 8000. Outside Lambda it does nothing, so the image still runs on ECS.

```dockerfile
COPY --from=public.ecr.aws/awsguru/aws-lambda-adapter:0.9.1 /lambda-adapter /opt/extensions/lambda-adapter
```

Rebuild and push (`docker build ... -t $IMAGE .` and `docker push $IMAGE` as in step 3).

### 2. A role, the function, and a streaming function URL

Lambda has no "secrets" setting like ECS. The app reads the secret once at start-up (`ANTHROPIC_API_KEY_SECRET_ID`), with a role that can read only our two secrets.

```bash
aws iam create-role --role-name shopkart-lambda --assume-role-policy-document file://labs/deploy/iam/lambda-trust.json
aws iam attach-role-policy --role-name shopkart-lambda --policy-arn arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole
aws iam put-role-policy --role-name shopkart-lambda --policy-name read-llm-secrets \
  --policy-document "$(sed "s/ACCOUNT/$ACCOUNT/" labs/deploy/iam/read-llm-secrets.json)"

aws lambda create-function --function-name $FUNCTION \
  --package-type Image --code ImageUri=$IMAGE \
  --role arn:aws:iam::$ACCOUNT:role/shopkart-lambda \
  --memory-size 512 --timeout 60 \
  --environment "Variables={LLM_PROVIDER=anthropic,ANTHROPIC_API_KEY_SECRET_ID=$SECRET,AWS_LWA_INVOKE_MODE=response_stream,DAILY_BUDGET_USD=0.50}"
aws lambda wait function-active-v2 --function-name $FUNCTION

aws lambda create-function-url-config --function-name $FUNCTION --auth-type NONE --invoke-mode RESPONSE_STREAM
aws lambda add-permission --function-name $FUNCTION --statement-id public-url \
  --action lambda:InvokeFunctionUrl --principal '*' --function-url-auth-type NONE
aws lambda add-permission --function-name $FUNCTION --statement-id public-invoke \
  --action lambda:InvokeFunction --principal '*' --invoked-via-function-url
```

- Half a gigabyte, a **60 s timeout**, and the model call's own 30 s timeout inside it: timeouts from the inside out.
- `--invoke-mode RESPONSE_STREAM` plus `AWS_LWA_INVOKE_MODE=response_stream`: the answer streams. Without them, the customer waits for the whole answer.
- `--auth-type NONE` makes it a public URL, so the app must check its own users. A function URL's only other option is AWS IAM sign-in.

### 3. Cold start, warm, and streaming

```bash
FURL=$(aws lambda get-function-url-config --function-name $FUNCTION --query FunctionUrl --output text)
curl -s -o /dev/null -w 'health: %{http_code} in %{time_total}s\n' ${FURL}health     # cold
curl -s -o /dev/null -w 'health: %{http_code} in %{time_total}s\n' ${FURL}health     # warm
curl -sN ${FURL}chat -H 'Content-Type: application/json' -d '{"session_id": "demo-2", "message": "Where is my refund for order 4512?"}'
aws logs tail /aws/lambda/$FUNCTION --since 10m --format short | grep REPORT
```

The `REPORT` line of a cold start shows `Init Duration` (start Python, import the SDKs, read the secret), and the **billed** duration includes it.

### 4. Compare (our run, 0.25 vCPU task vs 512 MB function, Sydney)

| | ECS Express Mode | Lambda + function URL |
| --- | --- | --- |
| First request | always warm (at least one task runs) | cold start: init 8.0 s the very first time, 3.4 s on a later cold start |
| Warm `/health` round trip | ~0.6 s from our machine | ~0.55 s (mostly network to Sydney) |
| Streaming | yes (load balancer: keep each gap under 60 s) | yes, with `RESPONSE_STREAM` and the web adapter |
| Longest request | as long as you like | 15 minutes, hard limit |
| Requests per copy | many at once (async) | one per execution environment |
| You pay for | every hour it's up, busy or idle | each request's time, including waiting for the model, and the cold start |
| Time to deploy | ~5 min to create, ~10 min per update | seconds |

Rule of thumb from the lesson: Lambda for spiky traffic, queues and nightly jobs; always-on containers for steady chat.

### 5. Tear down everything

```bash
bash labs/deploy/teardown.sh all
```

Every line it prints at the end should say `none` (`bash labs/deploy/leftovers.sh` checks again any time).

## The same app on OpenAI

Swap the secret, not the code: store the OpenAI key, point the service at it, and set `LLM_PROVIDER=openai`.

```bash
aws secretsmanager create-secret --name shopkart/openai-api-key --secret-string "$OPENAI_API_KEY"
OPENAI_ARN=$(aws secretsmanager describe-secret --secret-id shopkart/openai-api-key --query ARN --output text)
aws ecs update-express-gateway-service \
  --service-arn arn:aws:ecs:$AWS_REGION:$ACCOUNT:service/$CLUSTER/$SERVICE \
  --primary-container "{
      \"image\": \"$IMAGE\", \"containerPort\": 8000,
      \"environment\": [{\"name\": \"LLM_PROVIDER\", \"value\": \"openai\"}, {\"name\": \"DAILY_BUDGET_USD\", \"value\": \"0.50\"}],
      \"secrets\": [{\"name\": \"OPENAI_API_KEY\", \"valueFrom\": \"$OPENAI_ARN\"}]
    }"
```

What differs: the model is `gpt-6-luna`, the stream arrives in smaller pieces (often one word each), and OpenAI's request ID comes from the `x-request-id` header. The update is a rolling deployment: the old task keeps answering until the new one is healthy (about 10 minutes in our run). On Lambda, the same swap is `OPENAI_API_KEY_SECRET_ID=shopkart/openai-api-key` and `LLM_PROVIDER=openai`.

## Checkpoint

```bash
LAB=start uv run pytest labs/deploy -q      # your copy
uv run pytest labs/deploy -q                # the answer
```

- [ ] `docker run --entrypoint ls ... /app` shows no `.env`, and the image runs as `app`
- [ ] A live HTTPS URL streams an answer, and an empty message gets 422 without a model call
- [ ] The service settings show only a secret ARN, never the key
- [ ] The Lambda function URL streams the same answer, and you saw its cold start in the logs
- [ ] `leftovers.sh` says `none` everywhere

The real output of a live run is in [RUN.md](RUN.md).
