#send_email.py
import boto3
import json
from aws_lambda_powertools import Logger

logger = Logger()
ses = boto3.client('ses')

def handler(event, context):
    try:
        response = ses.send_email(
            Source=event['source_email'],
            Destination={'ToAddresses': [event['recipient']},
            Message={
                'Subject': {'Data': event['subject']},
                'Body': {'Html': {'Data': event['body_html']}
            }
        )
        logger.info(f"Email sent to {event['recipient']}", message_id=response['MessageId'])
        return {'status': 'success'}
        
    except ses.exceptions.MessageRejected as e:
        logger.error("Invalid email address", error=str(e))
        raise
    except Exception as e:
        logger.error("SES failure", error=str(e))
        # Lambda will automatically retry twice
        raise