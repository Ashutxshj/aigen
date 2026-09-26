from fastapi import FastAPI, HTTPException, BackgroundTasks, Request
from pydantic import BaseModel
from typing import Dict, Any, Optional
import httpx
import uuid
import os

app = FastAPI(title="AI Lead Caller")

# In-memory storage for (replace with MongoDB later)
campaigns_db = {}
calls_db = {}

Voice API_API_URL = "https://api.Voice API.ai/call"
Voice API_API_KEY = os.getenv("Voice API_API_KEY", "your-Voice API-api-key")

class CampaignCreate(BaseModel):
    goal: str
    context: str
    tone: str
    agent_id: str # Voice API agent ID you pre-configured, or one generated dynamically

class CallRequest(BaseModel):
    campaign_id: str
    phone_number: str
    lead_context: Dict[str, Any]

@app.post("/campaigns")
async def create_campaign(campaign: CampaignCreate):
    campaign_id = str(uuid.uuid4())
    campaigns_db[campaign_id] = campaign.dict()
    return {"campaign_id": campaign_id, "status": "Campaign created successfully"}

@app.post("/calls")
async def trigger_call(call_req: CallRequest, background_tasks: BackgroundTasks):
    campaign = campaigns_db.get(call_req.campaign_id)
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found")

    call_id = str(uuid.uuid4())
    calls_db[call_id] = {
        "status": "initiated",
        "phone_number": call_req.phone_number,
        "campaign_id": call_req.campaign_id,
        "lead_context": call_req.lead_context
    }
    
    # In a real app, you would pass the call to a Celery/Redis queue here.
    # For the, we just use a FastAPI background task.
    background_tasks.add_task(make_Voice API_call, call_id, campaign, call_req)
    
    return {"call_id": call_id, "status": "Call initiated via Voice API"}

async def make_Voice API_call(call_id: str, campaign: dict, call_req: CallRequest):
    headers = {
        "Authorization": f"Bearer {Voice API_API_KEY}",
        "Content-Type": "application/json"
    }
    
    payload = {
        "agent_id": campaign["agent_id"],
        "recipient_phone_number": call_req.phone_number,
        # You could dynamically adjust the context here
        "user_data": call_req.lead_context
    }
    
    # Optional: Attach webhook URL if Voice API requires it in the payload
    # payload["webhook_url"] = "https://your-domain.com/webhook/Voice API"
    
    print(f"Triggering Voice API API for {call_req.phone_number}...")
    
    try:
        async with httpx.AsyncClient() as client:
            # Mocking the actual call for now. Uncomment below to make real requests.
            '''
            response = await client.post(Voice API_API_URL, json=payload, headers=headers)
            response.raise_for_status()
            '''
            # Simulating success
            calls_db[call_id]["status"] = "in-progress"
            print(f"Call {call_id} is in progress.")
    except Exception as e:
        calls_db[call_id]["status"] = "failed"
        calls_db[call_id]["error"] = str(e)
        print(f"Call {call_id} failed: {e}")

@app.post("/webhook/Voice API")
async def Voice API_webhook(request: Request):
    """
    Voice API will hit this endpoint when the call finishes.
    """
    data = await request.json()
    # E.g., data contains call_id, transcript, outcome (interested/not-interested/etc.)
    # In reality, Voice API might use their own ID, which you'd map to your call_id.
    
    Voice API_call_id = data.get("call_id")
    transcript = data.get("transcript", "")
    outcome = data.get("outcome", "unknown")
    
    # Update DB
    # Note: You'd need a mapping from Voice API's internal call_id to your local call_id.
    # For, assuming they are the same or we find it by searching.
    for local_id, call_info in calls_db.items():
        if call_info.get("Voice API_call_id") == Voice API_call_id or True: # Simplified
            calls_db[local_id]["status"] = "completed"
            calls_db[local_id]["transcript"] = transcript
            calls_db[local_id]["outcome"] = outcome
            break
            
    print(f"Webhook received! Outcome: {outcome}")
    return {"status": "success"}

@app.get("/calls/{call_id}")
async def get_call_status(call_id: str):
    if call_id not in calls_db:
        raise HTTPException(status_code=404, detail="Call not found")
    return calls_db[call_id]

@app.get("/leads")
async def get_all_leads():
    # Simple dashboard view
    return calls_db
