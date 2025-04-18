import boto3
import requests
import json
import os
import time

# Initialize DynamoDB client
dynamodb = boto3.resource('dynamodb')
table = dynamodb.Table('CTI_Database')  # Replace with your DynamoDB table name

# Initialize OpenAI API key
openai_api_key = os.environ['OPENAI_API_KEY']

def call_openai_api(prompt):
    """
    Sends a prompt to the OpenAI API and returns the response.
    """
    headers = {
        "Authorization": f"Bearer {openai_api_key}",
        "Content-Type": "application/json"
    }
    data = {
        "model": "gpt-3.5-turbo",
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": 10,
        "temperature": 0.5
    }
    try:
        # Add a delay to avoid hitting the rate limit
        time.sleep(1)  # 1-second delay between requests
        response = requests.post(
            "https://api.openai.com/v1/chat/completions",
            headers=headers,
            json=data
        )
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        print(f"API Request Failed: {e}")
        print(f"Response: {response.text if 'response' in locals() else 'No response'}")
        raise

def score_article(article_text):
    """
    Scores an article based on accountability using the OpenAI API.
    """
    try:
        prompt = f"""
        Evaluate the following article based on accountability. Provide a score between 1 and 100.
        Article:
        {article_text}
        Respond with only a number between 1 and 100.
        """
        
        response = call_openai_api(prompt)
        print("OpenAI API Response:", json.dumps(response, indent=2))
        
        if "choices" not in response or not response["choices"]:
            # Fallback: Return a default score if the API fails
            print("OpenAI API failed. Using fallback score.")
            return 50  # Default score
        
        generated_text = response['choices'][0]['message']['content'].strip()
        try:
            score = int(generated_text)
            if score < 1 or score > 100:
                raise ValueError("Score out of range")
            return score
        except ValueError:
            print("AI did not return a valid number. Using fallback score.")
            return 50  # Default score
    
    except Exception as e:
        print(f"Error scoring article: {e}")
        return 50  # Default score

def lambda_handler(event, context):
    """
    AWS Lambda handler function.
    """
    try:
        # Scan the DynamoDB table to fetch all articles
        response = table.scan()
        articles = response.get('Items', [])
        
        # Process each article
        for article in articles:
            article_id = article['User_ID']
            article_text = article['content']
            
            # Check if the article has already been scored
            if 'accountability_score' not in article or article['accountability_score'] is None:
                # Score the article
                score = score_article(article_text)
                print(f"Scored article {article_id} with score: {score}")
                
                # Update the DynamoDB table with the score
                table.update_item(
                    Key={'User_ID': article_id},  # Replace with your primary key
                    UpdateExpression="SET accountability_score = :score",
                    ExpressionAttributeValues={":score": score}
                )
            else:
                print(f"Article {article_id} already scored. Skipping.")
        
        return {
            'statusCode': 200,
            'body': json.dumps({'message': 'Articles scored and updated successfully'})
        }
    
    except Exception as e:
        print(f"Error: {e}")
        return {
            'statusCode': 500,
            'body': json.dumps({'error': str(e)})
        }