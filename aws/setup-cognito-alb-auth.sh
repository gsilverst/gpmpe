#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'USAGE'
Usage:
  setup-cognito-alb-auth.sh \
    --region us-east-2 \
    --app-host app.example.com \
    --certificate-arn arn:aws:acm:...:certificate/... \
    --load-balancer-arn arn:aws:elasticloadbalancing:...:loadbalancer/app/... \
    --target-group-arn arn:aws:elasticloadbalancing:...:targetgroup/... \
    --ecs-task-role-name gpmpe-ecs-task-role \
    [--name-prefix gpmpe-staging] \
    [--cognito-domain-prefix gpmpe-staging-433249887797]

Creates a Cognito user pool, app client, hosted UI domain, HTTPS ALB listener
with authenticate-cognito, and an IAM policy allowing the ECS task role to
invite users with Cognito AdminCreateUser.

Prerequisites:
  - app-host must already resolve to the ALB, or be ready to do so.
  - certificate-arn must be an ACM certificate in the same region as the ALB.
  - The ALB security group must allow inbound HTTPS/443 from the desired clients.
USAGE
}

REGION=""
APP_HOST=""
CERTIFICATE_ARN=""
LOAD_BALANCER_ARN=""
TARGET_GROUP_ARN=""
ECS_TASK_ROLE_NAME=""
NAME_PREFIX="gpmpe-staging"
COGNITO_DOMAIN_PREFIX=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --region) REGION="$2"; shift 2 ;;
    --app-host) APP_HOST="$2"; shift 2 ;;
    --certificate-arn) CERTIFICATE_ARN="$2"; shift 2 ;;
    --load-balancer-arn) LOAD_BALANCER_ARN="$2"; shift 2 ;;
    --target-group-arn) TARGET_GROUP_ARN="$2"; shift 2 ;;
    --ecs-task-role-name) ECS_TASK_ROLE_NAME="$2"; shift 2 ;;
    --name-prefix) NAME_PREFIX="$2"; shift 2 ;;
    --cognito-domain-prefix) COGNITO_DOMAIN_PREFIX="$2"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown argument: $1" >&2; usage; exit 2 ;;
  esac
done

if [[ -z "$REGION" || -z "$APP_HOST" || -z "$CERTIFICATE_ARN" || -z "$LOAD_BALANCER_ARN" || -z "$TARGET_GROUP_ARN" || -z "$ECS_TASK_ROLE_NAME" ]]; then
  usage >&2
  exit 2
fi

ACCOUNT_ID="$(aws sts get-caller-identity --query Account --output text)"
if [[ -z "$COGNITO_DOMAIN_PREFIX" ]]; then
  COGNITO_DOMAIN_PREFIX="${NAME_PREFIX}-${ACCOUNT_ID}"
fi

CALLBACK_URL="https://${APP_HOST}/oauth2/idpresponse"
LOGOUT_URL="https://${APP_HOST}/"
USER_POOL_NAME="${NAME_PREFIX}-users"
CLIENT_NAME="${NAME_PREFIX}-alb"
POLICY_NAME="${NAME_PREFIX}-cognito-admin-create-user"

echo "Creating Cognito user pool: ${USER_POOL_NAME}"
USER_POOL_ID="$(
  aws cognito-idp create-user-pool \
    --region "$REGION" \
    --pool-name "$USER_POOL_NAME" \
    --username-attributes email \
    --auto-verified-attributes email \
    --policies 'PasswordPolicy={MinimumLength=12,RequireUppercase=true,RequireLowercase=true,RequireNumbers=true,RequireSymbols=false,TemporaryPasswordValidityDays=7}' \
    --account-recovery-setting 'RecoveryMechanisms=[{Priority=1,Name=verified_email}]' \
    --query 'UserPool.Id' \
    --output text
)"
USER_POOL_ARN="arn:aws:cognito-idp:${REGION}:${ACCOUNT_ID}:userpool/${USER_POOL_ID}"

echo "Creating Cognito app client: ${CLIENT_NAME}"
USER_POOL_CLIENT_ID="$(
  aws cognito-idp create-user-pool-client \
    --region "$REGION" \
    --user-pool-id "$USER_POOL_ID" \
    --client-name "$CLIENT_NAME" \
    --generate-secret \
    --allowed-o-auth-flows-user-pool-client \
    --allowed-o-auth-flows code \
    --allowed-o-auth-scopes openid email profile \
    --supported-identity-providers COGNITO \
    --callback-urls "$CALLBACK_URL" \
    --logout-urls "$LOGOUT_URL" \
    --query 'UserPoolClient.ClientId' \
    --output text
)"

echo "Creating Cognito hosted UI domain: ${COGNITO_DOMAIN_PREFIX}"
aws cognito-idp create-user-pool-domain \
  --region "$REGION" \
  --user-pool-id "$USER_POOL_ID" \
  --domain "$COGNITO_DOMAIN_PREFIX" >/dev/null

POLICY_DOCUMENT="$(
  printf '{"Version":"2012-10-17","Statement":[{"Effect":"Allow","Action":["cognito-idp:AdminCreateUser","cognito-idp:AdminGetUser"],"Resource":"%s"}]}' "$USER_POOL_ARN"
)"

echo "Granting ECS task role permission to invite Cognito users"
aws iam put-role-policy \
  --role-name "$ECS_TASK_ROLE_NAME" \
  --policy-name "$POLICY_NAME" \
  --policy-document "$POLICY_DOCUMENT" >/dev/null

echo "Creating HTTPS listener with authenticate-cognito"
HTTPS_LISTENER_ARN="$(
  aws elbv2 create-listener \
    --region "$REGION" \
    --load-balancer-arn "$LOAD_BALANCER_ARN" \
    --protocol HTTPS \
    --port 443 \
    --certificates CertificateArn="$CERTIFICATE_ARN" \
    --ssl-policy ELBSecurityPolicy-TLS13-1-2-2021-06 \
    --default-actions \
      Type=authenticate-cognito,Order=1,AuthenticateCognitoConfig="{UserPoolArn=${USER_POOL_ARN},UserPoolClientId=${USER_POOL_CLIENT_ID},UserPoolDomain=${COGNITO_DOMAIN_PREFIX},SessionCookieName=AWSELBAuthSessionCookie,Scope='openid email profile',OnUnauthenticatedRequest=authenticate}" \
      Type=forward,Order=2,TargetGroupArn="$TARGET_GROUP_ARN" \
    --query 'Listeners[0].ListenerArn' \
    --output text
)"

cat <<SUMMARY

Created Cognito/ALB authentication resources.

Set these ECS task environment values:
  AUTH_MODE=alb_oidc
  COGNITO_REGION=${REGION}
  COGNITO_USER_POOL_ID=${USER_POOL_ID}

Keep AUTH_BOOTSTRAP_TOKEN in Secrets Manager only long enough for first setup.

Resource outputs:
  USER_POOL_ID=${USER_POOL_ID}
  USER_POOL_ARN=${USER_POOL_ARN}
  USER_POOL_CLIENT_ID=${USER_POOL_CLIENT_ID}
  COGNITO_DOMAIN_PREFIX=${COGNITO_DOMAIN_PREFIX}
  HTTPS_LISTENER_ARN=${HTTPS_LISTENER_ARN}

Validate:
  https://${APP_HOST}/auth/status
  https://${APP_HOST}/setup
SUMMARY
