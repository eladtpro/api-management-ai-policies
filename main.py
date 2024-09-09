import concurrent.futures
import requests
import argparse
import time
import datetime
from colorama import Fore, Style, init
import os

# Initialize colorama
init(autoreset=True)

def get_prompt(max_tokens):
    return {
        "messages": [
            {
                "role": "assistant",
                "content": (
                    "I am writing a blog post for small business owners. "
                    "Provide an outline with 5 sections on 'Effective Marketing Strategies for Small Businesses'.\n\n"
                    "The outline should include an introduction and conclusion, and focus on the following topics:\n\n"
                    "- Understanding your target audience\n"
                    "- Content, social media, and email marketing strategies\n"
                    "- Measuring marketing success\n\n"
                    "The outline should clearly articulate the topic, and provide clear structure to ease reading for the target audience."
                )
            }
        ],
        "temperature": 1,
        "top_p": 1,
        "n": 1,
        "stream": False,
        "max_tokens": max_tokens,
        "presence_penalty": 0,
        "frequency_penalty": 0,
        "logit_bias": {}
    }   

def build_response(index, response):
    backend = response.headers.get("backend-host", "Unknown")
    remaining_tokens = response.headers.get("x-ratelimit-remaining-tokens", "Unknown")
    remaining_requests = response.headers.get("x-ratelimit-remaining-requests", "Unknown")
    consumed_tokens = response.headers.get("consumed-tokens", "Unknown")
    status_code = response.status_code
    status_reason = response.reason
    return {
        "index": index,
        "backend_host": backend,
        "status_code": status_code,
        "status_reason": status_reason,
        "remaining_tokens": remaining_tokens,
        "consumed_tokens": consumed_tokens,
        "remaining_requests": remaining_requests
    }

def make_request(index, apim_name, api_key, max_tokens):
    # Define the API endpoint
    # https://learn.microsoft.com/en-us/azure/ai-services/openai/reference#chat-completions
    # POST https://{endpoint}/openai/deployments/{deployment-id}/chat/completions?api-version=2024-06-01
    api_endpoint = f'https://{apim_name}.azure-api.net/openai/deployments/gpt-4o/chat/completions?api-version=2024-06-01'
    headers = {
        'api-key': api_key,
        'Content-Type': 'application/json',
        'Ocp-Apim-Trace': 'true'
    }
    payload = get_prompt(max_tokens)  
    response = requests.post(api_endpoint, headers=headers, json=payload)
    return build_response(index, response)

# Function to run requests in batches
def main():
    parser = argparse.ArgumentParser(description='Call the main API with APIM name and API key.')
    parser.add_argument('--apim-name', required=True, help='The APIM name')
    parser.add_argument('--subscription-key', required=True, help='The API key')
    parser.add_argument('--workers', type=int, default=20, help='The number of parallel requests')
    parser.add_argument('--total-requests', type=int, default=200, help='The total number of requests')
    parser.add_argument('--request-max-tokens', type=int, default=200, help='The maximum number of tokens per request')
    parser.add_argument('--request-limit', type=int, default=20, help='The request limit per time window')
    args = parser.parse_args()

    apim_name = args.apim_name
    api_key = args.subscription_key or os.environ.get('APIM_SUBSCRIPTION_KEY')
    batch_size = args.workers
    total_requests = args.total_requests
    max_tokens = args.request_max_tokens

    start_time = time.time()
    request_count = 0
    time_window = 10  # Time window in seconds
    request_limit = args.request_limit  # Request limit per time window 3*50 = 150, 150/6 = 25

    formatted_start_time = datetime.datetime.fromtimestamp(start_time).strftime('%Y-%m-%d %H:%M:%S')
    print(f'{Fore.CYAN}Starting {formatted_start_time} {total_requests} requests with {batch_size} workers. Time window: {time_window} seconds. Request limit: {request_limit}, Max tokens: {max_tokens}, APIM: {apim_name}')

    with concurrent.futures.ThreadPoolExecutor(max_workers=batch_size) as executor:
        for i in range(0, total_requests, batch_size):
            batch_indices = range(i, min(i + batch_size, total_requests))
            future_to_index = {executor.submit(make_request, index, apim_name, api_key, max_tokens): index for index in batch_indices}
            for future in concurrent.futures.as_completed(future_to_index):
                index = future_to_index[future]
                try:
                    result = future.result()
                    request_count += 1
                    elapsed_time = time.time() - start_time

                    # Check if the time window has passed
                    if elapsed_time >= time_window:
                        print(f'{Fore.CYAN}Requests in the last {time_window} seconds: {request_count}')
                        start_time = time.time()
                        if request_count > request_limit:
                            print(f'{Fore.YELLOW}Request limit exceeded (approx 50 per endpoint). Sleeping for 10 seconds...')
                            time.sleep(10)
                        request_count = 0                        

                    # Check if the request count exceeds the limit
                    if request_count > request_limit:
                        print(f'{Fore.YELLOW}Request limit exceeded (approx 50 per endpoint). Sleeping for 10 seconds...')
                        time.sleep(10)
                        start_time = time.time()
                        request_count = 0                    

                    if result["backend_host"] == "PoolIsInactive" and result["status_code"] == 503:
                        print(Fore.YELLOW + f'Backend pool has no available endpoint. Waiting for 30 seconds before retrying...')
                        time.sleep(30)
                        request_count = 0
                        result = make_request(index, apim_name, api_key, max_tokens)
                    print(f'{Fore.GREEN}# {result["index"]}: {result["status_code"]}, Backend: {result["backend_host"]}, Remaining(T): {result["remaining_tokens"]}, Consumed: {result["consumed_tokens"]}, Remaining(R): {result["remaining_requests"]}, Reason: {result["status_reason"]}')
                except Exception as e:
                    print(f'{Fore.RED}Request {index} generated an exception: {e}')
    print(f'{Fore.CYAN}All requests completed. Total time: {time.time() - start_time}')

if __name__ == '__main__':
    main()