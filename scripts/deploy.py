import argparse
import sys
import time
from pathlib import Path

import boto3
from botocore.exceptions import ClientError

STACK_NAME = "gpu-dev-env"
TEMPLATE_FILE = "cloudformation/dev-environment.yaml"
REGION = "us-east-1"

def parse_args():
    parser = argparse.ArgumentParser(description="Deploy/Update/Delete GPU Dev Environment")
    parser.add_argument("--action", choices=["create", "update", "delete", "status"], required=True)
    parser.add_argument("--my-ip", help="Your IP in CIDR, e.g., 1.2.3.4/32", default="0.0.0.0/0")
    parser.add_argument("--key-name", help="EC2 Key Pair name")
    parser.add_argument("--instance-type", help="EC2 instance type", default="g4dn.xlarge")
    parser.add_argument("--volume-size", help="Root volume (GB)", default=100, type=int)
    return parser.parse_args()

def read_template():
    template_path = Path(__file__).parent.parent / TEMPLATE_FILE
    if not template_path.exists():
        print(f"Error: Template {template_path} not found.")
        sys.exit(1)
    return template_path.read_text()

def get_stack_status(cf, stack_name):
    """Retrieve the stack status and outputs"""
    try:
        resp = cf.describe_stacks(StackName=stack_name)
        stack = resp["Stacks"][0]
        status = stack["StackStatus"]
        outputs = {o["OutputKey"]: o["OutputValue"] for o in stack.get("Outputs", [])}
        return status, outputs
    except ClientError as e:
        if "does not exist" in str(e):
            return "DOES_NOT_EXIST", {}
        raise

def main():
    args = parse_args()
    cf = boto3.client("cloudformation", region_name=REGION)

    if args.action == "delete":
        status = get_stack_status(cf, STACK_NAME)
        if status == "DOES_NOT_EXIST":
            print(f"Stack {STACK_NAME} does not exist.")
            return
        print(f"Deleting stack {STACK_NAME}...")
        cf.delete_stack(StackName=STACK_NAME)
        return

    if args.action == "status":
        status, outputs = get_stack_status(cf, STACK_NAME)
        print(f"Stack {STACK_NAME} status: {status}")

        ssh_command = outputs.get("SSHCommand")
        if ssh_command:
            print(f"SSH Command: {ssh_command}")
        else:
            print("SSH Command not available. Stack might not be fully created yet.")
        return

    if args.key_name is None:
        raise ValueError("key-name is required for action 'create' or 'update'")

    template_body = read_template()
    parameters = [
        {"ParameterKey": "MyIpAddress", "ParameterValue": args.my_ip},
        {"ParameterKey": "KeyName", "ParameterValue": args.key_name if args.key_name else ""},
        {"ParameterKey": "InstanceType", "ParameterValue": args.instance_type},
        {"ParameterKey": "VolumeSize", "ParameterValue": str(args.volume_size)},
    ]

    kwargs = {
        "StackName": STACK_NAME,
        "TemplateBody": template_body,
        "Parameters": parameters,
        "Capabilities": ["CAPABILITY_IAM", "CAPABILITY_NAMED_IAM"],
    }

    try:
        if args.action == "create":
            print(f"Creating stack {STACK_NAME}...")
            cf.create_stack(**kwargs)
        elif args.action == "update":
            print(f"Updating stack {STACK_NAME}...")
            cf.update_stack(**kwargs)
    except ClientError as e:
        if "No updates are to be performed" in str(e):
            print("No updates required.")
        else:
            print(f"Error: {e}")

if __name__ == "__main__":
    main()
