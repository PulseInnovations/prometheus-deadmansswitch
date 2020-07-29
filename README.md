### Prometheus Dead Man's Switch

Deploys a couple of Lambda functions which receive the `Watchdog` webhook from Prometheus/AlertManager and alert to a Slack channel if a Prometheus instance hasn't been heard from for over 5 minutes.

It uses API Gateway, DynamoDB and Lambda.

- `api.py` is the Lambda responsible for receiving the webhook POST requests and storing the timestamp for each cluster in DynamoDB.
- `checker.py` is run in a schedule and checks if any of the timestamps in DynamoDB are more than 5 minutes in the past.

## Deployment

1. Install the [Serverless Framework](https://github.com/serverless/serverless), python3 and pip

2. Install the dependencies with `pip3 install -t vendored/ -r requirements.txt`

3. Run the deploy command:
```
sls deploy --region eu-west-1 --bucket your-bucket --verify-token YOUROWNVERIFYTOKEN --slack-channel your-slack-channel --slack-token your-slack-bot-token
```

Where:
- `region` is your chosen AWS region
- `bucket` is a pre-existing S3 bucket where the Serverless Framework can store state
- `verify-token` is a made up token which matches your Alert Manager configuration (see below)
- `slack-channel` is the name of your Slack channel
- `slack-token` is a Slack bot token with access to post to the Slack channel

## Alert Manager configuration

For this to work you must first have a `Watchdog` Prometheus Rule like in [coreos/kube-prometheus](https://github.com/coreos/kube-prometheus/blob/master/examples/existingrule.yaml) or the [stable/prometheus-operator](https://github.com/helm/charts/blob/09afc289103a1250f4a7111c87286c72e602ea08/stable/prometheus-operator/templates/prometheus/rules/general.rules.yaml#L34) Helm Chart.

Example receiver configuration:
```
    - name: prometheus_deadmansswitch
      webhook_configs:
      -  url: "https://example.execute-api.us-east-1.amazonaws.com/prod/my-cluster-name?verify_token=YOUROWNVERIFYTOKEN"
```
This URL will be output by the `sls deploy` command above.

Example route configuration:
```
      routes:
      - match:
          alertname: Watchdog
        receiver: prometheus_deadmansswitch
        repeat_interval: 1m
```
