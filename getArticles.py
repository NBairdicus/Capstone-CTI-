import json
import boto3
from decimal import Decimal

# Helper function to convert Decimal objects to float
def decimal_default(obj):
    if isinstance(obj, Decimal):
        return float(obj)  # Convert Decimal to float
    raise TypeError(f"Object of type {type(obj)} is not JSON serializable")

def lambda_handler(event, context):
    # Initialize DynamoDB resource
    dynamodb = boto3.resource('dynamodb')
    table_name = 'CTI_Database'
    table = dynamodb.Table(table_name)
    
    try:
        # Scan the table to get all articles
        response = table.scan()
        articles = response.get('Items', [])
        
        # Prepare the response with accountability scores
        scored_articles = []
        for article in articles:
            scored_articles.append({
                'article_id': article.get('article_id', 'N/A'),
                'title': article.get('title', 'N/A'),
                'content': article.get('content', 'N/A')[:150] + '...',  # Truncate content
                'url': article.get('url', 'N/A'),
                'likes_count': int(article.get('likes_count', 0)),  # Convert to int
                'saved_count': int(article.get('saved_count', 0)),  # Convert to int
                'accountability_score': article.get('accountability_score', 'N/A')
            })
        
        return {
            'statusCode': 200,
            'headers': {
                'Content-Type': 'application/json',
                'Access-Control-Allow-Origin': '*'  # Enable CORS
            },
            'body': json.dumps({'articles': scored_articles}, ensure_ascii=False, default=decimal_default)  # Preserve Unicode and handle Decimal
        }
    
    except Exception as e:
        return {
            'statusCode': 500,
            'headers': {
                'Content-Type': 'application/json',
                'Access-Control-Allow-Origin': '*'  # Enable CORS
            },
            'body': json.dumps({'error': str(e)}, ensure_ascii=False, default=decimal_default)  # Preserve Unicode and handle Decimal
        }