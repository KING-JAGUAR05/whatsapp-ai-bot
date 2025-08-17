# app.py - WhatsApp AI Agent
import os
import re
import json
import requests
import gspread
from flask import Flask, request, jsonify
from datetime import datetime
from oauth2client.service_account import ServiceAccountCredentials
import logging

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)

# Configuration
WHATSAPP_TOKEN = os.getenv('WHATSAPP_TOKEN')
VERIFY_TOKEN = os.getenv('VERIFY_TOKEN', 'whatsapp_verify_123')
HUGGINGFACE_TOKEN = os.getenv('HUGGINGFACE_TOKEN')
BUSINESS_NAME = os.getenv('BUSINESS_NAME', 'Your Business')
SUPPORT_EMAIL = os.getenv('SUPPORT_EMAIL', 'support@yourbusiness.com')

class GoogleSheetsManager:
    def __init__(self):
        self.sheet = None
        self.setup_google_sheets()
    
    def setup_google_sheets(self):
        try:
            scope = [
                'https://spreadsheets.google.com/feeds',
                'https://www.googleapis.com/auth/drive'
            ]
            
            creds_dict = {
                "type": "service_account",
                "project_id": os.getenv('GOOGLE_PROJECT_ID'),
                "private_key_id": os.getenv('GOOGLE_PRIVATE_KEY_ID'),
                "private_key": os.getenv('GOOGLE_PRIVATE_KEY', '').replace('\\n', '\n'),
                "client_email": os.getenv('GOOGLE_CLIENT_EMAIL'),
                "client_id": os.getenv('GOOGLE_CLIENT_ID'),
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
            }
            
            creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
            client = gspread.authorize(creds)
            
            sheet_id = os.getenv('GOOGLE_SHEET_ID')
            if sheet_id:
                self.sheet = client.open_by_key(sheet_id).sheet1
                self.ensure_headers()
                logger.info("Google Sheets connected successfully")
                
        except Exception as e:
            logger.error(f"Google Sheets setup error: {e}")
            self.sheet = None
    
    def ensure_headers(self):
        try:
            if self.sheet:
                headers = ['Name', 'Phone Number', 'Email', 'Latest Question', 
                          'Last Contact Date', 'Last Contact Time', 'Total Interactions']
                
                existing_headers = self.sheet.row_values(1)
                if not existing_headers:
                    self.sheet.insert_row(headers, 1)
                    logger.info("Headers added to Google Sheet")
        except Exception as e:
            logger.error(f"Error ensuring headers: {e}")
    
    def store_customer_data(self, name, phone, email, question):
        try:
            if not self.sheet:
                return False
            
            current_date = datetime.now().strftime('%Y-%m-%d')
            current_time = datetime.now().strftime('%H:%M:%S')
            
            # Find existing customer
            try:
                phone_cells = self.sheet.findall(phone)
                if phone_cells:
                    row_num = phone_cells[0].row
                    current_interactions = self.sheet.cell(row_num, 7).value or '0'
                    new_interactions = str(int(current_interactions) + 1)
                    
                    self.sheet.update(f'A{row_num}:G{row_num}', [[
                        name, phone, email, question, current_date, 
                        current_time, new_interactions
                    ]])
                else:
                    self.sheet.append_row([
                        name, phone, email, question, current_date, 
                        current_time, '1'
                    ])
                
                return True
            except:
                self.sheet.append_row([
                    name, phone, email, question, current_date, 
                    current_time, '1'
                ])
                return True
                
        except Exception as e:
            logger.error(f"Error storing customer data: {e}")
            return False

class AIResponseGenerator:
    def __init__(self):
        self.huggingface_url = "https://api-inference.huggingface.co/models/microsoft/DialoGPT-large"
        self.headers = {"Authorization": f"Bearer {HUGGINGFACE_TOKEN}"}
    
    def get_ai_response(self, message, customer_name):
        try:
            # Check for common queries
            predefined_response = self.get_predefined_response(message.lower())
            if predefined_response:
                return predefined_response.format(name=customer_name, business=BUSINESS_NAME)
            
            # Generate AI response
            prompt = f"Customer {customer_name} says: {message}. Reply as helpful customer support:"

            payload = {
                "inputs": prompt,
                "parameters": {
                    "max_length": 150,
                    "temperature": 0.7
                },
                "options": {"wait_for_model": True}
            }
            
            response = requests.post(self.huggingface_url, headers=self.headers, json=payload)
            
            if response.status_code == 200:
                result = response.json()
                if isinstance(result, list) and len(result) > 0:
                    generated_text = result[0].get('generated_text', '')
                    ai_response = generated_text.replace(prompt, '').strip()
                    
                    if ai_response and len(ai_response) > 10:
                        return ai_response[:400]
                    
            return f"Hello {customer_name}! Thank you for contacting {BUSINESS_NAME}. How can I help you today?"
            
        except Exception as e:
            logger.error(f"AI response error: {e}")
            return f"Hi {customer_name}! Thanks for your message. Our team will get back to you soon!"
    
    def get_predefined_response(self, message):
        responses = {
            'hello': "Hello {name}! Welcome to {business}. How can I help you today?",
            'hi': "Hi {name}! Thanks for contacting {business}. What can I assist you with?",
            'help': "I'm here to help! Please tell me what you need assistance with.",
            'hours': "Our business hours are 9 AM to 6 PM, Monday to Friday.",
            'price': "For pricing information, please let me know which product you're interested in.",
            'order': "I'd be happy to help with your order. Could you provide your order number?",
            'support': f"You're talking to our support! For complex issues, email {SUPPORT_EMAIL}.",
        }
        
        for keyword, response in responses.items():
            if keyword in message:
                return response
        return None

# Initialize managers
sheets_manager = GoogleSheetsManager()
ai_generator = AIResponseGenerator()

def extract_email(text):
    email_pattern = r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b'
    match = re.search(email_pattern, text)
    return match.group(0) if match else 'Not provided'

def send_whatsapp_message(phone_number_id, to_number, message):
    try:
        url = f"https://graph.facebook.com/v18.0/{phone_number_id}/messages"
        headers = {
            "Authorization": f"Bearer {WHATSAPP_TOKEN}",
            "Content-Type": "application/json"
        }
        
        payload = {
            "messaging_product": "whatsapp",
            "to": to_number,
            "type": "text",
            "text": {"body": message}
        }
        
        response = requests.post(url, headers=headers, json=payload)
        return response.status_code == 200
        
    except Exception as e:
        logger.error(f"Error sending WhatsApp message: {e}")
        return False

@app.route('/webhook', methods=['GET'])
def verify_webhook():
    try:
        mode = request.args.get('hub.mode')
        token = request.args.get('hub.verify_token')
        challenge = request.args.get('hub.challenge')
        
        if mode == 'subscribe' and token == VERIFY_TOKEN:
            logger.info("Webhook verified successfully")
            return challenge, 200
        else:
            return 'Forbidden', 403
            
    except Exception as e:
        logger.error(f"Webhook verification error: {e}")
        return 'Bad Request', 400

@app.route('/webhook', methods=['POST'])
def handle_message():
    try:
        data = request.get_json()
        
        if (data.get('object') == 'whatsapp_business_account' and 
            data.get('entry') and 
            data['entry'][0].get('changes') and
            data['entry'][0]['changes'][0].get('value', {}).get('messages')):
            
            entry = data['entry'][0]
            changes = entry['changes'][0]
            value = changes['value']
            
            message_data = value['messages'][0]
            contacts = value.get('contacts', [])
            phone_number_id = value['metadata']['phone_number_id']
            
            # Extract information
            from_number = message_data.get('from')
            message_text = message_data.get('text', {}).get('body', '')
            
            customer_name = 'Customer'
            if contacts:
                profile = contacts[0].get('profile', {})
                customer_name = profile.get('name', from_number)
            
            # Only process text messages
            if message_data.get('type') != 'text':
                return jsonify({'status': 'ignored'}), 200
            
            logger.info(f"Message from {customer_name}: {message_text}")
            
            # Extract email and store data
            email = extract_email(message_text)
            sheets_manager.store_customer_data(customer_name, from_number, email, message_text)
            
            # Generate and send AI response
            ai_response = ai_generator.get_ai_response(message_text, customer_name)
            send_whatsapp_message(phone_number_id, from_number, ai_response)
            
            return jsonify({'status': 'success'}), 200
            
    except Exception as e:
        logger.error(f"Error handling message: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.route('/health')
def health_check():
    status = {
        'status': 'healthy',
        'timestamp': datetime.now().isoformat(),
        'services': {
            'whatsapp_token': bool(WHATSAPP_TOKEN),
            'huggingface_token': bool(HUGGINGFACE_TOKEN),
            'google_sheets': sheets_manager.sheet is not None
        }
    }
    return jsonify(status), 200

@app.route('/')
def index():
    info = {
        'service': f'{BUSINESS_NAME} WhatsApp AI Agent',
        'status': 'active',
        'endpoints': {
            'webhook': '/webhook',
            'health': '/health'
        }
    }
    return jsonify(info), 200

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)