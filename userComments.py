import json
import decimal
import boto3
import time
from boto3.dynamodb.conditions import Key
from datetime import datetime
import urllib.parse

# Initialize DynamoDB resource
dynamodb = boto3.resource('dynamodb')
table = dynamodb.Table('Comments_Table')

# Custom JSON encoder to handle Decimal types
class DecimalEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, decimal.Decimal):
            return float(obj)
        return super(DecimalEncoder, self).default(obj)

def create_response(status_code, body, location=None):
    """Create a standardized response format for API Gateway v2"""
    headers = {
        'Content-Type': 'application/json',
        'Access-Control-Allow-Origin': '*',
        'Access-Control-Allow-Headers': 'content-type,authorization,username',
        'Access-Control-Allow-Methods': 'OPTIONS,POST,GET,PUT',
        'Cache-Control': 'no-cache, no-store, must-revalidate',
        'Pragma': 'no-cache',
        'Expires': '0',
        'X-Content-Type-Options': 'nosniff'
    }
    
    if location:
        headers['Location'] = location

    try:
        # If body is already a string, use it directly
        if isinstance(body, str):
            response_body = body
        else:
            # Otherwise, serialize it with our custom encoder
            response_body = json.dumps(body, cls=DecimalEncoder)
        
        # Create the response dictionary
        response = {
            'statusCode': status_code,
            'headers': headers,
            'body': response_body
        }
        
        # Log the response for debugging
        print(f"Response before serialization: {response}")
        
        # Verify the response can be JSON serialized
        json.dumps(response)
        
        return response
        
    except Exception as e:
        print(f"Error in create_response: {str(e)}")
        # Return a simplified error response
        return {
            'statusCode': 500,
            'headers': {
                'Content-Type': 'application/json',
                'Access-Control-Allow-Origin': '*'
            },
            'body': json.dumps({
                'error': 'Internal server error',
                'details': str(e)
            })
        }

def parse_form_data(body):
    """Parse form data from the request body"""
    result = {}
    if not body:
        return result
        
    for pair in body.split('&'):
        if '=' in pair:
            key, value = pair.split('=', 1)
            result[key] = urllib.parse.unquote_plus(value)
    return result

def extract_article_id(event):
    """Extract article_id from various event formats"""
    # HTTP API v2 format
    if event.get('pathParameters') and event['pathParameters'].get('article_id'):
        return event['pathParameters']['article_id']
    
    # HTTP API v2 rawPath format
    raw_path = event.get('rawPath', '')
    if raw_path and raw_path.startswith('/comment/'):
        parts = raw_path.split('/')
        if len(parts) > 2:
            return parts[2]
            
    # Try resource path + path parameters (REST API)
    if event.get('resource') == '/comment/{article_id}' and event.get('pathParameters'):
        return event['pathParameters'].get('article_id')
        
    return None

def lambda_handler(event, context):
    print("Received event:", json.dumps(event, default=str))
    print("Headers:", json.dumps(event.get('headers', {}), default=str))
    # Handle HTTP API v2 format
    http_method = event.get('requestContext', {}).get('http', {}).get('method', event.get('httpMethod', ''))
    
    # Handle OPTIONS requests for CORS
    if http_method == 'OPTIONS':
        return create_response(200, '')
    
    try:
        # Parse body based on content type
        body = {}
        if 'body' in event and event['body']:
            try:
                if isinstance(event['body'], dict):
                    body = event['body']
                else:
                    body = json.loads(event['body'])
                print("Parsed body:", json.dumps(body, default=str))
            except json.JSONDecodeError:
                print("Failed to parse JSON body")
                return create_response(400, {'error': 'Invalid JSON in request body'})
            except Exception as e:
                print(f"Body parsing error: {str(e)}")
                return create_response(400, {'error': f'Failed to parse request body: {str(e)}'})
        
        if http_method == 'POST':
            article_id = body.get('article_id')
            comment = body.get('comment')
            username = body.get('username', event.get('headers', {}).get('username', 'Anonymous'))
            return_url = body.get('return_url')

            print(f"Processing POST request - article_id: {article_id}, username: {username}")
    
            # Validate input
            if not article_id:
                return create_response(400, {'error': 'Missing article_id'})
            if not comment:
                return create_response(400, {'error': 'Missing comment text'})
    
            try:
                timestamp = int(time.time())
                item = {
                    'article_id': str(article_id),
                    'timestamp': timestamp,
                    'username': username,
                    'comment': comment
                }
        
                print(f"Attempting to save item: {json.dumps(item, default=str)}")
                table.put_item(Item=item)
        
                # Handle redirect if return_url is provided
                if return_url:
                    return create_response(303, '', return_url)
                return create_response(201, {'message': 'Comment created successfully', 'comment': item})
        
            except Exception as e:
                print(f"DynamoDB Error: {str(e)}")
                return create_response(500, {'error': 'Failed to save comment to database'})
        
        # GET comments for an article
        elif http_method == 'GET':
            print("=== START GET REQUEST HANDLING ===")
            print(f"1. Raw Event: {json.dumps(event, default=str)}")
            print(f"2. HTTP Method: {http_method}")
            print(f"3. Path Parameters: {json.dumps(event.get('pathParameters', {}), default=str)}")
            print(f"4. Raw Path: {event.get('rawPath', 'No rawPath')}")


            # Extract article_id from path parameters
            article_id = extract_article_id(event)
            print(f"5. Extracted article_id: {article_id}")
            
            if not article_id:
                print("ERROR: No article_id found in request")
                return create_response(400, {'error': 'Missing article_id parameter'})
            
            try:
                print(f"6. Attempting DynamoDB query for article_id: {article_id}")

                # Query the database for comments related to the article
                response = table.query(
                    KeyConditionExpression=Key('article_id').eq(article_id),
                    ScanIndexForward=False  # Sort in descending order (newest first)
                )

                print(f"7. DynamoDB response: {json.dumps(response, default=str)}")

                items = response.get('Items', [])
                print(f"8. Retrieved {len(items)} comments for article {article_id}")

                # Convert DynamoDB Decimal types to float in items
                formatted_items = []
                for idx, item in enumerate(items):
                    formatted_item = {}
                    for key, value in item.items():
                        if key == 'timestamp':
                            formatted_item[key] = float(value) if isinstance(value, (str, decimal.Decimal)) else value
                        elif isinstance(value, decimal.Decimal):
                            formatted_item[key] = float(value)
                        else:
                            formatted_item[key] = value
                    formatted_items.append(formatted_item)
                    print(f"9. Formatted Item {idx}: {json.dumps(formatted_item, default=str)}")

                print(f"10. Final Formatted Items: {json.dumps(formatted_items, default=str)}")

                response = create_response(200, formatted_items)
                print("=== FINAL RESPONSE TO API GATEWAY ===")
                print(f"Response type: {type(response)}")
                print(f"Response keys: {response.keys()}")
                print(f"Response body type: {type(response['body'])}")
                print(f"Response body: {response['body']}")
                print("=== END FINAL RESPONSE ===")
                return response
            
            except Exception as e:
                error_type = type(e).__name__
                error_message = str(e)
                print(f"Error Type: {error_type}")
                print(f"Error Message: {error_message}")
                print(f"Full error: {e}")
                return create_response(500, {
                    'error': 'Failed to retrieve comments from database',
                    'error_type': error_type,
                    'error_details': error_message
                })
        else:
            return create_response(404, {'error': 'Route not found'})
            
    except Exception as e:
        print(f"Error: {str(e)}")
        return create_response(500, {'error': f'Internal server error: {str(e)}'})