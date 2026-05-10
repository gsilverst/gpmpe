# AWS Deployment Runbook

This runbook describes the first AWS staging deployment for GPMPE. It assumes the application image is already Docker-ready and that local CI passes in SQLite mode.

For a concrete worked example based on the first successful staging deployment, see `docs/AWS_STAGING_DEPLOYMENT_EXAMPLE.md`. That example includes non-secret resource names, validation checks, limitations, and troubleshooting lessons learned. This runbook remains the general deployment reference.

## Repository Boundaries

GPMPE deployments should keep three repositories conceptually separate:

- **Application source repository**: Contains the open-source GPMPE application code, tests, Dockerfile, and deployment examples. It must not contain customer business profiles, campaign YAML, generated PDFs, database files, or deployment secrets.
- **Deployment repository**: Owned by the operator of a specific AWS deployment. It can contain that operator's infrastructure-as-code, copied or adapted GitHub Actions workflows, ECS task definitions, and environment-specific deployment documentation. For example, an operator might maintain a private `gpmpe-deployment` repository.
- **Business data repository**: Owned and configured by the application administrator for a specific tenant/customer/deployment. This repository stores business profile and marketing campaign YAML files that are synchronized to EFS and RDS at runtime. It must be managed independently from the application source repository.

The sample `.github/workflows/aws-deploy.yml` and `aws/ecs-task-definition.template.json` files are scaffolds for deployment owners. An open-source user should copy or adapt them into their own deployment repository rather than treating the upstream application source repository as the owner of their AWS deployment.

## Deployment Shape

- **Compute**: ECS/Fargate service running the GPMPE container.
- **Database**: Amazon RDS exposed to the task through `DATABASE_URL`.
- **Storage**: Amazon EFS mounted at `/app/data` and `/app/output`.
- **Source-of-truth data**: YAML files in the EFS-backed data directory, synchronized with Git.
- **Git sync**: Sidecar container running `backend/scripts/git_sync_worker.sh`.
- **Secrets**: AWS Secrets Manager or ECS task secrets. Do not put raw database passwords, Git tokens, deploy keys, or API keys in GitHub variables or task-definition environment values.

## Required AWS Values

Before running an adapted deploy workflow from the deployment owner's repository, collect these values:

| Value | Used By |
|---|---|
| AWS account ID | ECR image URI, IAM role ARNs, secret ARNs |
| AWS region | Deploy workflow, ECR, ECS, CloudWatch, Secrets Manager |
| ECR repository name | Deploy workflow image push |
| ECS cluster name | Deploy workflow deploy step |
| ECS service name | Deploy workflow deploy step |
| ECS task definition family | `aws/ecs-task-definition.template.json` |
| ECS app container name | GitHub workflow render step; default `gpmpe-app` |
| ECS execution role ARN | Pull image and read ECS secrets |
| ECS task role ARN | App runtime access to AWS services |
| VPC subnets and security groups | ECS service networking |
| RDS endpoint/secret ARN | `DATABASE_URL` secret |
| EFS filesystem ID | ECS task volume configuration |
| EFS access point IDs | `/app/data` and `/app/output` mounts |
| CloudWatch log group | ECS container logs |
| Deployment OIDC role ARN | `AWS_DEPLOY_ROLE_ARN` GitHub secret or equivalent CI setting |
| Application host name | Cognito callback URL and HTTPS user entry point |
| ACM certificate ARN | HTTPS ALB listener for Cognito authentication |

## Deployment CI Configuration

If the deployment owner uses GitHub Actions, create an `aws-staging` environment in the deployment repository and set:

### Environment Variables

- `AWS_REGION`
- `ECR_REPOSITORY`
- `ECS_CLUSTER`
- `ECS_SERVICE`

### Environment Secrets

- `AWS_DEPLOY_ROLE_ARN`

The deploy workflow should use OIDC and assume this role. Prefer OIDC over long-lived AWS access keys. The OIDC trust policy should name the deployment repository, not the upstream application source repository, unless the same private repository intentionally owns both source and deployment.

## ECS Task Definition

Use `aws/ecs-task-definition.template.json` as the starting point. Before first deployment:

1. Replace `ACCOUNT_ID`, `REGION`, `fs-REPLACE_ME`, and access point placeholders.
2. Replace execution and task role ARNs.
3. Confirm the task CPU/memory values.
4. Confirm the CloudWatch log group exists or let infrastructure provisioning create it.
5. Confirm `GIT_BRANCH` points to the staging/integration branch.
6. Keep `GIT_PUSH_ENABLED=false` for the first deploy unless global Git credentials have been validated.
7. Keep `AUTH_MODE=disabled` for pre-auth smoke tests, then switch to `AUTH_MODE=alb_oidc` after Cognito/ALB authentication is configured.
8. Set `AUTH_BOOTSTRAP_TOKEN` only for the active Primary Admin handoff/recovery window, then remove or rotate it after the handoff succeeds.
9. Set `COGNITO_REGION` and `COGNITO_USER_POOL_ID` after creating the Cognito user pool.
10. Keep `AUTH_DEPLOYER_RECOVERY_ENABLED=false` by default. Set it to `true` only when an AWS Deployer/Admin needs to assign or recover a GPMPE Primary Admin after the initial handoff.

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
5. Run the deployment owner's deploy workflow manually with an image tag such as `staging-YYYYMMDD-HHMM`.
6. Wait for ECS service stability.
7. Open the load balancer target and check `/health`.

## Cognito And ALB Login Setup

The recommended AWS login shape is Cognito hosted UI in front of the application through an HTTPS ALB listener. The application then trusts the ALB-provided OIDC headers, maps the authenticated email to an app user record, and enforces application roles and business grants from RDS.

Prerequisites:

- A real application host name, such as `staging.example.com`, that users will open in the browser.
- An ACM certificate for that host name in the same AWS region as the ALB.
- DNS for the host name pointing to the ALB.
- The ALB security group allowing inbound HTTPS `443` from the desired client source.

After those prerequisites exist, run the helper from the deployment repository or an operator workstation:

```bash
aws/setup-cognito-alb-auth.sh \
  --region us-east-2 \
  --app-host staging.example.com \
  --certificate-arn arn:aws:acm:us-east-2:ACCOUNT_ID:certificate/CERTIFICATE_ID \
  --load-balancer-arn arn:aws:elasticloadbalancing:us-east-2:ACCOUNT_ID:loadbalancer/app/gpmpe-staging-alb/ALB_ID \
  --target-group-arn arn:aws:elasticloadbalancing:us-east-2:ACCOUNT_ID:targetgroup/gpmpe-staging-tg/TG_ID \
  --ecs-task-role-name gpmpe-ecs-task-role
```

The helper creates:

- Cognito user pool with email usernames.
- Cognito app client with a client secret for ALB authentication.
- Cognito hosted UI domain.
- ECS task role inline policy for `cognito-idp:AdminCreateUser`.
- HTTPS ALB listener that authenticates with Cognito before forwarding to the app.

Then update the ECS task definition:

1. Set `AUTH_MODE=alb_oidc`.
2. Set `COGNITO_REGION` to the deployment region.
3. Set `COGNITO_USER_POOL_ID` to the helper output.
4. Keep `AUTH_BOOTSTRAP_TOKEN` as an ECS secret only until first setup has completed.
5. Redeploy the ECS service and open `/auth/status` through the HTTPS host.

For the current staging deployment, this step is blocked until a host name and ACM certificate are selected. Do not switch the public staging app to `AUTH_MODE=alb_oidc` until the HTTPS listener is active; otherwise direct HTTP requests will lack trusted OIDC headers and the app will correctly reject them.

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
- Admin-only credential management is guarded by the app authorization dependency when authentication is enabled. The current AWS target is ALB/Cognito authentication in front of the app, with app-level user and role mirrors stored in RDS.

## First-Run Admin Handoff

After the AWS stack is deployed and Cognito/ALB authentication is configured:

1. Set `AUTH_MODE=alb_oidc` on the ECS task.
2. Set `COGNITO_USER_POOL_ID` and `COGNITO_REGION` so the app can send Cognito invitations through `AdminCreateUser`.
3. Set a temporary `AUTH_BOOTSTRAP_TOKEN` value for the first setup run.
4. Visit `/setup` through the AWS application URL.
5. Enter the Primary Admin email address and setup token.
6. Remove or rotate the setup token after the first Primary Admin is created.

The application stores only app-level user metadata, roles, business access grants, and audit/version metadata. Cognito remains responsible for login credentials, password reset, MFA/session behavior, and invite delivery.

## AWS Deployer/Admin Recovery

AWS Deployer/Admin and GPMPE Primary Admin are separate roles. AWS access should not automatically grant GPMPE app access, but an AWS Deployer/Admin must be able to recover the deployment if all GPMPE Primary Admin users are unavailable.

For a controlled recovery handoff:

1. Use AWS credentials to set or rotate the `AUTH_BOOTSTRAP_TOKEN` secret.
2. Set `AUTH_DEPLOYER_RECOVERY_ENABLED=true` in the ECS task definition.
3. Redeploy the ECS service.
4. Visit `/setup` through the authenticated HTTPS application URL.
5. Enter the new or restored Primary Admin email address and setup token.
6. Confirm the audit log contains `auth.deployer_recovery_primary_admin`.
7. Set `AUTH_DEPLOYER_RECOVERY_ENABLED=false`, remove or rotate `AUTH_BOOTSTRAP_TOKEN`, and redeploy.

This recovery path can be reopened whenever needed by an AWS Deployer/Admin, but it should not be left enabled during normal operation.

## RDS Managed Passwords

If the RDS instance uses AWS-managed master password rotation, treat the RDS-managed master secret as the source of truth. The application `DATABASE_URL` secret must be rebuilt from that managed secret whenever the managed password changes.

Do not set `--master-user-password` manually on a managed-password RDS instance, and do not print the managed password while repairing the app secret. The `DATABASE_URL` value should still be a plaintext SQLAlchemy URL stored in Secrets Manager, with the password portion URL-encoded.
