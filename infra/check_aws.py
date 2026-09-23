#!/usr/bin/env python3
"""Read-only checks for the Twin Mind AWS cleanup. Never fetches secret values."""
import datetime
import json
import os
import subprocess
from pathlib import Path

ACCOUNT = os.environ['TWIN_AWS_ACCOUNT_ID']  # private: set in .env, never committed
ALERT_EMAIL = os.environ['ALERT_EMAIL']
REGION = 'eu-west-1'
TRAIL = 'twin-mind-account'
LOG_GROUP = '/aws/bedrock/model-invocations'
PROFILES = {
    'twin-mind-sonnet': ('twin-mind', 'r9bht745cst4'),
    'agentlab-sonnet': ('agentlab', 'mfzwa25maf8z'),
    'agentlab-haiku': ('agentlab', 'kpbqsnaqf2ti'),
}


def aws(service, operation, **parameters):
    command = ['aws', service, operation, '--region', REGION, '--output', 'json']
    for key, value in parameters.items():
        command.extend(['--' + key.replace('_', '-'),
                        json.dumps(value) if isinstance(value, (dict, list)) else str(value)])
    result = subprocess.run(command, capture_output=True, text=True, check=True)
    return json.loads(result.stdout) if result.stdout.strip() else {}


def main():
    print('Verified at', datetime.datetime.now(datetime.timezone.utc).isoformat())
    assert aws('sts', 'get-caller-identity')['Account'] == ACCOUNT
    subscriptions = aws('ce', 'get-anomaly-subscriptions')['AnomalySubscriptions']
    alert = next(s for s in subscriptions if s['SubscriptionName'] == 'Default-Services-Subscription')
    assert alert['Subscribers'] == [{'Address': ALERT_EMAIL, 'Type': 'EMAIL', 'Status': 'CONFIRMED'}]
    expression = alert['ThresholdExpression']
    if isinstance(expression, str):
        expression = json.loads(expression)
    assert expression == {'Dimensions': {'Key': 'ANOMALY_TOTAL_IMPACT_ABSOLUTE', 'Values': ['10'], 'MatchOptions': ['GREATER_THAN_OR_EQUAL']}}
    assert alert['Frequency'] == 'DAILY' and alert['MonitorArnList']
    print('PASS anomaly alert: owner email, $10')

    trail = aws('cloudtrail', 'get-trail', name=TRAIL)['Trail']
    assert trail['IsMultiRegionTrail'] and trail['LogFileValidationEnabled'] and trail['IncludeGlobalServiceEvents']
    selectors = aws('cloudtrail', 'get-event-selectors', trail_name=TRAIL)['EventSelectors']
    assert any(x['IncludeManagementEvents'] and x['ReadWriteType'] == 'All' and not x.get('ExcludeManagementEventSources') for x in selectors)
    status = aws('cloudtrail', 'get-trail-status', name=TRAIL)
    assert status['IsLogging'] and status.get('LatestDeliveryTime') and status.get('LatestCloudWatchLogsDeliveryTime')
    assert not status.get('LatestDeliveryError') and not status.get('LatestCloudWatchLogsDeliveryError')
    for key in ('LatestDeliveryTime', 'LatestCloudWatchLogsDeliveryTime'):
        timestamp = datetime.datetime.fromisoformat(status[key])
        assert (datetime.datetime.now(datetime.timezone.utc) - timestamp).total_seconds() < 3600, 'Delivery older than one hour: ' + key
    print('PASS CloudTrail: recent S3 and CloudWatch delivery')
    alarms = aws('cloudwatch', 'describe-alarms', alarm_name_prefix='twin-mind-security-')['MetricAlarms']
    filters = json.loads((Path(__file__).parent / 'security-filters.json').read_text())
    expected_names = {'twin-mind-security-' + f['filterName'] for f in filters}
    assert {a['AlarmName'] for a in alarms} == expected_names
    live_filters = aws('logs', 'describe-metric-filters', log_group_name='/aws/cloudtrail/' + TRAIL)['metricFilters']
    assert [{k: f[k] for k in ('filterName', 'filterPattern', 'metricTransformations')} for f in live_filters] == filters
    for alarm in alarms:
        assert alarm['Namespace'] == 'TwinMind/Security' and alarm['MetricName'] == alarm['AlarmName'].removeprefix('twin-mind-security-')
        assert alarm['Period'] == 300 and alarm['EvaluationPeriods'] == 1 and alarm['Threshold'] == 1
        assert alarm['ComparisonOperator'] == 'GreaterThanOrEqualToThreshold' and alarm['TreatMissingData'] == 'notBreaching'
        assert alarm['ActionsEnabled'] and alarm['AlarmActions'] == [f'arn:aws:sns:{REGION}:{ACCOUNT}:twin-mind-alerts']
    subscribers = aws('sns', 'list-subscriptions-by-topic', topic_arn=f'arn:aws:sns:{REGION}:{ACCOUNT}:twin-mind-alerts')['Subscriptions']
    assert any(x['Protocol'] == 'email' and x['Endpoint'] == ALERT_EMAIL and x['SubscriptionArn'].startswith('arn:') for x in subscribers)
    print('PASS four security alarms: exact filters, thresholds, and confirmed SNS subscriber')

    config = aws('bedrock', 'get-model-invocation-logging-configuration')['loggingConfig']
    for modality in ('text', 'image', 'embedding', 'video', 'audio'):
        assert config[modality + 'DataDeliveryEnabled'] is False
    assert config['cloudWatchConfig']['logGroupName'] == LOG_GROUP
    events = aws('logs', 'get-log-events', log_group_name=LOG_GROUP,
                 log_stream_name='aws/bedrock/modelinvocations', limit=100)['events']
    count = 0
    for event in events:
        try:
            record = json.loads(event['message'])
        except json.JSONDecodeError:
            continue  # Bedrock's plain-text permission verification message.
        if record.get('schemaType') != 'ModelInvocationLog':
            continue
        for side in ('input', 'output'):
            assert not any('body' in key.lower() or 's3' in key.lower() for key in record.get(side, {}))
        count += 1
    assert count > 0
    print(f'PASS Bedrock metadata: {count} records inspected, no body or S3 body references')

    for name, (project, identifier) in PROFILES.items():
        arn = f'arn:aws:bedrock:{REGION}:{ACCOUNT}:application-inference-profile/{identifier}'
        profile = aws('bedrock', 'get-inference-profile', inference_profile_identifier=arn)
        assert profile['status'] == 'ACTIVE' and profile['inferenceProfileName'] == name
        tags = aws('bedrock', 'list-tags-for-resource', resource_arn=arn)['tags']
        assert {'key': 'project', 'value': project} in tags
    assert aws('ce', 'list-cost-allocation-tags', tag_keys=['project'])['CostAllocationTags'][0]['Status'] == 'Active'
    for name, project in [('twin-mind-monthly', 'twin-mind'), ('agentlab-monthly-cost', 'agentlab'), ('account-monthly', None)]:
        budget = aws('budgets', 'describe-budget', account_id=ACCOUNT, budget_name=name)['Budget']
        expected = {'TagKeyValue': ['user:project$' + project]} if project else {}
        assert (budget.get('CostFilters') or {}) == expected
        assert not budget['CostTypes']['IncludeCredit'] and not budget['CostTypes']['IncludeRefund']
        assert float(budget['BudgetLimit']['Amount']) == 50
        filename = {'twin-mind-monthly': 'budget.json', 'agentlab-monthly-cost': 'agentlab-budget.json', 'account-monthly': 'account-budget.json'}[name]
        template = json.loads((Path(__file__).parent / filename).read_text())
        assert template['BudgetName'] == name and (template.get('CostFilters') or {}) == expected
        assert not template['CostTypes']['IncludeCredit'] and not template['CostTypes']['IncludeRefund']
        assert float(template['BudgetLimit']['Amount']) == float(budget['BudgetLimit']['Amount'])
        notifications = aws('budgets', 'describe-notifications-for-budget', account_id=ACCOUNT, budget_name=name)['Notifications']
        expected_alerts = {'twin-mind-monthly': {('ACTUAL', 50), ('ACTUAL', 80), ('ACTUAL', 100)}, 'agentlab-monthly-cost': {('ACTUAL', 80)}, 'account-monthly': {('ACTUAL', 80), ('ACTUAL', 100), ('FORECASTED', 100)}}[name]
        assert {(n['NotificationType'], n['Threshold']) for n in notifications} == expected_alerts
        for notification in notifications:
            assert notification['ComparisonOperator'] == 'GREATER_THAN'
            recipients = aws('budgets', 'describe-subscribers-for-notification', account_id=ACCOUNT, budget_name=name, notification=notification)['Subscribers']
            assert {'SubscriptionType': 'EMAIL', 'Address': ALERT_EMAIL} in recipients
    print('PASS tagged profiles and $50 project/account budgets; billing totals require later reconciliation')

    users = {u['UserName'] for u in aws('iam', 'list-users')['Users']}
    assert not users.intersection({'nathan-bedrock', 'daniel-iam', 'BedrockAPIKey-150t'})
    assert {'daniel-admin', 'BedrockAPIKey-edsw'}.issubset(users)
    print('PASS dormant IAM cleanup; live judge user retained')


if __name__ == '__main__':
    main()
