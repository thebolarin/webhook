import requests
import logging

# Logging setup
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def send_http_request(endpoint, payload):
    """Helper function to send HTTP POST request for the webhook.
    Returns True on success, False on failure.
    """
    try:
        response = requests.post(endpoint, json=payload)
        
        if response.status_code == 200:
            return True
        else:
            logging.warning(f"Request to {endpoint} failed with status: {response.status_code}")
            return False
    except requests.RequestException as e:
        logging.error(f"Request to {endpoint} failed with error: {e}")
        return False
