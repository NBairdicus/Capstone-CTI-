import json
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

def lambda_handler(event, context):
    # Extract the article contents from the event body
    body = json.loads(event['body'])
    article1 = body['article1']
    article2 = body['article2']
    
    # Compare the articles
    documents = [article1, article2]
    vectorizer = TfidfVectorizer(Lowecase=True).fit_transform(documents)
    vectors = vectorizer.toarray()
    similarity = cosine_similarity(vectors)
    integrity_check = similarity[0, 1] > 0.45  # Threshold for similarity
    
    # Return the integrity check result as JSON
    return {
        'statusCode': 200,
        'body': json.dumps({'integrity_check': int(integrity_check)})
    }
