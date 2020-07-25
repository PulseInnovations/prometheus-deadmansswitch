### Prometheus Dead Man's Switch

Deploys a couple of Lambda functions which receive the `Watchdog` webhook from Prometheus/AlertManager and alert to a Slack channel if a Prometheus instance hasn't been heard from for over 5 minutes.

`api.py` is the Lambda responsible for receiving the webhook POST requests and storing the timestamp for each cluster in DynamoDB.
`checker.py` is run in a schedule and checks if any of the timestamps in DynamoDB are more than 5 minutes in the past.

See the docstrings in the code for more detail on how it all works.

