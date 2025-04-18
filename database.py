import boto3
import urllib3
import hashlib
import json
import re
from bs4 import BeautifulSoup

# Initialize DynamoDB and HTTP client
dynamodb = boto3.resource('dynamodb')
table = dynamodb.Table('CTI_Database')
http = urllib3.PoolManager()

def add_user(User_ID, password):
    try:
        print(f"Adding user: {User_ID}")
        response = table.put_item(
            Item={
                'User_ID': User_ID,
                'password': password,
                'read_list': []
            }
        )   
        print("DynamoDB response for user creation:", response)
        return True
    except Exception as e:
        print(f"Error adding user: {e}")
        return False

def get_read_list(User_ID):
    try:
        print(f"Getting read list for user: {User_ID}")
        response = table.get_item(Key={'User_ID': User_ID})
        print("DynamoDB response for read list:", response)
        return response['Item']['read_list']
    except Exception as e:
        print(f"Error getting user read list: {e}")
        return []

def add_to_read_list(User_ID, read_list):
    try:
        print(f"Adding to read list for user: {User_ID}")
        response = table.update_item(
            Key={'User_ID': User_ID},
            UpdateExpression='SET read_list = list_append(if_not_exists(read_list, :empty_list), :read_list)',
            ExpressionAttributeValues={':empty_list': [], ':read_list': read_list}
        )
        print("DynamoDB response for read list update:", response)
        return True
    except Exception as e:
        print(f"Error adding to read list: {e}")
        return False

def add_article(article_id, title, content):
    try:
        print(f"Adding article: {article_id}, {title}")
        # Limit content size for DynamoDB
        if len(content) > 400000:  # DynamoDB has a 400KB item size limit
            content = content[:400000] + "... (content truncated)"
            
        response = table.put_item(
            Item={
                'User_ID': f"ARTICLE#{article_id}",
                'article_id': article_id,
                'type': 'article',
                'title': title,
                'content': content
            }
        )
        print("DynamoDB response for article creation:", response)
        return True
    except Exception as e:
        print(f"Error adding article: {e}")
        return False

def get_article(article_id):
    try:
        print(f"Getting article: {article_id}")
        response = table.get_item(Key={'User_ID': f"ARTICLE#{article_id}"})
        print("DynamoDB response for article retrieval:", response)
        if 'Item' in response:
            return {
                'article_id': response['Item']['article_id'],
                'title': response['Item']['title'],
                'content': response['Item']['content']
            }
        return None
    except Exception as e:
        print(f"Error getting article: {e}")
        return None

def process_url_feed(url, keywords):
    try:
        print(f"Starting to process URL: {url}")
        
        # Generate unique article ID from URL
        article_id = hashlib.md5(url.encode()).hexdigest()[:10]
        print(f"Generated article_id: {article_id}")
        
        # Fetch webpage with error handling
        try:
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
            }
            print(f"Sending request to: {url}")
            response = http.request('GET', url, headers=headers, timeout=10.0)
            print(f"Got response from {url}, status code: {response.status}")
            content = response.data.decode('utf-8')  # Get full content
        except Exception as e:
            print(f"Request error: {str(e)}")
            return {
                'url': url,
                'status': 'failed',
                'error': f'Request failed: {str(e)}'
            }
        
        # Parse HTML content with Beautiful Soup
        soup = BeautifulSoup(content, 'html.parser')
        
        # Extract title
        title = soup.title.string if soup.title else f"Article from {url}"
        title = title.strip()
        
        # Extract main content (you can customize this to extract specific elements)
        paragraphs = soup.find_all('p')
        article_content = "\n\n".join([p.get_text() for p in paragraphs])
        
        # Check for keywords in the content
        if any(keyword.lower() in article_content.lower() for keyword in keywords):
            # Store in database
            try:
                success = add_article(
                    article_id=article_id,
                    title=title,
                    content=article_content
                )
                print(f"Database storage result: {success}")
            except Exception as e:
                print(f"Database error: {str(e)}")
                return {
                    'url': url,
                    'status': 'failed',
                    'error': f'Database error: {str(e)}'
                }
            
            if success:
                return {
                    'article_id': article_id,
                    'title': title,
                    'url': url,
                    'status': 'success'
                }
            else:
                return {
                    'url': url,
                    'status': 'failed',
                    'error': 'Failed to store in database'
                }
        else:
            print(f"No relevant keywords found in {url}. Article ignored.")
            return {
                'url': url,
                'status': 'ignored',
                'message': 'No relevant keywords found'
            }
            
    except Exception as e:
        print(f"Unexpected error: {str(e)}")
        return {
            'url': url,
            'status': 'failed',
            'error': str(e)
        }