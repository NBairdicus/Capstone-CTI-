import bcrypt

def lambda_handler(event, context):
    hashed = bcrypt.hashpw(b"test", bcrypt.gensalt(rounds=12))
    return {"statusCode": 200, "body": hashed.decode()}
