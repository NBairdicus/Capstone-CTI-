import json
import boto3

accountability_function_name = "AccountabilityScoreFunction" # Need to change to actual function name
integrity_function_name = "IntegrityCheckFunction" # Need to change to actual function name
client = boto3.client('lambda')

def lambda_handler(event, context):
    articles = event['articles']
    
    for article in articles:
        content = article['content']
        
        # Get Accountability Score
        accountability_response = client.invoke(
            FunctionName=accountability_function_name,
            Payload=json.dumps({'content': content})
        )
        accountability_result = json.loads(accountability_response['Payload'].read())
        article['accountability_score'] = accountability_result['accountability_score']
        
        # Integrity Check
        similar_article_found = False
        for other_article in articles:
            if article == other_article:
                continue
            
            integrity_response = client.invoke(
                FunctionName=integrity_function_name,
                Payload=json.dumps({'article1': content, 'article2': other_article['content']})
            )
            integrity_result = json.loads(integrity_response['Payload'].read())
            
            if integrity_result['integrity_check']:
                article['integrity_check'] = 1
                similar_article_found = True
                break
        
        if not similar_article_found:
            article['integrity_check'] = 0

    return {
        'statusCode': 200,
        'body': json.dumps(articles)
    }
