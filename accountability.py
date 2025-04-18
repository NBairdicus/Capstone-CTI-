import json
import openai
from pydantic import BaseModel, ValidationError

class Article(BaseModel):
    content: str

def lambda_handler(event, context):
    try:
        # Parse the event body using pydantic
        article = Article(**json.loads(event['body']))
        
        # Prompt for OpenAI API
        prompt = f"Evaluate the following article and provide an accountability score from 0 to 100: {article.content}"
        
        # Call the OpenAI API
        openai.api_key = 'YOUR_API_KEY'
        response = openai.Completion.create(
            engine="davinci-codex",
            prompt=prompt,
            max_tokens=10,
            n=1,
            stop=None,
            temperature=0.5,
        )
        
        # Get the accountability score from the response
        score = int(response.choices[0].text.strip())
        
        return {
            'statusCode': 200,
            'body': json.dumps({'accountability_score': score})
        }
    except ValidationError as e:
        return {
            'statusCode': 400,
            'body': json.dumps({'error': e.errors()})
        }
