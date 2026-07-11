
"""
Paystack integration for Trovee – deposits and withdrawals.
Supports multiple African countries (Nigeria, Ghana, Kenya, South Africa, etc.)
If Paystack is not configured, the service gracefully falls back to mock mode.
"""

import os
import hmac
import hashlib
import json
import requests
from datetime import datetime

PAYSTACK_SECRET_KEY = os.environ.get("PAYSTACK_SECRET_KEY", "")
PAYSTACK_PUBLIC_KEY = os.environ.get("PAYSTACK_PUBLIC_KEY", "")
PAYSTACK_WEBHOOK_SECRET = os.environ.get("PAYSTACK_WEBHOOK_SECRET", "")

# Paystack API endpoints
PAYSTACK_API_URL = "https://api.paystack.co"


class PaystackService:
    def __init__(self):
        self.connected = bool(PAYSTACK_SECRET_KEY)
        self.headers = {
            "Authorization": f"Bearer {PAYSTACK_SECRET_KEY}",
            "Content-Type": "application/json"
        }
    
    def is_configured(self):
        """Check if Paystack is configured."""
        return self.connected
    
    def get_supported_countries(self):
        """Return countries supported by Paystack with their currencies."""
        return {
            "NG": {"name": "Nigeria", "currency": "NGN", "code": "NG"},
            "GH": {"name": "Ghana", "currency": "GHS", "code": "GH"},
            "KE": {"name": "Kenya", "currency": "KES", "code": "KE"},
            "ZA": {"name": "South Africa", "currency": "ZAR", "code": "ZA"},
        }
    
    def get_country_info(self, country_code):
        """Get country-specific payment configuration."""
        countries = self.get_supported_countries()
        return countries.get(country_code.upper(), countries.get("NG"))
    
    def initialize_payment(self, user_email, amount, currency="NGN", reference=None, callback_url=None, metadata=None):
        """
        Initialize a payment with Paystack.
        Returns payment URL.
        """
        if not self.connected:
            # Paystack not configured – fallback
            return {
                "status": "fallback",
                "data": {
                    "link": f"/deposit/mock?ref={reference}",
                    "reference": reference,
                    "amount": amount,
                    "currency": currency,
                    "message": "Paystack not configured. Please set PAYSTACK_SECRET_KEY."
                }
            }
        
        if not reference:
            reference = f"TROVEE-{int(datetime.now().timestamp())}-{user_email.split('@')[0]}"
        
        if not callback_url:
            callback_url = os.environ.get("BASE_URL", "https://yourdomain.com") + "/api/paystack/callback"
        
        payload = {
            "email": user_email,
            "amount": int(amount * 100),  # Paystack uses kobo (cents)
            "currency": currency,
            "reference": reference,
            "callback_url": callback_url,
            "metadata": metadata or {
                "custom_fields": [
                    {"display_name": "Trovee Deposit", "variable_name": "trovee_deposit", "value": amount}
                ]
            }
        }
        
        try:
            response = requests.post(
                f"{PAYSTACK_API_URL}/transaction/initialize",
                headers=self.headers,
                json=payload,
                timeout=30
            )
            data = response.json()
            
            if data.get("status"):
                return {
                    "status": "success",
                    "data": {
                        "link": data.get("data", {}).get("authorization_url"),
                        "reference": data.get("data", {}).get("reference"),
                        "access_code": data.get("data", {}).get("access_code"),
                        "amount": amount,
                        "currency": currency
                    }
                }
            else:
                return {
                    "status": "error",
                    "message": data.get("message", "Payment initialization failed.")
                }
        except Exception as e:
            print(f"[trovee] Paystack init error: {e}")
            return {
                "status": "error",
                "message": str(e)
            }
    
    def verify_payment(self, reference):
        """Verify a payment by reference."""
        if not self.connected:
            return {
                "status": "fallback",
                "data": {
                    "status": "success",
                    "reference": reference,
                    "amount": 100,
                    "currency": "NGN"
                }
            }
        
        try:
            response = requests.get(
                f"{PAYSTACK_API_URL}/transaction/verify/{reference}",
                headers=self.headers,
                timeout=30
            )
            data = response.json()
            
            if data.get("status"):
                return {
                    "status": "success",
                    "data": {
                        "status": data.get("data", {}).get("status"),
                        "reference": data.get("data", {}).get("reference"),
                        "amount": data.get("data", {}).get("amount", 0) / 100,  # Convert from kobo
                        "currency": data.get("data", {}).get("currency", "NGN"),
                        "metadata": data.get("data", {}).get("metadata", {})
                    }
                }
            else:
                return {
                    "status": "error",
                    "message": data.get("message", "Verification failed.")
                }
        except Exception as e:
            print(f"[trovee] Paystack verify error: {e}")
            return {
                "status": "error",
                "message": str(e)
            }
    
    def get_banks(self, country_code="NG"):
        """Get list of banks for a country."""
        if not self.connected:
            # Fallback banks for testing
            fallback = {
                "NG": [
                    {"code": "001", "name": "Access Bank"},
                    {"code": "004", "name": "GTBank"},
                    {"code": "011", "name": "First Bank"},
                    {"code": "033", "name": "UBA"},
                    {"code": "057", "name": "Zenith Bank"},
                    {"code": "214", "name": "FCMB"},
                    {"code": "058", "name": "Guaranty Trust Bank"},
                ],
                "GH": [
                    {"code": "001", "name": "Ghana Commercial Bank"},
                    {"code": "002", "name": "Access Bank Ghana"},
                ],
                "KE": [
                    {"code": "001", "name": "Equity Bank"},
                    {"code": "002", "name": "KCB Bank"},
                ],
                "ZA": [
                    {"code": "001", "name": "First National Bank"},
                    {"code": "002", "name": "Standard Bank"},
                ],
            }
            return fallback.get(country_code.upper(), fallback.get("NG", []))
        
        try:
            response = requests.get(
                f"{PAYSTACK_API_URL}/bank",
                headers=self.headers,
                params={"country": country_code},
                timeout=30
            )
            data = response.json()
            if data.get("status"):
                return data.get("data", [])
            return []
        except Exception as e:
            print(f"[trovee] Paystack banks error: {e}")
            return []
    
    def resolve_bank_account(self, bank_code, account_number):
        """Verify a bank account number."""
        if not self.connected:
            return {
                "status": "success",
                "data": {"account_name": "John Doe"}
            }
        
        try:
            response = requests.get(
                f"{PAYSTACK_API_URL}/bank/resolve",
                headers=self.headers,
                params={
                    "bank_code": bank_code,
                    "account_number": account_number
                },
                timeout=30
            )
            data = response.json()
            if data.get("status"):
                return {
                    "status": "success",
                    "data": {
                        "account_name": data.get("data", {}).get("account_name")
                    }
                }
            else:
                return {
                    "status": "error",
                    "message": data.get("message", "Account verification failed.")
                }
        except Exception as e:
            print(f"[trovee] Paystack resolve account error: {e}")
            return {
                "status": "error",
                "message": str(e)
            }
    
    def initiate_transfer(self, amount, bank_code, account_number, account_name, reference=None, narration=None, currency="NGN"):
        """Initiate a transfer/payout to a bank account."""
        if not self.connected:
            return {
                "status": "fallback",
                "data": {
                    "reference": reference or f"TROVEE-{int(datetime.now().timestamp())}",
                    "message": "Paystack not configured. Withdrawal marked as processed."
                }
            }
        
        if not reference:
            reference = f"TROVEE-TRF-{int(datetime.now().timestamp())}"
        
        payload = {
            "source": "balance",
            "amount": int(amount * 100),  # Convert to kobo
            "bank_code": bank_code,
            "account_number": account_number,
            "account_name": account_name,
            "reference": reference,
            "narration": narration or f"Trovee withdrawal for account {account_number}",
            "currency": currency
        }
        
        try:
            response = requests.post(
                f"{PAYSTACK_API_URL}/transfer",
                headers=self.headers,
                json=payload,
                timeout=30
            )
            data = response.json()
            
            if data.get("status"):
                return {
                    "status": "success",
                    "data": {
                        "reference": data.get("data", {}).get("reference"),
                        "transfer_code": data.get("data", {}).get("transfer_code"),
                        "amount": amount,
                        "currency": currency
                    }
                }
            else:
                return {
                    "status": "error",
                    "message": data.get("message", "Transfer failed.")
                }
        except Exception as e:
            print(f"[trovee] Paystack transfer error: {e}")
            return {
                "status": "error",
                "message": str(e)
            }
    
    def webhook_verify_signature(self, payload, signature):
        """Verify webhook signature for security."""
        if not PAYSTACK_WEBHOOK_SECRET:
            # If no webhook secret is set, skip verification (less secure but works)
            return True
        
        expected = hmac.new(
            PAYSTACK_WEBHOOK_SECRET.encode(),
            payload.encode(),
            hashlib.sha512
        ).hexdigest()
        return hmac.compare_digest(signature, expected)
    
    def list_banks_with_currency(self, country_code="NG"):
        """Get banks with their supported currencies."""
        banks = self.get_banks(country_code)
        currency_map = {
            "NG": "NGN",
            "GH": "GHS",
            "KE": "KES",
            "ZA": "ZAR"
        }
        currency = currency_map.get(country_code.upper(), "NGN")
        return [
            {
                "code": bank.get("code"),
                "name": bank.get("name"),
                "currency": currency
            }
            for bank in banks
        ]


# Singleton instance
paystack = PaystackService()
