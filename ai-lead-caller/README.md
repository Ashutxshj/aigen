# AI Lead Caller

This is a prototype for integrating a lead generation pipeline with an AI voice caller using [Voice API.ai](https://Voice API.ai/).

## Overview
This tool is meant to sit next to your existing ChiliSpark / Niche scraping engine. 
1. Your scraping engine finds a lead and extracts context (e.g., website speed is slow, no CTA).
2. It sends this to the `/calls` endpoint.
3. This app triggers an outbound call via Voice API using a pre-configured AI Agent.
4. Voice API conducts the call and sends the transcript/outcome back to the `/webhook/Voice API` endpoint.

## Setup
1. Create a virtual environment: `python -m venv venv`
2. Activate it: `venv\Scripts\activate` (Windows)
3. Install dependencies: `pip install -r requirements.txt`
4. Set your Voice API API key: `set Voice API_API_KEY=your_key_here`

## Running
Run the FastAPI development server:
```bash
uvicorn main:app --reload
```

## API Usage

### 1. Create a Campaign
```bash
curl -X POST http://localhost:8000/campaigns \
     -H "Content-Type: application/json" \
     -d '{"goal": "Book a website demo", "context": "We are AIGen, a web development agency.", "tone": "friendly", "agent_id": "YOUR_Voice API_AGENT_ID"}'
```

### 2. Trigger a Call
```bash
curl -X POST http://localhost:8000/calls \
     -H "Content-Type: application/json" \
     -d '{"campaign_id": "<CAMPAIGN_ID>", "phone_number": "+91XXXXXXXXXX", "lead_context": {"business_name": "Smile Dental", "issues": ["slow website"]}}'
```

### 3. Check Status
```bash
curl http://localhost:8000/calls/<CALL_ID>
```
