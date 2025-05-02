import json
import boto3
import requests
from bs4 import BeautifulSoup
from urllib.parse import urlparse, urljoin
import hashlib

# Initialize DynamoDB resource
dynamodb = boto3.resource('dynamodb')
url_table = dynamodb.Table('URLTable')
article_table = dynamodb.Table('CTI_Database')

def fetch_urls_from_database():
    """Fetch URLs from DynamoDB"""
    print("Fetching URLs from DynamoDB...")
    response = url_table.scan()
    urls = [item['url'] for item in response.get('Items', [])]
    print(f"Fetched {len(urls)} URLs from DynamoDB.")
    return urls

def fetch_content(url):
    """Fetch content from a given URL with a timeout and headers"""
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,image/apng,*/*;q=0.8',
        'Accept-Language': 'en-US,en;q=0.9',
    }
    print(f"Fetching content from: {url}")
    try:
        response = requests.get(url, headers=headers, timeout=(3.05, 5))  # Add headers
        response.raise_for_status()
        print(f"Successfully fetched content from: {url}")
        return response.text
    except requests.exceptions.Timeout:
        print(f"Timeout occurred for URL {url}")
        return None
    except requests.exceptions.HTTPError as http_err:
        print(f"HTTP error occurred for URL {url}: {http_err}")
        return None
    except Exception as e:
        print(f"An error occurred for URL {url}: {e}")
        return None

def extract_title(content):
    """Extract the title from the HTML content"""
    soup = BeautifulSoup(content, 'html.parser')
    title = soup.title.string if soup.title else 'No Title Found'
    return title

def extract_first_lines(content, num_lines=5):
    """Extract the first few lines of content from the HTML"""
    soup = BeautifulSoup(content, 'html.parser')
    paragraphs = soup.find_all('p')
    lines = []
    for p in paragraphs[:num_lines]:
        lines.append(p.get_text(strip=True))
    return '\n'.join(lines)

def clean_content(content):
    """Remove unwanted phrases from the content"""
    return content.replace("Share this article:", "").strip()

def is_homepage(url):
    """Check if the URL is a homepage"""
    parsed_url = urlparse(url)
    return parsed_url.path in ('', '/') or url.endswith('/feed/')

def is_article_url(url):
    """Check if the URL is likely an article URL"""
    content = fetch_content(url)
    if content is None:
        return False

    soup = BeautifulSoup(content, 'html.parser')
    
    # Check for OpenGraph metadata
    og_type = soup.find('meta', property='og:type')
    if og_type and og_type.get('content') == 'article':
        return True

    # Check for common article tags
    article_tags = soup.find_all(['article', 'div'], class_=['article', 'post', 'entry'])
    if article_tags:
        return True

    # Check URL patterns
    article_patterns = ['article', 'news', 'post', '2025', '2024', 'cybercrime', 'threats', 'blog']
    return (any(pattern in url for pattern in article_patterns) and 
            not any(fragment in url for fragment in ['#comments', '#', '?']) and
            url.count('/') >= 4 and
            not any(exclude in url for exclude in ['/category/', '/tag/', '/feed/', '/about/', '/contact/']))

def extract_articles_from_homepage(homepage_url):
    """Extract article links from the homepage"""
    print(f"Extracting articles from homepage: {homepage_url}")
    content = fetch_content(homepage_url)
    if content is None:
        return []

    soup = BeautifulSoup(content, 'html.parser')
    article_links = []

    for link in soup.find_all('a', href=True):
        href = link['href']
        full_url = urljoin(homepage_url, href)
        
        if full_url.startswith(homepage_url) and is_article_url(full_url):
            article_links.append(full_url)
            if len(article_links) >= 5:  # Limit to 5 articles per homepage
                break

    print(f"Found {len(article_links)} articles on homepage: {homepage_url}")
    return article_links

def generate_article_id(url):
    """Generate a unique article ID based on the URL"""
    return hashlib.md5(url.encode()).hexdigest()

def process_url_feed(url, keywords):
    """Process a URL feed and store or update the article in DynamoDB"""
    print(f"Processing URL: {url}")
    if is_homepage(url):
        print(f"URL is a homepage: {url}")
        article_links = extract_articles_from_homepage(url)
        results = []
        articles_added = 0

        for article_url in article_links:
            if articles_added >= 2:  # Limit to 2 articles per homepage
                break

            content = fetch_content(article_url)
            if content:
                title = extract_title(content)
                first_lines = extract_first_lines(content)
                cleaned_content = clean_content(first_lines)

                if not cleaned_content or "No Title Found" in title:
                    print(f"Ignoring invalid article: {article_url}")
                    continue

                article_id = generate_article_id(article_url)
                user_id = f'ARTICLE#{article_id}'
                
                article_table.put_item(
                    Item={
                        'User_ID': user_id,
                        'article_id': article_id,
                        'title': title,
                        'url': article_url,
                        'content': cleaned_content,
                        'likes_count': 0,
                        'saved_count': 0,
                        'type': 'article'
                    }
                )
                results.append({'url': article_url, 'status': 'success', 'message': 'Article processed'})
                articles_added += 1
            else:
                print(f"Failed to fetch content for article: {article_url}")
        return results
    else:
        print(f"URL is not a homepage: {url}")
        content = fetch_content(url)
        if content is None:
            return {'url': url, 'status': 'error', 'message': 'Failed to fetch content'}

        title = extract_title(content)
        first_lines = extract_first_lines(content)
        cleaned_content = clean_content(first_lines)

        if not cleaned_content or "No Title Found" in title:
            print(f"Ignoring invalid article: {url}")
            return {'url': url, 'status': 'ignored', 'message': 'Invalid article'}

        article_id = generate_article_id(url)
        user_id = f'ARTICLE#{article_id}'
        
        existing_item = article_table.get_item(Key={'User_ID': user_id})
        if 'Item' in existing_item:
            article_table.update_item(
                Key={'User_ID': user_id},
                UpdateExpression="SET #title = :title, #url = :url, content = :content, article_id = :article_id",
                ExpressionAttributeNames={
                    '#title': 'title',
                    '#url': 'url'
                },
                ExpressionAttributeValues={
                    ':title': title,
                    ':url': url,
                    ':content': cleaned_content,
                    ':article_id': article_id
                }
            )
            return {'url': url, 'status': 'updated', 'message': 'Article updated'}
        else:
            article_table.put_item(
                Item={
                    'User_ID': user_id,
                    'article_id': article_id,
                    'title': title,
                    'url': url,
                    'content': cleaned_content,
                    'likes_count': 0,
                    'saved_count': 0,
                    'type': 'article'
                }
            )
            return {'url': url, 'status': 'success', 'message': 'Article processed'}

def lambda_handler(event, context):
    """Main handler for processing feed URLs"""
    try:
        body = json.loads(event['body'])
        keywords = body.get('keywords', [])
        
        if not keywords:
            return {
                'statusCode': 400,
                'body': json.dumps({'error': 'Keywords are required'})
            }
        
        # Fetch URLs from the database
        urls = fetch_urls_from_database()
        results = []

        # Process only the first 5 URLs for testing
        for url in urls[:10]:
            result = process_url_feed(url, keywords)
            results.append(result)

        return {
            'statusCode': 200,
            'body': json.dumps({'results': results})
        }
    
    except Exception as e:
        return {
            'statusCode': 500,
            'body': json.dumps({'error': str(e)})
        }