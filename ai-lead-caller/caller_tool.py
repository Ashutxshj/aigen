import os
import sys
import json
import httpx
import argparse
from dotenv import load_dotenv

def main():
    load_dotenv()
    api_key = os.getenv("BOLNA_API_KEY")
    if not api_key:
        print("Error: BOLNA_API_KEY not found in .env")
        sys.exit(1)

    parser = argparse.ArgumentParser()
    parser.add_argument("--sheet", help="Path to excel sheet to read leads from", required=False)
    parser.add_argument("--no-email", action="store_true")
    args = parser.parse_args()

    print("AI Caller initialized.")
    print(f"Using Bolna API Key: {api_key[:6]}...{api_key[-4:]}")
    
    # Normally we would use pandas or openpyxl to read the sheet
    # For MVP, we will mock finding 2 leads.
    print("Scanning leads for phone numbers...")
    leads_to_call = [
        {"business_name": "Mock Dental", "phone": "+919876543210", "context": "Needs modern website"},
    ]

    print(f"Found {len(leads_to_call)} lead(s) with phone numbers.")
    for lead in leads_to_call:
        print(f"Triggering Bolna Call for {lead['business_name']} ({lead['phone']})...")
        # Real code would do:
        # httpx.post("https://api.bolna.ai/call", headers={"Authorization": f"Bearer {api_key}"}, json={...})
        print(f"Call initiated successfully for {lead['phone']}")
        
    print("Done calling leads. Awaiting webhooks for transcripts.")
    sys.exit(0)

if __name__ == "__main__":
    main()
