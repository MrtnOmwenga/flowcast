#!/bin/bash
# Create the AWS pieces for the public demo: a budget alert first, then one locked-down
# machine. Prints the plan and stops unless run with --go.
#
#   deploy/aws/provision.sh --email you@example.com [--profile NAME] [--go]
#
# What it creates, all tagged Project=flowcast:
#   - a monthly cost budget of $40 on EC2 and VPC, emailing at 50%, 80% and 100% of actual
#     spend and at 100% of forecast spend
#   - a key pair from a key made locally (~/.ssh/flowcast-aws); the private key never leaves
#     this machine
#   - a security group: web traffic (80, 443) from anywhere, SSH from this machine's address only
#   - a t3a.xlarge (4 vCPU, 16 GB, AMD EPYC) running Ubuntu 24.04, 30 GB encrypted disk,
#     instance metadata v2 only, no IAM role, CPU credits "standard" (it slows down rather
#     than charging extra under sustained load)
set -euo pipefail

REGION=us-east-1
INSTANCE_TYPE=t3a.xlarge
BUDGET=40
NAME=flowcast
KEY=~/.ssh/flowcast-aws
PROFILE_ARGS=()
EMAIL=""
GO=false
while [ $# -gt 0 ]; do
  case $1 in
    --email) EMAIL=$2; shift 2 ;;
    --profile) PROFILE_ARGS=(--profile "$2"); shift 2 ;;
    --go) GO=true; shift ;;
    *) echo "unknown option $1"; exit 1 ;;
  esac
done
[ -n "$EMAIL" ] || { echo "give --email for the budget alerts"; exit 1; }
aws() { command aws "${PROFILE_ARGS[@]}" --region $REGION "$@"; }

ACCOUNT=$(aws sts get-caller-identity --query Account --output text)
MY_IP=$(curl -fsS https://checkip.amazonaws.com | tr -d '[:space:]')
AMI=$(aws ssm get-parameter --name /aws/service/canonical/ubuntu/server/24.04/stable/current/amd64/hvm/ebs-gp3/ami-id \
  --query Parameter.Value --output text)
TAGS="ResourceType=%s,Tags=[{Key=Project,Value=$NAME},{Key=Name,Value=$NAME}]"

cat <<PLAN
Account $ACCOUNT, region $REGION
  budget:          \$$BUDGET a month on EC2 and VPC, alerts to $EMAIL
  key pair:        $NAME (public half of $KEY)
  security group:  $NAME: 80 and 443 from anywhere, 22 from $MY_IP only
  machine:         $INSTANCE_TYPE, Ubuntu 24.04 ($AMI), 30 GB gp3 encrypted, IMDSv2, no IAM role
PLAN
$GO || { echo; echo "Nothing created. Run again with --go to create it."; exit 0; }

# 1. The budget, before anything that costs money
if ! aws budgets describe-budget --account-id "$ACCOUNT" --budget-name $NAME >/dev/null 2>&1; then
  notify() { echo "{\"Notification\":{\"NotificationType\":\"$1\",\"ComparisonOperator\":\"GREATER_THAN\",\"Threshold\":$2,\"ThresholdType\":\"PERCENTAGE\"},\"Subscribers\":[{\"SubscriptionType\":\"EMAIL\",\"Address\":\"$EMAIL\"}]}"; }
  aws budgets create-budget --account-id "$ACCOUNT" \
    --budget "{\"BudgetName\":\"$NAME\",\"BudgetLimit\":{\"Amount\":\"$BUDGET\",\"Unit\":\"USD\"},\"TimeUnit\":\"MONTHLY\",\"BudgetType\":\"COST\",
               \"CostFilters\":{\"Service\":[\"Amazon Elastic Compute Cloud - Compute\",\"EC2 - Other\",\"Amazon Virtual Private Cloud\"]}}" \
    --notifications-with-subscribers "[$(notify ACTUAL 50),$(notify ACTUAL 80),$(notify ACTUAL 100),$(notify FORECASTED 100)]"
  echo "budget created"
fi

# 2. The key pair: made here, only the public half goes to AWS
[ -f $KEY ] || ssh-keygen -t ed25519 -N "" -C $NAME -f $KEY
aws ec2 describe-key-pairs --key-names $NAME >/dev/null 2>&1 || \
  aws ec2 import-key-pair --key-name $NAME --public-key-material "fileb://$KEY.pub" \
    --tag-specifications "$(printf "$TAGS" key-pair)" >/dev/null

# 3. The security group, in the default network
VPC=$(aws ec2 describe-vpcs --filters Name=is-default,Values=true --query 'Vpcs[0].VpcId' --output text)
SG=$(aws ec2 describe-security-groups --filters Name=group-name,Values=$NAME Name=vpc-id,Values=$VPC \
  --query 'SecurityGroups[0].GroupId' --output text)
if [ "$SG" = "None" ]; then
  SG=$(aws ec2 create-security-group --group-name $NAME --description "Flowcast public demo" --vpc-id $VPC \
    --tag-specifications "$(printf "$TAGS" security-group)" --query GroupId --output text)
  aws ec2 authorize-security-group-ingress --group-id $SG --ip-permissions \
    "IpProtocol=tcp,FromPort=80,ToPort=80,IpRanges=[{CidrIp=0.0.0.0/0}]" \
    "IpProtocol=tcp,FromPort=443,ToPort=443,IpRanges=[{CidrIp=0.0.0.0/0}]" \
    "IpProtocol=tcp,FromPort=22,ToPort=22,IpRanges=[{CidrIp=$MY_IP/32,Description=Martin}]" >/dev/null
fi

# 4. The machine
INSTANCE=$(aws ec2 run-instances --image-id "$AMI" --instance-type $INSTANCE_TYPE --key-name $NAME \
  --security-group-ids $SG --credit-specification CpuCredits=standard \
  --metadata-options HttpTokens=required,HttpEndpoint=enabled \
  --block-device-mappings 'DeviceName=/dev/sda1,Ebs={VolumeSize=30,VolumeType=gp3,Encrypted=true,DeleteOnTermination=true}' \
  --tag-specifications "$(printf "$TAGS" instance)" "$(printf "$TAGS" volume)" \
  --query 'Instances[0].InstanceId' --output text)
aws ec2 wait instance-running --instance-ids $INSTANCE
IP=$(aws ec2 describe-instances --instance-ids $INSTANCE --query 'Reservations[0].Instances[0].PublicIpAddress' --output text)
echo "machine $INSTANCE running at $IP"
echo "next: deploy/aws/setup.sh $IP"
