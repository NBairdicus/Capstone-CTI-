import json
import boto3

def lambda_handler(event, context):
    # Initialize DynamoDB resource
    dynamodb = boto3.resource('dynamodb')
    table_name = 'CTI_Database'
    table = dynamodb.Table(table_name)
    
    # Extract article ID from the path parameters
    article_id = event['pathParameters']['articleId']
    
    # Get the article from DynamoDB
    try:
        response = table.get_item(Key={'article_id': article_id})
        if 'Item' in response:
            article = response['Item']
            return {
                'statusCode': 200,
                'body': json.dumps(article)
            }
        else:
            return {
                'statusCode': 404,
                'body': json.dumps({'error': 'Article not found'})
            }
    except Exception as e:
        return {
            'statusCode': 500,
            'body': json.dumps({'error': str(e)})
        }
