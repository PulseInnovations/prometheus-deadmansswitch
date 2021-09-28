"""
Prometheus Monitor Checker

Runs on a schedule and sends an alert to slack if any of the Prometheus Clusters stored in DynamoDB have failed to check
in for over 5 minutes. Also sets a flag in DynamoDB so a recovery message can be sent.

"""
import sys
import time
import os
import logging
from datetime import datetime

import boto3
from botocore.exceptions import ClientError

here = os.path.dirname(os.path.realpath(__file__))
sys.path.append(os.path.join(here, "./vendored"))
import requests
from croniter import croniter

# Set up our logger
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger()


REQUIRED_ENVIRONMENT_VARIABLES = ['ENVIRONMENT_NAME', 'MAX_TIME_SECONDS', 'SLACK_CHANNEL', 'SLACK_TOKEN']
for env_var in REQUIRED_ENVIRONMENT_VARIABLES:
    if env_var not in os.environ:
        logger.error(f'{env_var} is a required environment variable')
        sys.exit(1)

ENVIRONMENT_NAME = os.environ['ENVIRONMENT_NAME']
MAX_TIME_SECONDS = os.environ['MAX_TIME_SECONDS']
SLACK_CHANNEL = os.environ['SLACK_CHANNEL']
SLACK_TOKEN = os.environ['SLACK_TOKEN']

SCALE_DOWN_CLUSTERS = []
SCALE_UP_CRON = ""
SCALE_DOWN_CRON = ""
if 'SCALE_DOWN_CLUSTERS' in os.environ:
    if 'SCALE_UP_CRON' not in os.environ:
        logger.error('SCALE_UP_CRON is a required environment variable if SCALED_DOWN_CLUSTERS set')
        sys.exit(1)
    if 'SCALE_DOWN_CRON' not in os.environ:
        logger.error('SCALE_DOWN_CRON is a required environment variable if SCALED_DOWN_CLUSTERS set')
        sys.exit(1)

    SCALE_DOWN_CLUSTERS.extend(os.environ['SCALE_DOWN_CLUSTERS'].split(","))
    SCALE_UP_CRON = os.environ['SCALE_UP_CRON']
    SCALE_DOWN_CRON = os.environ['SCALE_DOWN_CRON']


def check_cluster_cron(cluster_name):
    """
    Returns False if the cluster is scaled down according to configured variables. Otherwise True.

    :param cluster_name: (str) The name of the cluster to use
    :return: Whether or not we should process the cluster
    """
    # Process as normal if the cluster isn't in the cluster list
    if cluster_name not in SCALE_DOWN_CLUSTERS:
        return True

    # If the cron expressions are invalid process the cluster
    if not croniter.is_valid(SCALE_DOWN_CRON) or not croniter.is_valid(SCALE_UP_CRON):
        logger.warning(f"Cron expression invalid. Processing {cluster_name} as normal.")
        return True

    # If the cluster scaled down then don't process the cluster
    now = datetime.now()
    last_scale_down = croniter(SCALE_DOWN_CRON, now).get_prev(datetime)
    last_scale_up = croniter(SCALE_UP_CRON, now).get_prev(datetime)
    if last_scale_down > last_scale_up:
        logger.info(f"Cluster {cluster_name} is scaled down. Not processing.")
        return False

    logger.info(f"Cluster {cluster_name} is scaled up. Processing as normal.")
    return True


def dynamodb_scan(table_name):
    """
    Returns the full list of clusters in the DynamoDB table and the last time they checked in (seconds since epoch)

    :param table_name: (str) The name of the DynamoDB table to use
    :return: The list of clusters in the DynamoDB table
    """
    dynamodb = boto3.resource('dynamodb')
    table = dynamodb.Table(table_name)
    scan_kwargs = {
        'ProjectionExpression': "cluster_name, epoch_seconds, error_state"
    }

    dynamodb_records = []
    done = False
    start_key = None
    try:
        while not done:
            if start_key:
                scan_kwargs['ExclusiveStartKey'] = start_key
            response = table.scan(**scan_kwargs)
            dynamodb_records.extend(response.get('Items', []))
            start_key = response.get('LastEvaluatedKey', None)
            done = start_key is None
    except ClientError as err:
        logger.critical('DynamoDB Scan Encountered an Error')
        logger.critical(err, exc_info=True)
        sys.exit(1)
    else:
        return dynamodb_records


def dynamodb_update(table_name, cluster_name, error_state):
    """
    Updates the error_state field in DynamoDB for a cluster so we know whether an alert has previously been sent.

    :param table_name: (str) The name of the DynamoDB table to use
    :param cluster_name: (str) The name of the Kubernetes cluster running Prometheus
    :param error_state: (bool) Whether the cluster is in an error state
    """
    dynamodb = boto3.resource('dynamodb')
    try:
        table = dynamodb.Table(table_name)
        table.update_item(
            Key={
                'cluster_name': cluster_name
            },
            UpdateExpression="set error_state=:e",
            ExpressionAttributeValues={
                ':e': error_state
            },
            ReturnValues="UPDATED_NEW"
        )
    except ClientError as err:
        logger.warning('DynamoDB Update Encountered an Error')
        logger.warning(err, exc_info=True)


def send_slack_notification(notification_text, error=True):
    """
    Sends a slack notification with specified text

    :param notification_text: (str) The text to include in the message
    :param error: (bool) Whether this is an error alert or a recovery
    """
    if error:
        slack_text = '*Prometheus Instance Not Responding*\n' \
                     'A Prometheus instance has not checked in for over 5 minutes\n' \
                     + notification_text
    else:
        slack_text = '*Prometheus Instance Recovered*\n' \
                     'A Prometheus instances has recovered\n' \
                     + notification_text

    json_message = {
        'token': SLACK_TOKEN,
        'channel': SLACK_CHANNEL,
        'as_user': 'false',
        'icon_emoji': ':computer:',
        'username': 'Prometheus Monitor',
        'text': slack_text
    }

    try:
        slack_response = requests.post('https://slack.com/api/chat.postMessage', json_message)
        slack_response.raise_for_status()
    except requests.RequestException as err:
        logger.error('Post to Slack API encountered an error')
        logger.error(err, exc_info=True)


def check(event, context):
    """
    The Lambda handler. Queries DynamoDB, iterates over the returned clusters and sends Slack messages if they have
    failed to check in within the last 5 minutes, or if they have recovered.

    :param event: (map) The Lambda event
    :param context: (map) The Lambda context
    """
    clusters = dynamodb_scan(ENVIRONMENT_NAME)

    for cluster in clusters:
        now = int(time.time())
        cluster_name = cluster['cluster_name']
        if not check_cluster_cron(cluster_name):
            continue

        time_since_check_in = now - cluster['epoch_seconds']

        if time_since_check_in > int(MAX_TIME_SECONDS):
            logger.error(f'Time since {cluster_name} checked in is {time_since_check_in} seconds')
            logger.info(f'Sending alert Slack notification for {cluster_name}')
            send_slack_notification(f'Time since {cluster_name} checked in is {time_since_check_in} seconds')
            dynamodb_update(ENVIRONMENT_NAME, cluster_name, True)
        else:
            logger.info(f'Time since {cluster_name} checked in is {time_since_check_in} seconds')
            if 'error_state' in cluster and cluster['error_state']:
                logger.info(f'Sending recovery Slack notification for {cluster_name}')
                send_slack_notification(f'Time since {cluster_name} checked in is {time_since_check_in} seconds',
                                        error=False)
            dynamodb_update(ENVIRONMENT_NAME, cluster_name, False)


if __name__ == "__main__":
    check(None, None)
