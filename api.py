"""
Prometheus Monitor API

Receives a POST request from API Gateway with the name of a Kubernetes cluster running Prometheus in the path. It then
stores the last time it heard from this cluster in DynamoDB.
"""
import logging
import os
import sys
import time

import boto3
from botocore.exceptions import ClientError

# Set up our logger
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger()

REQUIRED_ENVIRONMENT_VARIABLES = ['ENVIRONMENT_NAME', 'VERIFY_TOKEN']
for env_var in REQUIRED_ENVIRONMENT_VARIABLES:
    if env_var not in os.environ:
        logger.error(f'{env_var} is a required environment variable')
        sys.exit(1)
VERIFY_TOKEN = os.environ['VERIFY_TOKEN']
ENVIRONMENT_NAME = os.environ['ENVIRONMENT_NAME']


def verify_token(event):
    """
    Verifies whether the verification token in provided in the query string is what we expect.

    :param event: The Lambda triggering event
    :return: (bool) Whether the token has been verified or not
    """
    if 'verify_token' in event['query'] and event['query']['verify_token'] == VERIFY_TOKEN:
        logger.info("Successfully verified token")
        return True

    logger.error("Couldn't verify token")
    return False


def dynamodb_write(table_name, cluster_name, epoch_seconds):
    """
    Updates the epoch_seconds field in DynamoDB for a cluster so we know when we last heard from it.

    :param table_name: (str) The name of the DynamoDB table to use
    :param cluster_name: (str) The name of the Kubernetes cluster running Prometheus
    :param epoch_seconds: (int) The last time we heard from the cluster in epoch seconds
    """
    dynamodb = boto3.resource('dynamodb')
    try:
        table = dynamodb.Table(table_name)
        response = table.update_item(
            Key={
                'cluster_name': cluster_name
            },
            UpdateExpression="set epoch_seconds=:e",
            ExpressionAttributeValues={
                ':e': epoch_seconds
            },
            ReturnValues="UPDATED_NEW"
        )
    except ClientError as err:
        logger.critical('DynamoDB Update Encountered an Error')
        logger.critical(err, exc_info=True)
        raise Exception('[InternalServerError] DynamoDB Update Encountered an Error')
    else:
        return response


def webhook(event, context):
    """
    The Lambda handler. Gets the cluster name from the URL path, finds the current time in epoch seconds and updates
    DynamoDB.

    :param event: (map) The Lambda event
    :param context: (map) The Lambda context
    """
    if not verify_token(event):
        return {"statusCode": 400, "body": "Wrong verification token"}

    cluster_name = event['path']['cluster_name']
    epoch_seconds = int(time.time())
    logger.info(f'Writing record for {cluster_name} with timestamp {epoch_seconds} to DynamoDB')
    dynamodb_write(ENVIRONMENT_NAME, cluster_name, epoch_seconds)
    return {"statusCode": 200, "body": str(epoch_seconds)}


if __name__ == "__main__":
    post_event = {'method': 'POST', 'path': {'cluster_name': 'test'}, 'query': {'verify_token': VERIFY_TOKEN}}
    print(webhook(post_event, None))
