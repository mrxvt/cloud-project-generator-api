import azure.functions as func
import logging
import os
import json
import time
from azure.core.credentials import AzureKeyCredential
from azure.search.documents import SearchClient
from azure.search.documents.models import Vector
import openai
from tenacity import retry, wait_random_exponential, stop_after_attempt


cog_search_endpoint = os.environ['cognitive_search_api_endpoint']
cog_search_key = os.environ['cognitive_search_api_key']
prompt = os.environ['prompt']


openai.api_type = os.environ['openai_api_type']
openai.api_key = os.environ['openai_api_key']
openai.api_base = os.environ['openai_api_endpoint']
openai.api_version = os.environ['openai_api_version']
embeddings_deployment = os.environ['openai_embeddings_deployment']
completions_deployment = os.environ['openai_completions_deployment']
cog_search_cred = AzureKeyCredential(cog_search_key)
index_name = "project-generator-index"

app = func.FunctionApp(http_auth_level=func.AuthLevel.FUNCTION)


@app.route(route="http_trigger")
@app.function_name('http_trigger')
def http_trigger(req: func.HttpRequest) -> func.HttpResponse:
    logging.info('Python HTTP trigger function processed a request.')

    prompt = req.params.get('prompt')
    if not prompt:
        try:
            req_body = req.get_json()
        except ValueError:
            print("Caught ValueError for invalid JSON")
            return func.HttpResponse(
                body=json.dumps({'message': 'Invalid JSON request body and no prompt in the query string'}),
                status_code=400
            )
        else:
            prompt = req_body.get('prompt')
    if prompt:
        results_for_prompt = vector_search(prompt)
        completions_results = generate_completion(results_for_prompt, prompt)
        project = (completions_results['choices'][0]['message']['content'])
        try:
            project = json.loads(project)
        except ValueError:
            print("Caught ValueError for invalid JSON")
            return func.HttpResponse(
                body=json.dumps({'message': 'API was unable to generate proper JSON response'}),
                status_code=400
            )
        else:
            return func.HttpResponse(
                body=json.dumps(project),
                status_code=200,
                mimetype="application/json"
            )
        


@retry(wait=wait_random_exponential(min=1, max=20), stop=stop_after_attempt(10))
def generate_embeddings(text):
    '''
    Generate embeddings from string of text.
    This will be used to vectorize data and user input for interactions with Azure OpenAI.
    '''
    response = openai.Embedding.create(
        input=text, engine=embeddings_deployment)
    embeddings = response['data'][0]['embedding']
    time.sleep(0.5)  # rest period to avoid rate limiting on AOAI for free tier
    return embeddings


def generate_completion(results, user_input):
    """
    Generates a chatbot response using Azure OpenAI based on the user's input and a list related services from Azure Cognitive Search.

    Args:
        results (list): A list of possible services to use.
        user_input (str): The user's input.

    Returns:
        dict: A dictionary containing the model's response.
    """
    

    messages = [
        {"role": "system", "content": prompt},
        {"role": "user", "content": user_input},
    ]

    for item in results:
        messages.append({"role": "system", "content": item['service_name']})

    response = openai.ChatCompletion.create(
        engine=completions_deployment, messages=messages)

    return response


def vector_search(query):
    """
    Searches for documents in the index that are similar to the given query vector.

    Args:
        query (str): The query string to search for.

    Returns:
        SearchResult: The search result object containing the matching documents.
    """
    search_client = SearchClient(
        cog_search_endpoint, index_name, cog_search_cred)
    results = search_client.search(
        search_text="",
        vector=Vector(value=generate_embeddings(
            query), k=3, fields="certificationNameVector"),
        select=["certification_name", "service_name", "category"]
    )
    return results
