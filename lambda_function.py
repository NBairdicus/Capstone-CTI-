import json
import boto3
import requests
from bs4 import BeautifulSoup 
from decimal import Decimal
from boto3.dynamodb.conditions import Attr
import hashlib 
import secrets 
import time
import bcrypt

# Initialize DynamoDB resource
dynamodb = boto3.resource('dynamodb')
url_table = dynamodb.Table('URLTable') 
article_table = dynamodb.Table('CTI_Database')
users_table = dynamodb.Table('Users_Database')  
ses_client = boto3.client('ses')

class DecimalEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, Decimal):
            return float(obj) 
        return super(DecimalEncoder, self).default(obj)

def fetch_urls_from_database():
    # Fetch URLs from DynamoDB
    response = url_table.scan()
    urls = [item['url'] for item in response.get('Items', [])] 
    return urls

def fetch_content(url):
    # Fetch content from a given URL
    try:
        response = requests.get(url)
        response.raise_for_status()
        return response.text
    except requests.exceptions.HTTPError as http_err:
        print(f"HTTP error occurred for URL {url}: {http_err}") 
        return None 
    except Exception as e:
        print(f"An error occurred for URL {url}: {e}") 
        return None  

def generate_article_id(url):
    # Generate a unique article ID based on the URL
    parts = url.split('/')
    if parts:
        last_part = parts[-1]
        if last_part:
            return last_part 
    return 'unknown_article_id'

def extract_title(content):
    # Extract the title from the HTML content
    soup = BeautifulSoup(content, 'html.parser')
    title = soup.title.string if soup.title else 'No Title Found'
    return title

def extract_first_lines(content, num_lines=5):
    # Extract the first few lines of content from the HTML
    soup = BeautifulSoup(content, 'html.parser')
    paragraphs = soup.find_all('p') 
    lines = []
    for p in paragraphs[:num_lines]: 
        lines.append(p.get_text(strip=True))  
    return '\n'.join(lines) 

def process_url_feed(url, keywords):
    # Process a URL feed and store the article in DynamoDB if keywords are found
    content = fetch_content(url)
    if content is None:
        return {'url': url, 'status': 'error', 'message': 'Failed to fetch content'}

    article_id = generate_article_id(url) 

    found_keywords = [keyword for keyword in keywords if keyword.lower() in content.lower()]

    if found_keywords:
        title = extract_title(content) 
        first_lines = extract_first_lines(content)  

        article_table.put_item(
            Item={
                'User_ID': f'ARTICLE#{article_id}',
                'article_id': article_id, 
                'content': first_lines, 
                'title': title, 
                'url': url, 
                'type': 'article',
                'likes_count': 0, 
                'saved_count': 0
            }
        )
        print("Stored item with URL:", url)
        return {'url': url, 'status': 'success', 'message': 'Article processed'}
    else:
        return {'url': url, 'status': 'ignored', 'message': 'No relevant keywords found'}

def fetch_all_articles():
    # Fetch all articles from the DynamoDB table
    try:
        response = article_table.scan()
        articles = response.get('Items', []) 
        return create_response(200, articles) 
    except Exception as e:
        print("Error fetching articles:", str(e))
        return create_response(500, {'error': str(e)}) 
           
def search_articles(search_term):
    # Search articles by keyword in title or content
    try:
        response = article_table.scan(
            FilterExpression=
                Attr('title').contains(search_term) | 
                Attr('content').contains(search_term)
        )
        return create_response(200, response['Items'])
    except Exception as e:
        return create_response(500, {'error': str(e)})

def hash_password(password: str) -> str:
    """Hash a password with a randomly-generated salt using bcrypt"""
    if not password:
        raise ValueError("Password cannot be empty")
    if len(password.encode('utf-8')) > 72:
        raise ValueError("Password too long (max 72 bytes)")
    salt = bcrypt.gensalt(rounds=12)
    return bcrypt.hashpw(password.encode('utf-8'), salt).decode('utf-8')

def verify_password(stored_hash: str, provided_password: str) -> bool:
    """Verify a password against a stored hash"""
    try:
        return bcrypt.checkpw(
            provided_password.encode('utf-8'),
            stored_hash.encode('utf-8')
        )
    except (ValueError, TypeError):
        return False

def generate_token():
    # Generate a secure token and expiration timestamp
    token = secrets.token_hex(32)
    expiration = int(time.time()) + 3600 
    return token, expiration

def login_user(username, password):
    # Authenticate user login
    try:
        response = users_table.get_item(Key={'username': username})
        if 'Item' not in response:
            # Use constant-time dummy verification to prevent timing attacks
            verify_password("$2b$12$dummyhashdummyhashdummyhashdummy", "dummy")
            return create_response(401, {'error': 'Invalid username or password'})
            
        user = response['Item']
            
        if user.get('account_locked_until', 0) > time.time():
            return create_response(403, {'error': 'Account temporarily locked due to too many failed attempts'})
        
        # Verify password
        if not verify_password(user['password'], password):
            # Update failed attempts
            failed_attempts = user.get('failed_login_attempts', 0) + 1
            update_expr = 'SET failed_login_attempts = :fails, last_failed_login = :now'
            expr_values = {':fails': failed_attempts, ':now': int(time.time())}
            
            # Lock after 5 failed attempts (15 minutes)
            if failed_attempts >= 5:
                update_expr += ', account_locked_until = :lock_time'
                expr_values[':lock_time'] = int(time.time()) + 900
                
            users_table.update_item(
                Key={'username': username},
                UpdateExpression=update_expr,
                ExpressionAttributeValues=expr_values
            )
            return create_response(401, {'error': 'Invalid username or password'})

        # Successful login - reset counters and generate token
        token, expiration = generate_token()
        
        users_table.update_item(
            Key={'username': username},
            UpdateExpression='SET auth_token = :token, token_expiration = :exp, '
                            'failed_login_attempts = :zero, last_failed_login = :zero, '
                            'account_locked_until = :zero',
            ExpressionAttributeValues={
                ':token': token,
                ':exp': expiration,
                ':zero': 0
            }
        )

        return create_response(200, {
            'message': 'Login successful',
            'token': token,
            'expiration': expiration
        })
        
    except Exception as e:
        return create_response(500, {'error': str(e)})
            
    except Exception as e:
        return {
            'statusCode': 500,
            'body': json.dumps({'error': str(e)})
        }

def register_user(username, password):
    # Register new user with plain text password and send verification email
    try:
        if not username or not password:
            return create_response(400, {'error': 'Username and password are required'})

        response = users_table.get_item(Key={'username': username})
        if 'Item' in response:
            return {
                'statusCode': 400,
                'body': json.dumps({'error': 'Username already exists'})
            }

        hashed_password = hash_password(password)

        verification_token = secrets.token_hex(32)
        verification_expiration = int(time.time()) + 3600 

        users_table.put_item(
            Item={
                'username': username,
                'password': hashed_password, 
                'saved_articles': [], 
                'liked_articles': [],  
                'auth_token': None,
                'token_expiration': 0,
                'verified': False,
                'verification_token': verification_token,
                'verification_expiration': verification_expiration,
                'failed_login_attempts': 0,
                'last_failed_login': 0,
                'account_locked_until': 0
            }
        )

        verification_link = f"https://oqjehb8wu8.execute-api.us-east-1.amazonaws.com/verify?token={verification_token}&email={username}"
        email_body = f"""
            <html>
                <body>
                    <h1>Welcome to Cyber Safe Alert!</h1>
                    <p>Please verify your email address by clicking the link below:</p>
                    <a href="{verification_link}">Verify Email</a>
                    <p>If you did not create an account, please ignore this email.</p>
                </body>
            </html>
        """

        try:
            response = ses_client.send_email(
                Source='cybersafealertverify@gmail.com', 
                Destination={'ToAddresses': [username]},
                Message={
                    'Subject': {'Data': 'Verify Your Email Address'},
                    'Body': {'Html': {'Data': email_body}}
                }
            )
            print("SES Response:", response)
        except Exception as e:
            print("Error sending verification email:", str(e))
            return {
                'statusCode': 500,
                'body': json.dumps({'error': 'Failed to send verification email'})
            }

        return {
            'statusCode': 200,
            'body': json.dumps({'message': 'User registered successfully. Please check your email to verify your account.'})
        }

    except ValueError as e:
        return create_response(400, {'error': str(e)})
    except Exception as e:
        return {
            'statusCode': 500,
            'body': json.dumps({'error': str(e)})
        }

def resend_verification_email(event, context):
    # Resend the verification email to the user
    try:
        body = json.loads(event.get('body', '{}'))
        token = body.get('token')

        if not token:
            return create_response(400, {'error': 'Token is required'})

        response = users_table.scan(
            FilterExpression=Attr('auth_token').eq(token)
        )
        if 'Items' not in response or not response['Items']:
            return create_response(404, {'error': 'User not found'})

        user = response['Items'][0]
        email = user['username']

        verification_token = secrets.token_hex(32)
        verification_expiration = int(time.time()) + 3600

        users_table.update_item(
            Key={'username': email},
            UpdateExpression='SET verification_token = :token, verification_expiration = :exp',
            ExpressionAttributeValues={
                ':token': verification_token,
                ':exp': verification_expiration
            }
        )

        verification_link = f"https://oqjehb8wu8.execute-api.us-east-1.amazonaws.com/verify?token={verification_token}&email={username}"
        email_body = f"""
            <html>
                <body>
                    <h1>Welcome to Cyber Safe Alert!</h1>
                    <p>Please verify your email address by clicking the link below:</p>
                    <a href="{verification_link}">Verify Email</a>
                    <p>If you did not create an account, please ignore this email.</p>
                </body>
            </html>
        """

        ses_client.send_email(
            Source='cybersafealertverify@gmail.com',
            Destination={'ToAddresses': [email]},
            Message={
                'Subject': {'Data': 'Verify Your Email Address'},
                'Body': {'Html': {'Data': email_body}}
            }
        )

        return create_response(200, {'message': 'Verification email sent successfully'})
    except Exception as e:
        return create_response(500, {'error': str(e)})

def verify_email(event, context):
    # Verify user email using the verification token
    try:
        query_params = event.get('queryStringParameters', {})
        token = query_params.get('token')
        email = query_params.get('email')

        if not token or not email:
            return create_response(400, {'error': 'Token and email are required'})

        response = users_table.get_item(Key={'username': email})
        if 'Item' not in response:
            return create_response(404, {'error': 'User not found'})

        user = response['Item']
        stored_token = user.get('verification_token')
        expiration = user.get('verification_expiration')

        if not stored_token or not expiration:
            return create_response(400, {'error': 'Invalid verification request'})

        if stored_token != token or int(time.time()) > expiration:
            return create_response(400, {'error': 'Invalid or expired token'})

        users_table.update_item(
            Key={'username': email},
            UpdateExpression='SET verified = :verified REMOVE verification_token, verification_expiration',
            ExpressionAttributeValues={':verified': True}
        )

        return create_response(200, {'message': 'Email verified successfully'})
    except Exception as e:
        return create_response(500, {'error': str(e)})

def feed_urls(keywords):
    # Process the feed URLs based on the provided keywords
    urls = fetch_urls_from_database() 
    results = []

    for url in urls:
        result = process_url_feed(url, keywords)
        results.append(result)

    return {
        'statusCode': 200,
        'body': json.dumps({'results': results})
    }

def create_response(status_code, body):
    # Create a standardized response format
    return {
        'statusCode': status_code,
        'headers': {
            'Content-Type': 'application/json',
            'Access-Control-Allow-Origin': '*'
        },
        'body': json.dumps(body, cls=DecimalEncoder)
    }

def check_verification_status(event, context):
    # Check if the user's email is verified
    try:
        body = json.loads(event.get('body', '{}'))
        token = body.get('token')

        if not token:
            return create_response(400, {'error': 'Token is required'})

        response = users_table.scan(
            FilterExpression=Attr('auth_token').eq(token)
        )
        if 'Items' not in response or not response['Items']:
            return create_response(404, {'error': 'User not found'})

        user = response['Items'][0]
        verified = user.get('verified', False)

        return create_response(200, {'verified': verified})
    except Exception as e:
        return create_response(500, {'error': str(e)})

def like_article(article_id, token):
    # Toggle like status for an article and update the likes count and liked users
    try:
        print(f"Checking token: {token}")
        response = users_table.scan(
            FilterExpression=Attr('auth_token').eq(token)
        )
        if 'Items' not in response or not response['Items']:
            return create_response(401, {'message': 'Invalid token'})

        user = response['Items'][0]
        if not user.get('verified', False):
            return create_response(403, {'message': 'Please verify your email to like articles'})

        user = response['Items'][0]
        username = user['username']
        print(f"User found: {username}")

        article_response = article_table.get_item(
            Key={'User_ID': f'ARTICLE#{article_id}'}
        )
        
        if 'Item' not in article_response:
            print(f"Article not found: {article_id}")
            return create_response(404, {'message': 'Article not found'})

        article = article_response['Item']
        liked_users = article.get('liked_users', [])
        print(f"Current liked users: {liked_users}")

        if username in liked_users:
            try:
                print(f"Attempting to unlike article for user {username}")
                # User has already liked the article, so unlike it
                update_response = article_table.update_item(
                    Key={'User_ID': f'ARTICLE#{article_id}'},
                    UpdateExpression='SET likes_count = likes_count - :dec, liked_users = :new_list',
                    ExpressionAttributeValues={
                        ':dec': 1,
                        ':new_list': [user for user in liked_users if user != username]
                    },
                    ReturnValues="UPDATED_NEW"
                )
                print(f"Unlike response: {update_response}")
                return create_response(200, {'message': 'Article unliked successfully'})
            except Exception as update_error:
                print(f"Error unliking article: {str(update_error)}")
                return create_response(500, {'error': f'Failed to unlike article: {str(update_error)}'})
        else:
            try:
                print(f"Attempting to like article for user {username}")
                # User has not liked the article, so like it
                update_response = article_table.update_item(
                    Key={'User_ID': f'ARTICLE#{article_id}'},
                    UpdateExpression='SET likes_count = likes_count + :inc, liked_users = list_append(if_not_exists(liked_users, :empty_list), :user)',
                    ExpressionAttributeValues={
                        ':inc': 1,
                        ':user': [username],
                        ':empty_list': []
                    },
                    ReturnValues="UPDATED_NEW"
                )
                print(f"Like response: {update_response}")
                return create_response(200, {'message': 'Article liked successfully'})
            except Exception as update_error:
                print(f"Error liking article: {str(update_error)}")
                return create_response(500, {'error': f'Failed to like article: {str(update_error)}'})
    except Exception as e:
        print(f"General error in like_article: {str(e)}")
        return create_response(500, {'error': str(e)})

def save_article(article_id, token):
    # Save an article and update the saved users list and saved count
    if not token:
        return create_response(401, {'message': 'Missing token'})
    
    user = users_table.scan(
        FilterExpression=Attr('auth_token').eq(token)
    ).get('Items', [None])[0]
    
    if not user:
        return create_response(401, {'message': 'Invalid token'})
        
    if not user.get('verified', False):
        return create_response(403, {'message': 'Please verify your email first'})

    try:
        print(f"Checking token: {token}")
        response = users_table.scan(
            FilterExpression=Attr('auth_token').eq(token)
        )
        if 'Items' not in response or not response['Items']:
            print("Token validation failed")
            return create_response(401, {'message': 'Invalid token'})

        user = response['Items'][0]
        username = user['username']
        print(f"User found: {username}")

        article_response = article_table.get_item(
            Key={'User_ID': f'ARTICLE#{article_id}'}
        )
        
        if 'Item' not in article_response:
            print(f"Article not found: {article_id}")
            return create_response(404, {'message': 'Article not found'})

        article = article_response['Item']
        saved_users = article.get('saved_users', [])
        print(f"Current saved users: {saved_users}")

        if username in saved_users:
            try:
                print(f"Attempting to unsave article for user {username}")
                update_response = article_table.update_item(
                    Key={'User_ID': f'ARTICLE#{article_id}'},
                    UpdateExpression='SET saved_count = saved_count - :dec, saved_users = :new_list',
                    ExpressionAttributeValues={
                        ':dec': 1,
                        ':new_list': [user for user in saved_users if user != username]
                    },
                    ReturnValues="UPDATED_NEW"
                )
                print(f"Unsave response: {update_response}")

                users_table.update_item(
                    Key={'username': username},
                    UpdateExpression='SET saved_articles = :new_list',
                    ExpressionAttributeValues={
                        ':new_list': [article for article in user['saved_articles'] if article != article_id]
                    },
                    ReturnValues="UPDATED_NEW"
                )
                print(f"Updated user's saved articles list")

                return create_response(200, {'message': 'Article unsaved successfully'})
            except Exception as update_error:
                print(f"Error unsaving article: {str(update_error)}")
                return create_response(500, {'error': f'Failed to unsave article: {str(update_error)}'})
        else:
            try:
                print(f"Attempting to save article for user {username}")
                update_response = article_table.update_item(
                    Key={'User_ID': f'ARTICLE#{article_id}'},
                    UpdateExpression='SET saved_count = saved_count + :inc, saved_users = list_append(if_not_exists(saved_users, :empty_list), :user)',
                    ExpressionAttributeValues={
                        ':inc': 1,
                        ':user': [username],
                        ':empty_list': []
                    },
                    ReturnValues="UPDATED_NEW"
                )
                print(f"Save response: {update_response}")

                users_table.update_item(
                    Key={'username': username},
                    UpdateExpression='SET saved_articles = list_append(if_not_exists(saved_articles, :empty_list), :article_id)',
                    ExpressionAttributeValues={
                        ':article_id': [article_id],
                        ':empty_list': []
                    },
                    ReturnValues="UPDATED_NEW"
                )
                print(f"Updated user's saved articles list")

                return create_response(200, {'message': 'Article saved successfully'})
            except Exception as update_error:
                print(f"Error saving article: {str(update_error)}")
                return create_response(500, {'error': f'Failed to save article: {str(update_error)}'})
    except Exception as e:
        print(f"General error in save_article: {str(e)}")
        return create_response(500, {'error': str(e)})

def flag_article(article_id, user_id):
    # Flag an article for admin review
    try:
        user_response = users_table.get_item(Key={'username': user_id})
        if 'Item' not in user_response:
            return create_response(404, {'message': 'User not found'})
            
        flags_used = user_response['Item'].get('flags_used', 0)
        if flags_used >= 5:
            return create_response(400, {'message': 'Flag limit reached'})

        article_table.update_item(
            Key={'User_ID': f'ARTICLE#{article_id}'},
            UpdateExpression='SET flags = if_not_exists(flags, :empty_list) + :flag',
            ExpressionAttributeValues={
                ':flag': 1,
                ':empty_list': 0
            }
        )

        users_table.update_item(
            Key={'username': user_id},
            UpdateExpression='SET flags_used = if_not_exists(flags_used, :zero) + :one',
            ExpressionAttributeValues={
                ':zero': 0,
                ':one': 1
            }
        )

        return create_response(200, {'message': 'Article flagged successfully'})
    except Exception as e:
        return create_response(500, {'error': str(e)})

def review_flagged_article(article_id, is_fake):
    # Admin review of flagged article
    try:
        article_table.update_item(
            Key={'User_ID': f'ARTICLE#{article_id}'},
            UpdateExpression='SET reviewed = :reviewed, is_fake = :fake',
            ExpressionAttributeValues={
                ':reviewed': True,
                ':fake': is_fake
            }
        )
        return create_response(200, {'message': 'Article reviewed successfully'})
    except Exception as e:
        return create_response(500, {'error': str(e)})

def fetch_saved_articles(token):
    # First get user with token verification check
    user = users_table.scan(
        FilterExpression=Attr('auth_token').eq(token)
    ).get('Items', [None])[0]
    
    if not user or not user.get('verified', False):
        return create_response(403, {'message': 'Unauthorized'})
    
    saved_articles = []
    for article_id in user.get('saved_articles', []):
        article = article_table.get_item(
            Key={'User_ID': f'ARTICLE#{article_id}'}
        ).get('Item')
        if article:
            saved_articles.append(article)
    
    return create_response(200, saved_articles)

def fetch_account_info(token):
    user = users_table.scan(
        FilterExpression=Attr('auth_token').eq(token)
    ).get('Items', [None])[0]
    
    if not user:
        return create_response(401, {'message': 'Invalid token'})
    
    if not user.get('verified', False):
        return create_response(403, {'message': 'Email not verified'})
    
    return create_response(200, {
        'username': user['username'],
        'verified': user.get('verified', False)
    })

def follow_user(username, token):
    # Follow a user by adding them to the followed_users list
    try:
        user_response = users_table.get_item(Key={'username': username})
        if 'Item' not in user_response:
            return create_response(404, {'message': 'User not found'})

        response = users_table.scan(
            FilterExpression=Attr('auth_token').eq(token)
        )
        if 'Items' not in response or not response['Items']:
            return create_response(401, {'message': 'Invalid token'})

        user = response['Items'][0]
        current_username = user['username']

        if current_username == username:
            return create_response(400, {'message': "You can't follow yourself"})

        users_table.update_item(
            Key={'username': current_username},
            UpdateExpression='SET followed_users = list_append(if_not_exists(followed_users, :empty_list), :username)',
            ExpressionAttributeValues={
                ':username': [username],
                ':empty_list': []
            },
            ReturnValues="UPDATED_NEW"
        )

        return create_response(200, {'message': 'User followed successfully'})
    except Exception as e:
        return create_response(500, {'error': str(e)})

def unfollow_user(username, token):
    # Unfollow a user by removing them from the followed_users list
    try:
        response = users_table.scan(
            FilterExpression=Attr('auth_token').eq(token)
        )
        if 'Items' not in response or not response['Items']:
            return create_response(401, {'message': 'Invalid token'})

        user = response['Items'][0]
        current_username = user['username']

        followed_users = user.get('followed_users', [])
        if username not in followed_users:
            return create_response(404, {'message': 'User not found in followed list'})

        updated_followed_users = [u for u in followed_users if u != username]
        users_table.update_item(
            Key={'username': current_username},
            UpdateExpression='SET followed_users = :updated_list',
            ExpressionAttributeValues={
                ':updated_list': updated_followed_users
            },
            ReturnValues="UPDATED_NEW"
        )

        return create_response(200, {'message': 'User unfollowed successfully'})
    except Exception as e:
        return create_response(500, {'error': str(e)})

def fetch_users_following(token):
    # Fetch the list of users followed by the user associated with the provided token
    try:
        response = users_table.scan(
            FilterExpression=Attr('auth_token').eq(token)
        )
        if 'Items' not in response or not response['Items']:
            return create_response(401, {'message': 'Invalid token'})

        user = response['Items'][0]
        followed_users = user.get('followed_users', [])
        
        return create_response(200, {'followed_users': followed_users})
    except Exception as e:
        return create_response(500, {'error': str(e)})

def fetch_user_articles(username):
    # Fetch saved articles for a user based on the provided username
    try:
        response = users_table.get_item(Key={'username': username})
        if 'Item' not in response:
            return create_response(404, {'message': 'User not found'})

        user = response['Item']
        saved_article_ids = user.get('saved_articles', [])
        
        articles = []
        for article_id in saved_article_ids:
            article_response = article_table.get_item(
                Key={'User_ID': f'ARTICLE#{article_id}'}
            )
            if 'Item' in article_response:
                articles.append(article_response['Item'])
        
        return create_response(200, articles)
    except Exception as e:
        return create_response(500, {'error': str(e)})

def update_keyword(keyword, token):
    # Update the keyword list for a user based on the provided token
    try:
        response = users_table.scan(
            FilterExpression=Attr('auth_token').eq(token)
        )
        if 'Items' not in response or not response['Items']:
            return create_response(401, {'message': 'Invalid token'})

        user = response['Items'][0]
        username = user['username']
        keywords_list = user.get('keywords_list', [])

        if keyword in keywords_list:
            keywords_list.remove(keyword)
        else:
            keywords_list.append(keyword)

        users_table.update_item(
            Key={'username': username},
            UpdateExpression='SET keywords_list = :keywords_list',
            ExpressionAttributeValues={
                ':keywords_list': keywords_list
            },
            ReturnValues="UPDATED_NEW"
        )

        return create_response(200, {'message': 'Keyword updated successfully'})
    except Exception as e:
        return create_response(500, {'error': str(e)})

def fetch_keywords(token):
    # Fetch the list of keywords for a user based on the provided token
    try:
        response = users_table.scan(
            FilterExpression=Attr('auth_token').eq(token)
        )
        if 'Items' not in response or not response['Items']:
            return create_response(401, {'message': 'Invalid token'})

        user = response['Items'][0]
        keywords_list = user.get('keywords_list', [])
        
        return create_response(200, {'keywords_list': keywords_list})
    except Exception as e:
        return create_response(500, {'error': str(e)})

def lambda_handler(event, context):
    print("Received event:", json.dumps(event, indent=2))
    
    # Parse HTTP API v2 event format
    route_key = event.get('routeKey', '')
    http_method = route_key.split()[0] if route_key else ''
    path = event.get('rawPath', '')
    query_params = event.get('queryStringParameters', {})
    body = json.loads(event.get('body', '{}')) if event.get('body') else {}

    print(f"Route: {route_key}, Method: {http_method}, Path: {path}")

    try:
        if route_key == 'GET /verify':
            return verify_email(event, context)
            
        elif route_key == 'POST /register':
            return register_user(body.get('email'), body.get('password'))
            
        elif route_key == 'POST /login':
            return login_user(body.get('email'), body.get('password'))
            
        elif route_key == 'GET /articles':
            return fetch_all_articles()
            
        elif route_key.startswith('GET /search'):
            search_term = query_params.get('query', '')
            return search_articles(search_term)
            
        elif route_key.startswith('POST /articles/') and route_key.endswith('/like'):
            article_id = path.split('/')[-2]
            return like_article(article_id, body.get('token'))
            
        elif route_key.startswith('POST /articles/') and route_key.endswith('/save'):
            article_id = path.split('/')[-2]
            token = body.get('token')
            if not token:
                return create_response(401, {'message': 'Missing token'})
            return save_article(article_id, token)
            
        elif route_key == 'POST /resend-verification':
            return resend_verification_email(event, context)
            
        elif route_key == 'POST /check-verification':
            return check_verification_status(event, context)
            
        elif route_key.startswith('GET /following/'):
            token = path.split('/')[-1]
            return fetch_users_following(token)
            
        elif route_key.startswith('POST /follow/'):
            username = path.split('/')[-1]
            return follow_user(username, body.get('token'))

        elif route_key.startswith('GET /readlist/'):
            token = path.split('/')[-1]
            return fetch_account_info(token)
            
        elif route_key.startswith('POST /unfollow/'):
            username = path.split('/')[-1]
            return unfollow_user(username, body.get('token'))
            
        elif route_key.startswith('GET /users/') and route_key.endswith('/articles'):
            username = path.split('/')[-2]
            return fetch_user_articles(username)
            
        elif route_key.startswith('POST /keyword/'):
            keyword = path.split('/')[-1]
            return update_keyword(keyword, body.get('token'))
            
        elif route_key.startswith('GET /keyword/'):
            token = path.split('/')[-1]
            return fetch_keywords(token)

        elif route_key == 'POST /feed-urls':
            return feed_urls(body.get('keywords', []))
            
        elif route_key.startswith('GET /article/'):
            article_id = path.split('/')[-1]
            article = get_article(article_id)
            return create_response(200 if article else 404, article or {'message': 'Article not found'})
            
        elif route_key.endswith('/flag'):
            article_id = path.split('/')[-2]
            return flag_article(article_id, body.get('user_id'))
            
        elif route_key.endswith('/review'):
            article_id = path.split('/')[-2]
            return review_flagged_article(article_id, body.get('is_fake'))
            
        elif route_key.startswith('GET /articles/') and not route_key.endswith(('/like', '/save')):
            token = path.split('/')[-1]
            return fetch_saved_articles(token)

        return create_response(404, {'message': 'Route not found'})
        
    except json.JSONDecodeError:
        return create_response(400, {'error': 'Invalid JSON body'})
    except Exception as e:
        print(f"Error in lambda_handler: {str(e)}")
        return create_response(500, {'error': str(e)})