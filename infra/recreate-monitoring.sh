#!/bin/sh
# Monitoring as code (stepback 2026-07-14: the alarm existed only in AWS).
# Idempotent: safe to rerun. Requires an authenticated admin session.
set -e
R=eu-west-1
TOPIC=$(aws sns create-topic --name twin-mind-alerts --region $R --query TopicArn --output text)
aws sns subscribe --topic-arn "$TOPIC" --protocol email --notification-endpoint danielpuri1901@gmail.com --region $R || true
aws cloudwatch put-metric-alarm --region $R --alarm-name twin-mind-brief-deadman \
  --alarm-description "Morning brief has not sent in 24h" \
  --namespace TwinMind --metric-name BriefSent --statistic Sum \
  --period 86400 --evaluation-periods 1 --threshold 1 \
  --comparison-operator LessThanThreshold --treat-missing-data breaching --alarm-actions "$TOPIC"
aws cloudwatch put-metric-alarm --region $R --alarm-name twin-mind-watchdog-deadman \
  --alarm-description "brief_check watchdog has not run in 24h - the checker itself is dead" \
  --namespace TwinMind --metric-name WatchdogRan --statistic Sum \
  --period 86400 --evaluation-periods 1 --threshold 1 \
  --comparison-operator LessThanThreshold --treat-missing-data breaching --alarm-actions "$TOPIC"
aws cloudwatch put-metric-alarm --region $R --alarm-name twin-mind-prep-poller-deadman \
  --alarm-description "background-prep poller has not run in 3h (should tick every 15 min)" \
  --namespace TwinMind --metric-name PrepPollerRan --statistic Sum \
  --period 10800 --evaluation-periods 1 --threshold 1 \
  --comparison-operator LessThanThreshold --treat-missing-data breaching --alarm-actions "$TOPIC"
echo "monitoring recreated: 3 metrics, 3 dead-man alarms, 1 topic"
