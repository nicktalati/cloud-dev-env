#!/usr/bin/env python3
"""
deploy.py - Deploy/update CloudFormation stack for T4 GPU development environment
"""

import argparse
import json
import os
import sys
import time
from pathlib import Path

import boto3
from botocore.exceptions import ClientError, WaiterError

# Constants
STACK_NAME = "t4-dev-environment"
TEMPLATE_FILE = "cloudformation.yaml"
REGION = "us-east-1"  # Change to your preferred region
TIMEOUT = 300  # 5 minutes timeout for stack operations


def parse_args():
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(description="Deploy T4 GPU development environment")
    parser.add_argument(
        "--action",
        choices=["create", "update", "delete", "status"],
        required=True,
        help="Action to perform on the CloudFormation stack",
    )
    parser.add_argument("--my-ip", help="Your IP address for SSH access (format: x.x.x.x/32)")
    parser.add_argument("--key-name", help="EC2 Key Pair name for SSH access")
    parser.add_argument(
        "--force", action="store_true", help="Force the action even if conditions aren't ideal"
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=TIMEOUT,
        help=f"Timeout in seconds for stack operations (default: {TIMEOUT})",
    )
    return parser.parse_args()


def read_template():
    """Read CloudFormation template file."""
    template_path = Path(__file__).parent / TEMPLATE_FILE
    if not template_path.exists():
        print(f"Error: Template file {TEMPLATE_FILE} not found")
        sys.exit(1)
    return template_path.read_text()


def get_stack_status(cf_client):
    """Get the current status of the stack."""
    try:
        response = cf_client.describe_stacks(StackName=STACK_NAME)
        return response["Stacks"][0]["StackStatus"]
    except ClientError as e:
        if "does not exist" in str(e):
            return "DOES_NOT_EXIST"
        raise


def get_stack_events(cf_client, limit=5):
    """Get recent stack events."""
    try:
        response = cf_client.describe_stack_events(StackName=STACK_NAME)
        events = response["StackEvents"][:limit]
        return events
    except ClientError:
        return []


def print_stack_events(cf_client, limit=5):
    """Print recent stack events."""
    events = get_stack_events(cf_client, limit)
    if events:
        print("\nRecent stack events:")
        for event in events:
            timestamp = event["Timestamp"].strftime("%Y-%m-%d %H:%M:%S")
            resource_type = event["ResourceType"]
            logical_id = event["LogicalResourceId"]
            status = event.get("ResourceStatus", "N/A")
            reason = event.get("ResourceStatusReason", "")

            # Format the reason for clarity
            reason_str = f" - {reason}" if reason else ""

            print(f"  {timestamp} | {logical_id} ({resource_type}): {status}{reason_str}")
    else:
        print("\nNo stack events found.")


def wait_for_stack_completion(cf_client, action, timeout=TIMEOUT):
    """Wait for the stack operation to complete with a timeout."""
    print(f"Waiting for stack {action} to complete...", end="", flush=True)

    waiter_map = {
        "create": "stack_create_complete",
        "update": "stack_update_complete",
        "delete": "stack_delete_complete",
    }

    waiter = cf_client.get_waiter(waiter_map[action])

    # Add timeout handling
    start_time = time.time()
    elapsed_dots = 0

    try:
        while True:
            # Check if we've exceeded the timeout
            if time.time() - start_time > timeout:
                print("\nTimeout exceeded while waiting for stack operation to complete.")

                # For deletion, specifically check if the stack actually exists
                if action == "delete":
                    try:
                        cf_client.describe_stacks(StackName=STACK_NAME)
                    except ClientError as e:
                        if "does not exist" in str(e):
                            print(
                                "Stack appears to have been successfully deleted despite the timeout."
                            )
                            return True

                print("Stack may still be processing. Check AWS Console for status.")
                print_stack_events(cf_client)
                return False

            try:
                # Special handling for deletion
                if action == "delete":
                    try:
                        cf_client.describe_stacks(StackName=STACK_NAME)
                    except ClientError as e:
                        if "does not exist" in str(e):
                            print(" Done!")
                            return True

                # For other operations, check current stack status to handle errors
                status = get_stack_status(cf_client)

                # If the stack doesn't exist and we're deleting, that's success
                if status == "DOES_NOT_EXIST" and action == "delete":
                    print(" Done!")
                    return True

                # Check for failed states
                if status.endswith("_FAILED"):
                    print(f"\nStack operation failed with status: {status}")

                    try:
                        # Get the reason for the failure
                        response = cf_client.describe_stacks(StackName=STACK_NAME)
                        status_reason = response["Stacks"][0].get(
                            "StackStatusReason", "No reason provided"
                        )
                        print(f"Reason: {status_reason}")
                    except:
                        pass

                    print_stack_events(cf_client)
                    return False

                # Check for rollback states
                if "ROLLBACK" in status:
                    print(f"\nStack is in rollback state: {status}")
                    print_stack_events(cf_client)

                    # If it's a rollback complete, we're done with the operation but it failed
                    if status == "ROLLBACK_COMPLETE":
                        return False

                # If we reach the appropriate completion state, we're done
                if (action == "create" and status == "CREATE_COMPLETE") or (
                    action == "update" and status == "UPDATE_COMPLETE"
                ):
                    print(" Done!")
                    return True

                # Try the waiter (will raise an exception if not done)
                try:
                    waiter.wait(StackName=STACK_NAME, WaiterConfig={"Delay": 5, "MaxAttempts": 1})
                    print(" Done!")
                    return True
                except WaiterError:
                    # Not done yet, continue waiting
                    pass

                # Print a dot to show progress
                print(".", end="", flush=True)
                elapsed_dots += 1

                # Every 30 dots (roughly 2.5 minutes), print the current status
                if elapsed_dots % 30 == 0:
                    print(f"\nCurrent status: {status} (still waiting...)", end="", flush=True)

                time.sleep(5)

            except Exception as e:
                # Handle the case where the stack might not exist anymore during delete
                if action == "delete":
                    try:
                        cf_client.describe_stacks(StackName=STACK_NAME)
                    except ClientError as e:
                        if "does not exist" in str(e):
                            print(" Done!")
                            return True

                # Continue waiting unless it's a fatal error
                if "Waiter encountered a terminal failure state" in str(e):
                    print("\nStack operation failed")
                    print_stack_events(cf_client)
                    return False

                print(".", end="", flush=True)
                elapsed_dots += 1
                time.sleep(5)

    except Exception as e:
        print(f"\nError waiting for stack: {e}")

        # For deletion, check if the stack actually exists despite the error
        if action == "delete":
            try:
                cf_client.describe_stacks(StackName=STACK_NAME)
            except ClientError as e:
                if "does not exist" in str(e):
                    print("Stack was successfully deleted despite the error.")
                    return True

        print_stack_events(cf_client)
        return False


def get_stack_outputs(cf_client):
    """Get the outputs from the CloudFormation stack."""
    try:
        response = cf_client.describe_stacks(StackName=STACK_NAME)
        outputs = response["Stacks"][0].get("Outputs", [])

        if not outputs:
            return {}

        return {output["OutputKey"]: output["OutputValue"] for output in outputs}
    except ClientError:
        return {}


def create_or_update_stack(cf_client, template, parameters, action, timeout=TIMEOUT):
    """Create or update the CloudFormation stack."""
    kwargs = {
        "StackName": STACK_NAME,
        "TemplateBody": template,
        "Parameters": parameters,
        "Capabilities": ["CAPABILITY_IAM", "CAPABILITY_NAMED_IAM"],
    }

    try:
        if action == "create":
            cf_client.create_stack(**kwargs)
        else:  # update
            cf_client.update_stack(**kwargs)
        return wait_for_stack_completion(cf_client, action, timeout)
    except ClientError as e:
        error_message = str(e)

        if "No updates are to be performed" in error_message:
            print("No updates required for the stack.")
            return True

        if "already exists" in error_message and action == "create":
            print(f"Stack {STACK_NAME} already exists. Use --action update to update it.")
            print("Or --action delete to remove it first.")
        else:
            print(f"Error {action}ing stack: {e}")

        return False


def delete_stack(cf_client, timeout=TIMEOUT):
    """Delete the CloudFormation stack."""
    try:
        # First check if stack exists
        status = get_stack_status(cf_client)
        if status == "DOES_NOT_EXIST":
            print(f"Stack {STACK_NAME} does not exist.")
            return True

        cf_client.delete_stack(StackName=STACK_NAME)
        success = wait_for_stack_completion(cf_client, "delete", timeout)

        # Double-check deletion status regardless of waiter result
        try:
            cf_client.describe_stacks(StackName=STACK_NAME)
            print("Warning: Stack might still exist. Check AWS Console for status.")
            return success
        except ClientError as e:
            if "does not exist" in str(e):
                print(f"Stack {STACK_NAME} has been successfully deleted.")
                return True
            else:
                print(f"Error checking stack deletion: {e}")
                return False

    except ClientError as e:
        print(f"Error deleting stack: {e}")
        return False


def print_stack_info(cf_client):
    """Print information about the stack."""
    status = get_stack_status(cf_client)

    if status == "DOES_NOT_EXIST":
        print(f"Stack {STACK_NAME} does not exist.")
        return

    print(f"Stack {STACK_NAME} status: {status}")

    if status.endswith("FAILED") or "ROLLBACK" in status:
        print("\nStack is in a failed or rollback state.")
        print_stack_events(cf_client)

    if status.endswith("_COMPLETE") and not status.startswith("DELETE"):
        outputs = get_stack_outputs(cf_client)
        if outputs:
            print("\nStack Outputs:")
            for key, value in outputs.items():
                print(f"  {key}: {value}")

        # Get instance information
        ec2 = boto3.client("ec2", region_name=REGION)
        response = cf_client.describe_stack_resources(StackName=STACK_NAME)

        instance_ids = []
        for resource in response["StackResources"]:
            if resource["ResourceType"] == "AWS::EC2::Instance":
                instance_ids.append(resource["PhysicalResourceId"])

        if instance_ids:
            print("\nInstance Info:")
            instances = ec2.describe_instances(InstanceIds=instance_ids)
            for reservation in instances["Reservations"]:
                for instance in reservation["Instances"]:
                    print(f"  Instance ID: {instance['InstanceId']}")
                    print(f"  State: {instance['State']['Name']}")
                    print(f"  Instance Type: {instance['InstanceType']}")
                    if "PublicIpAddress" in instance:
                        print(f"  Public IP: {instance['PublicIpAddress']}")
                        print(
                            f"  SSH Command: ssh -i {outputs.get('KeyName', 'your-key')}.pem ec2-user@{instance.get('PublicIpAddress', 'N/A')}"
                        )


def main():
    """Main function."""
    args = parse_args()

    # Initialize AWS clients
    cf_client = boto3.client("cloudformation", region_name=REGION)

    # Check current stack status
    current_status = get_stack_status(cf_client)

    # Handle action
    if args.action == "status":
        print_stack_info(cf_client)
        return

    if args.action == "delete":
        if current_status == "DOES_NOT_EXIST" and not args.force:
            print(f"Stack {STACK_NAME} does not exist.")
            return
        print(f"Deleting stack {STACK_NAME}...")
        success = delete_stack(cf_client, args.timeout)
        if success:
            print(f"Stack {STACK_NAME} deleted successfully.")
        return

    # For create/update actions
    if args.action in ["create", "update"]:
        if args.action == "create" and current_status != "DOES_NOT_EXIST" and not args.force:
            print(f"Stack {STACK_NAME} already exists. Use --action update to update it.")
            print("Or use --action create --force to attempt creation anyway.")
            return
        if args.action == "update" and current_status == "DOES_NOT_EXIST" and not args.force:
            print(f"Stack {STACK_NAME} does not exist. Use --action create to create it.")
            print("Or use --action update --force to attempt update anyway.")
            return

        # Validate required parameters
        if not args.my_ip or not args.key_name:
            print("Error: --my-ip and --key-name are required for create/update actions.")
            return

        # Make sure IP is in CIDR format
        if not args.my_ip.endswith("/32"):
            args.my_ip = f"{args.my_ip}/32"

        # Read CloudFormation template
        template = read_template()

        # Prepare parameters
        parameters = [
            {"ParameterKey": "MyIpAddress", "ParameterValue": args.my_ip},
            {"ParameterKey": "KeyName", "ParameterValue": args.key_name},
        ]

        print(f"{args.action.capitalize()}ing stack {STACK_NAME}...")
        success = create_or_update_stack(cf_client, template, parameters, args.action, args.timeout)

        if success:
            print(f"Stack {STACK_NAME} {args.action}d successfully.")
            print_stack_info(cf_client)


if __name__ == "__main__":
    main()
