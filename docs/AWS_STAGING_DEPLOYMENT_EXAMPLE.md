# AWS Staging Deployment Example

> Draft status: this example records the first successful GPMPE staging deployment path. It intentionally excludes passwords, API keys, Git tokens, and proprietary business data. Before public release, review all identifiers and decide whether to keep concrete sample names or replace them with placeholders.

This document complements `docs/AWS_DEPLOYMENT_RUNBOOK.md`. The runbook is the general deployment reference; this file is a worked example based on the staging deployment we completed while migrating GPMPE to AWS.

## What This Example Deploys

The example deploys one low-traffic staging instance of GPMPE using:

- Amazon ECR for the Docker image.
- Amazon ECS/Fargate for the application container.
- Amazon RDS PostgreSQL for runtime database storage.
- Amazon EFS for persistent YAML and generated output storage.
- AWS Secrets Manager for runtime secrets.
- An internet-facing Application Load Balancer for HTTP access.
- An S3 staging-imports bucket for temporary business ZIP bootstrap packages.

This example is intentionally modest. It is suitable for staging, demos, and low-volume back-office use. It is not yet a full production reference architecture.

## Repository And Data Boundaries

Keep these concerns separate:

- **Application source repository**: the GPMPE codebase.
- **Deployment repository**: the deployment owner's infrastructure and environment-specific deployment automation.
- **Business data repository**: the administrator-managed business profile, promotion, and artifact-design data.
- **S3 staging-imports bucket**: temporary storage for ZIP packages used to bootstrap/import one business at a time.

The S3 bucket is not the live `DATA_DIR` and not the source of truth. It is only a short-lived import shelf.

## Example AWS Values

The first staging deployment used values like these:

| Resource | Example value |
|---|---|
| Region | `us-east-2` |
| Account ID | `433249887797` |
| ECR repository | `gpmpe` |
| Image URI | `433249887797.dkr.ecr.us-east-2.amazonaws.com/gpmpe:latest` |
| ECS cluster | `gpmpe-staging-cluster` |
| ECS service | `gpmpe-staging-alb-service` |
| ECS task family | `gpmpe-staging` |
| App container | `gpmpe-app` |
| App port | `8000` |
| ALB | `gpmpe-staging-alb` |
| Target group | `gpmpe-staging-tg` |
| RDS endpoint | `gpmpe.ctkgs4syk810.us-east-2.rds.amazonaws.com` |
| RDS port | `5432` |
| EFS file system | `fs-0de9bdc0d33139e08` |
| EFS access point | `fsap-0c47bc470d6320d07` |
| S3 import bucket | `gpmpe-433249887797-us-east-2-staging-imports` |

Use your own values in a real deployment.

## High-Level Setup Sequence

1. Select the AWS region and confirm account budget controls.
2. Create the ECR repository.
3. Create required Secrets Manager secrets.
4. Create RDS PostgreSQL.
5. Create EFS and an access point.
6. Create security groups.
7. Build and push the Docker image.
8. Create ECS task execution and task roles.
9. Create the ECS task definition.
10. Create the ECS cluster and service.
11. Add an Application Load Balancer and target group.
12. Create the S3 staging-imports bucket and task-role read policy.
13. Validate `/health`.
14. Bootstrap business data through ZIP or S3-backed business import.

## ECR And Image

Create an ECR repository named `gpmpe`.

Build and push an image for the target platform. If building on Apple Silicon and running Fargate ARM64, configure the ECS task definition for Linux/ARM64. If targeting x86_64 Fargate, build and push an amd64 image.

Example image:

```text
433249887797.dkr.ecr.us-east-2.amazonaws.com/gpmpe:latest
```

## Secrets Manager

Create secrets for runtime configuration:

- `gpmpe/staging/database-url`
- `gpmpe/staging/openai-api-key` or the model-provider key used by the deployment

The `DATABASE_URL` secret should be stored as plaintext containing only the URL, not JSON and not `DATABASE_URL=...`.

Example shape:

```text
postgresql+psycopg2://USERNAME:URL_ENCODED_PASSWORD@RDS_ENDPOINT:5432/postgres
```

In the first staging deployment, the RDS DB instance was named `gpmpe`, but the actual PostgreSQL database named `gpmpe` did not exist. Pointing the URL to `/postgres` allowed the application tables to be created. A cleaner production deployment should create an application database explicitly and point `DATABASE_URL` to that database.

## RDS

For low-volume staging:

- PostgreSQL
- Single-AZ
- Burstable instance class such as `db.t3.micro` when available
- General purpose storage such as `gp2` or `gp3`
- No public access
- Security group allows PostgreSQL `5432` from the ECS task security group

Avoid provisioned IOPS for this low-volume staging shape unless there is a clear need; it can dominate the monthly cost.

## EFS

Create an EFS file system and access point.

Example:

- File system: `fs-0de9bdc0d33139e08`
- Access point: `fsap-0c47bc470d6320d07`
- Root path: `/gpmpe`
- POSIX user/group: `1000` / `1000`
- Creation permissions: `0755`

Important lesson: if using One Zone EFS, the ECS task must run in the same Availability Zone/subnet as the EFS mount target. In the first staging deployment, tasks had to be constrained to the EFS subnet.

## Security Groups

The working staging shape used three main security groups:

| Security group | Purpose |
|---|---|
| `gpmpe-alb-sg` | Public HTTP entry to the load balancer |
| `gpmpe-ecs-sg` | ECS task application traffic |
| `gpmpe-efs-sg` | EFS NFS access |

Minimum useful rules:

| Security group | Direction | Rule |
|---|---|---|
| `gpmpe-alb-sg` | Inbound | HTTP `80` from current admin IP for staging |
| `gpmpe-alb-sg` | Outbound | TCP `8000` to `gpmpe-ecs-sg` |
| `gpmpe-ecs-sg` | Inbound | TCP `8000` from `gpmpe-alb-sg` |
| `gpmpe-efs-sg` | Inbound | NFS/TCP `2049` from `gpmpe-ecs-sg` |
| RDS security group | Inbound | PostgreSQL/TCP `5432` from `gpmpe-ecs-sg` |

During smoke testing, direct `My IP -> ECS:8000` access can help isolate issues. Remove that direct rule after ALB access works.

## ECS Roles

The ECS execution role needs to:

- Pull from ECR.
- Read ECS-injected secrets from Secrets Manager.
- Write container logs.

The ECS task role needs runtime access for services used by the app, including:

- EFS client permissions when IAM authorization is enabled.
- S3 read access for the staging-imports bucket.

Example S3 read policy for the task role:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "ListStagingImportsBucket",
      "Effect": "Allow",
      "Action": ["s3:ListBucket"],
      "Resource": "arn:aws:s3:::gpmpe-433249887797-us-east-2-staging-imports"
    },
    {
      "Sid": "ReadStagingImportObjects",
      "Effect": "Allow",
      "Action": ["s3:GetObject"],
      "Resource": "arn:aws:s3:::gpmpe-433249887797-us-east-2-staging-imports/*"
    }
  ]
}
```

## ECS Task Definition

Important container settings:

```text
RUN_MODE=aws
DATA_DIR=/mnt/gpmpe-data/data
OUTPUT_DIR=/mnt/gpmpe-data/output
GIT_REPO_PATH=/mnt/gpmpe-data/repo
GIT_REMOTE=origin
GIT_BRANCH=main
GIT_PUSH_ENABLED=false
GIT_LOCK_TIMEOUT_SECONDS=30
COMMIT_ON_SAVE=true
```

Secrets:

```text
DATABASE_URL -> gpmpe/staging/database-url
OPENAI_API_KEY or provider key -> configured provider secret
```

Use full Secrets Manager ARNs in ECS task definitions. Short names may be interpreted as SSM Parameter Store references and can fail with `ssm:GetParameters` permission errors.

EFS volume:

- File system ID: your EFS ID
- Access point: your EFS access point ID
- Transit encryption: enabled
- Transit encryption port: `2049`
- IAM authorization: enabled when using task-role EFS permissions
- Container mount path: `/mnt/gpmpe-data`

## Load Balancer

Create an internet-facing Application Load Balancer:

- Listener: HTTP `80`
- Target group type: IP
- Target group protocol/port: HTTP `8000`
- Health check path: `/health`
- Success code: `200`

Attach the target group to the ECS service:

```text
Container: gpmpe-app
Container port: 8000
```

If an existing ECS service cannot be updated cleanly to attach a load balancer, create a new ECS service using the same task definition and attach the ALB during service creation. Once the new service is healthy, scale down or delete the old direct-access service.

## S3 Staging Imports Bucket

Create a private bucket for temporary business ZIP imports:

```text
gpmpe-433249887797-us-east-2-staging-imports
```

Recommended settings:

- ACLs disabled
- Block all public access enabled
- SSE-S3 encryption
- Lifecycle rule to expire objects after 14 days

Object names should stay simple:

```text
merci.zip
acme-demo.zip
```

Do not mirror the `DATA_DIR` layout in S3. The bucket is only a package staging area.

## Validation

Health endpoint:

```text
GET http://ALB-DNS-NAME/health
```

Expected result:

```json
{"status":"ok","database":"ok","output_dir":"/mnt/gpmpe-data/output"}
```

Other useful checks:

```text
GET /startup/status
GET /businesses
GET /data-manager/businesses
```

If the ALB health check works but browser/curl access hangs, check the ALB security group source IP. If the task starts but stops with `ResourceInitializationError`, check Secrets Manager ARNs, EFS security groups, and EFS mount target placement.

## Business Bootstrap

The application supports importing one business directory at a time.

Raw ZIP path:

```text
POST /admin/business-imports/preview
POST /admin/business-imports?conflict_action=reject
POST /admin/business-imports?conflict_action=replace
```

S3 path:

```text
POST /admin/business-imports/s3/preview
POST /admin/business-imports/s3
```

Example S3 request body:

```json
{
  "s3_uri": "s3://gpmpe-433249887797-us-east-2-staging-imports/merci.zip",
  "conflict_action": "reject"
}
```

Current conflict actions:

- `reject`
- `replace`

Future work:

- import as new business key/name
- admin UI wrapper
- authenticated admin-only enforcement
- schema-version checks
- direct business-specific Git import

## Capabilities Confirmed So Far

- ECS/Fargate can run the GPMPE container.
- The app can read Secrets Manager-injected database/API configuration.
- The app can connect to RDS PostgreSQL.
- The app can mount EFS and report the configured output directory.
- The ALB can route public HTTP traffic to the ECS task.
- The task role can be configured to read S3 import ZIPs.
- Local backend tests cover raw ZIP and mocked S3 business import flows.
- The staging ECS image was rebuilt and redeployed with S3 import support on May 8, 2026.
- A real S3-backed business import smoke test succeeded from preview through import, RDS sync, EFS write, business/campaign API reads, data-manager reads, and audit-log recording.

## Current Limitations

- This is a staging deployment, not a production hardening guide.
- HTTPS/custom domain are not yet configured in this example.
- Authentication/RBAC/admin-only enforcement is not complete.
- Git push/pull automation is not fully validated in AWS.
- Business-specific Git repository settings are documented as the desired model but not fully implemented.
- The admin UI does not yet expose the import flow.
- Database migrations are still lightweight; explicit business/campaign data schema versioning is planned.

## Bumps in the Road

These are the real issues encountered during the first staging deployment and the fixes that got the deployment moving again.

Amazon Q was useful during this deployment for pulling together ECS task failure context, CloudWatch log clues, likely root causes, and recommended AWS console checks. It should not replace reading the actual task stop reason, CloudWatch logs, security group rules, and IAM policies, but it can shorten the debugging loop quite a bit.

### Wrong Region Drift

Some early resources were created in the wrong region because the console kept returning to a different default region. The fix was to standardize on `us-east-2`, verify every major resource by region, and recreate or correct resources there.

Check this for:

- Secrets Manager secrets
- ECR repository and image
- RDS instance
- EFS file system and access point
- Security groups
- ECS cluster, task definition, and service

### ECS Service-Linked Role Error

Cluster creation initially failed with an error about ECS being unable to assume the service-linked role. The service-linked role existed, but the active console session did not have the same effective permissions as the intended administrator session.

The fix was to use the IAM Identity Center administrator login with the correct account assignment, then delete the failed CloudFormation-created cluster stack before recreating the ECS cluster.

### ECS Could Not Read Secrets

The first task startup failed because ECS tried to retrieve configured secrets but the execution role did not have the needed access. In one case the policy also referenced the wrong region.

The fix was to:

- Correct the secret ARNs to `us-east-2`.
- Ensure the ECS execution role could read the required secrets.
- Use the latest task definition revision after role/policy changes.

### Short Secret Names Were Ambiguous

The ECS task definition accepted short secret names in the console, but a failed task later showed ECS trying to retrieve values through SSM Parameter Store:

```text
ssm:GetParameters ... no identity-based policy allows the ssm:GetParameters action
```

The safer fix is to use full Secrets Manager ARNs in the task definition `ValueFrom` fields. That makes it explicit that the values come from Secrets Manager and avoids accidental SSM interpretation.

### Task Definition Revisions Lagged Behind Fixes

After a role, secret, environment variable, or EFS setting was corrected, the ECS service sometimes still pointed at an older task definition revision.

The fix was to register a new task definition revision and explicitly update the ECS service to use the latest known-good revision. After changing task definition settings, always confirm the service is deploying the expected revision.

### `DATABASE_URL` Could Not Be Parsed

The container later started but exited during application startup because SQLAlchemy could not parse `DATABASE_URL`.

The fix was to store the database URL as plain text in Secrets Manager using SQLAlchemy/PostgreSQL format:

```text
postgresql://USER:URL_ENCODED_PASSWORD@RDS_ENDPOINT:5432/postgres
```

Special characters in the database password must be URL-encoded inside the URL.

### Secret Value Needed the Actual Database URL

The database password visible in Secrets Manager did not need to be encrypted again before use in `DATABASE_URL`; Secrets Manager handles encryption at rest. The application needs the final plaintext connection string as the secret value, with only the password portion URL-encoded when embedded in the URL.

The actual RDS endpoint came from the RDS instance Connectivity & security tab, for example:

```text
gpmpe.ctkgs4syk810.us-east-2.rds.amazonaws.com
```

That endpoint replaces placeholder text such as `RDS_ENDPOINT` in the URL.

### RDS Instance Name Was Not the Database Name

After the URL format was corrected, the app connected to the RDS host but failed with:

```text
FATAL: database "gpmpe" does not exist
```

The important distinction is that the RDS instance identifier and the PostgreSQL database name are separate. For this staging instance, the working URL used the default `postgres` database until an application database is explicitly created.

### RDS Cost Estimate Was Too High at First

The initial RDS configuration showed a cost estimate far above the staging budget because provisioned IOPS storage was selected. For this workload, the data size and user count are tiny, so provisioned IOPS was unnecessary.

The fix was to use the smallest practical burstable PostgreSQL instance and general purpose storage (`gp2` or `gp3`) without provisioned IOPS. That reduced the estimate from well over $100/month to roughly the low double digits for the staging database configuration.

### EFS Mounted on the Wrong Port

One EFS security group rule was accidentally configured with the application/database port instead of the NFS port. ECS tasks then failed with EFS mount timeouts.

The fix was:

- `gpmpe-efs-sg`: inbound TCP `2049` from `gpmpe-ecs-sg`.
- `gpmpe-ecs-sg`: outbound traffic allowed to EFS.

### One Zone EFS and Subnet Placement

The One Zone EFS file system had a mount target in only one Availability Zone. Tasks launched outside that AZ could not resolve or mount the file system.

The fix was to ensure the ECS service selected the subnet/AZ that matched the One Zone EFS mount target. A multi-AZ EFS deployment would need mount targets in each AZ used by ECS.

### Existing ECS Service Had No Load Balancer Attached

The first service was already running successfully without an ALB, but the target group showed zero targets because the service had not been created with load balancer integration.

The practical fix was to create a new ALB-backed ECS service using the same task definition, target group, subnets, and security groups. For future deployments, decide whether the service should use an ALB before creating it, because adding load balancer wiring after the fact is easier to get wrong in the console.

### Failed Cluster Stack Blocked Recreate

After the first ECS cluster creation failed, a CloudFormation stack remained for the failed infrastructure attempt. Reusing the same cluster name failed until that stack was removed.

The fix was to open CloudFormation, find the failed `Infra-ECS-Cluster-...` stack, delete it, wait for `DELETE_COMPLETE`, and then recreate the cluster.

### ALB Listener Reported `HTTP:80 Not Reachable`

The ALB listener page warned that HTTP was not reachable while the ALB security group did not have a valid inbound HTTP rule. The target-side rules were not enough; clients still need permission to reach the ALB listener.

The fix was to add inbound HTTP `80` on `gpmpe-alb-sg` from the allowed client source. For staging, `My IP` is a useful source. For a public deployment, this would usually become `0.0.0.0/0` after HTTPS, authentication, and any domain-level controls are ready.

### ALB Was Healthy but Browser Access Hung

The target group eventually showed a healthy target, but public requests to the ALB DNS still hung. The issue was security group directionality and source rules.

The working shape was:

- `gpmpe-alb-sg`: inbound HTTP `80` from the allowed client source, such as `My IP` for staging.
- `gpmpe-alb-sg`: outbound TCP `8000` to `gpmpe-ecs-sg`.
- `gpmpe-ecs-sg`: inbound TCP `8000` from `gpmpe-alb-sg`.

When restricted to `My IP`, the deployment is intentionally not open to the public. If the admin's public IP changes, the ALB inbound rule must be updated.

## Lessons Learned

- Use full Secrets Manager ARNs in ECS secrets.
- URL-encode special characters in database passwords inside `DATABASE_URL`.
- The RDS instance name is not necessarily the PostgreSQL database name.
- Avoid provisioned IOPS for tiny staging databases unless required.
- EFS uses NFS port `2049`, not the application port and not the database port.
- One Zone EFS requires ECS tasks to run in the same AZ/subnet as the mount target.
- ALB security group and ECS task security group are different roles; the ALB needs inbound HTTP, while ECS needs inbound app port from the ALB security group.
- Restricting ALB inbound to `My IP` is useful for staging, but the rule may need updating when the admin's public IP changes.
