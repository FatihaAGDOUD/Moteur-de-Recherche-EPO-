# token_manager.py

import requests
import time
import json
import os
from datetime import datetime, timedelta
import base64
import xml.etree.ElementTree as ET
from dotenv import load_dotenv

class EPOAuthManager:
    _instance = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(EPOAuthManager, cls).__new__(cls)
            cls._instance.initialized = False
        return cls._instance
    
    def __init__(self):
        if self.initialized:
            return
            
        load_dotenv()
        
        self.consumer_key = os.getenv('EPO_CONSUMER_KEY')
        self.consumer_secret = os.getenv('EPO_CONSUMER_SECRET')
        self.token_file = "epo_token.json"
        
        if not self.consumer_key or not self.consumer_secret:
            raise ValueError(
                "Missing EPO credentials. Please:\n"
                "1. Register at https://developers.epo.org/\n"
                "2. Create an application to get credentials\n"
                "3. Create a .env file with:\n"
                "   EPO_CONSUMER_KEY=your_key\n"
                "   EPO_CONSUMER_SECRET=your_secret"
            )
        
        self.token = None
        self.token_expiry = None
        self.auth_url = "https://ops.epo.org/3.2/auth/accesstoken"
        self.initialized = True
        self.load_token()

    def load_token(self):
        """Load token from file if valid."""
        if os.path.exists(self.token_file):
            try:
                with open(self.token_file, 'r') as f:
                    data = json.load(f)
                    if datetime.fromisoformat(data['expiry']) > datetime.now():
                        self.token = data['token']
                        self.token_expiry = datetime.fromisoformat(data['expiry'])
            except (json.JSONDecodeError, KeyError, ValueError):
                pass

    def save_token(self):
        """Save token and expiry to file."""
        with open(self.token_file, 'w') as f:
            json.dump({
                'token': self.token,
                'expiry': self.token_expiry.isoformat()
            }, f)

    def _get_basic_auth(self):
        """Get base64 encoded credentials."""
        auth_string = f"{self.consumer_key}:{self.consumer_secret}"
        return base64.b64encode(auth_string.encode()).decode()

    def _refresh_token(self):
        """Get new access token from EPO API."""
        headers = {
            'Authorization': f'Basic {self._get_basic_auth()}',
            'Content-Type': 'application/x-www-form-urlencoded',
        }
        
        data = 'grant_type=client_credentials'
        
        try:
            response = requests.post(
                self.auth_url,
                headers=headers,
                data=data
            )
            
            if 'xml' in response.headers.get('Content-Type', '').lower():
                root = ET.fromstring(response.text)
                error_message = root.find('message').text if root.find('message') is not None else 'Unknown error'
                raise Exception(f"EPO API Error: {error_message}")
            
            if response.status_code != 200:
                raise Exception(f"Failed to obtain token: {response.text}")
            
            data = response.json()
            
            if 'access_token' not in data or 'expires_in' not in data:
                raise Exception(f"Unexpected response format: {data}")
            
            expires_in = int(data['expires_in']) if isinstance(data['expires_in'], str) else data['expires_in']
            
            self.token = data['access_token']
            self.token_expiry = datetime.now() + timedelta(seconds=expires_in)
            self.save_token()
            
        except requests.exceptions.RequestException as e:
            raise Exception(f"Network error while obtaining token: {str(e)}")

    def get_valid_token(self):
        """Get a valid token, refreshing if necessary."""
        if not self.token or datetime.now() >= self.token_expiry - timedelta(minutes=5):
            self._refresh_token()
        return self.token

# Singleton instance
def get_token_manager():
    return EPOAuthManager()