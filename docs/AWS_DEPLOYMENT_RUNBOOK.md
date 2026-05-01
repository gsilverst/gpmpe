# AWS Deployment Runbook

This runbook describes the first AWS staging deployment for GPMPE. It assumes the application image is already Docker-ready and that local CI passes in SQLite mode.

## Deployment Shape

- **Compute**: ECS/Fargate service running the GPMPE container.
- **Database**: Amazon RDS exposed to the task through `DATABASE_URL`.
- **Storage**: Amazon EFS mounted at `/app/data` and `/app/output`.
- **Source-of-truth data**: YAML files in the EFS-backed data directory, synchronized with Git.
- **Git sync**: Sidecar container running `backend/scripts/git_sync_worker.sh`.
- **Secrets**: AWS Secrets Manager or ECS task secrets. Do not put raw database passwords, Git tokens, deploy keys, or API keys in GitHub variables or task-definition environment values.

## Required AWS Values

Before running `.github/workflows/aws-deploy.yml`, collect these values:

| Value | Used By |
|---|---|
| AWS account ID | ECR image URI, IAM role ARNs, secret ARNs |
| AWS region | GitHub workflow, ECR, ECS, CloudWatch, Secrets Manager |
| ECR repository name | GitHub workflow image push |
| ECS cluster name | GitHub workflow deploy step |
| ECS service name | GitHub workflow deploy step |
| ECS task definition family | `aws/ecs-task-definition.template.json` |
| ECS app container name | GitHub workflow render step; default `gpmpe-app` |
| ECS execution role ARN | Pull image and read ECS secrets |
| ECS task role ARN | App runtime access to AWS services |
| VPC subnets and security groups | ECS service networking |
| RDS endpoint/secret ARN | `DATABASE_URL` secret |
| EFS filesystem ID | ECS task volume configuration |
| EFS access point IDs | `/app/data` and `/app/output` mounts |
| CloudWatch log group | ECS container logs |
| GitHub OIDC deploy role ARN | `AWS_DEPLOY_ROLE_ARN` GitHub secret |

## GitHub Configuration

Create an `aws-staging` environment in GitHub and set:

### Environment Variables

- `AWS_REGION`
- `ECR_REPOSITORY`
- `ECS_CLUSTER`
- `ECS_SERVICE`

### Environment Secrets

- `AWS_DEPLOY_ROLE_ARN`

The deploy workflow uses GitHub OIDC and assumes this role. Prefer OIDC over long-lived AWS access keys.

## ECS Task Definition

Use `aws/ecs-task-definition.template.json` as the starting point. Before first deployment:

1. Replace `ACCOUNT_ID`, `REGION`, `fs-REPLACE_ME`, and access point placeholders.
2. Replace execution and task role ARNs.
3. Confirm the task CPU/memory values.
4. Confirm the CloudWatch log group exists or let infrastructure provisioning create it.
5. Confirm `GIT_BRANCH` points to the staging/integration branch.
6. Keep `GIT_PUSH_ENABLED=false` for the first deploy unless global Git credentials have been validated.

The task definition contains two containers:

- `gpmpe-app`: the FastAPI/frontend container exposed on port `8000`.
- `gpmpe-git-sync`: a sidecar that calls `/data/pull` on the app container.

## First Staging Deploy

1. Provision RDS, EFS, ECR, ECS, CloudWatch logs, and IAM roles.
2. Create Secrets Manager values for:
   - `DATABASE_URL`
   - `OPENROUTER_API_KEY` if LLM support is enabled
   - `GIT_USER_NAME`
   - `GIT_USER_EMAIL`
   - Git credentials if push/pull requires private repository authentication
3. Clone or initialize the YAML data repository onto the EFS data access point.
4. Update `aws/ecs-task-definition.template.json` with real AWS identifiers.
5. Run the `Deploy to AWS` workflow manually with an image tag such as `staging-YYYYMMDD-HHMM`.
6. Wait for ECS service stability.
7. Open the load balancer target and check `/health`.

## Staging Validation

Run these checks after the first deployment:

1. `GET /health` returns `database: ok`.
2. Startup reconciliation reports the expected YAML/RDS state.
3. `POST /data/pull` imports a known YAML commit into RDS.
4. The chatbot can modify a campaign.
5. Campaign save writes YAML to EFS.
6. PDF rendering writes output to `/app/output`.
7. If `GIT_PUSH_ENABLED=true`, a save operation creates and pushes a commit to the configured branch.
8. CloudWatch logs show no repeated sync worker failures.

## Rollback

For the initial release, rollback should be image-based:

1. Re-run the deploy workflow with the last known-good image tag, or update the ECS service to the prior task definition revision.
2. Leave EFS and RDS intact.
3. If Git sync caused a bad YAML commit, revert the Git commit in the data repository and run `/data/pull`.
4. If RDS and YAML disagree after rollback, stop the sync worker and perform manual reconciliation before re-enabling it.

## Production Promotion Checklist

- Backend tests pass.
- Frontend build passes.
- Docker build passes.
- Staging deploy is healthy.
- RDS backup policy is enabled.
- EFS backup policy is enabled.
- Secrets rotation process is documented.
- Git push remains disabled until global service credentials and branch protections are confirmed.
- Admin-only credential management is tracked for Phase 5/RBAC work.
