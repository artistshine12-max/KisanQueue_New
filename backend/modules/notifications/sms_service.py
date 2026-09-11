from twilio.rest import Client
from core.config import settings

client = Client(settings.TWILIO_SID, settings.TWILIO_AUTH)

def send_sms(to_number: str, message: str):
    client.messages.create(
        body=message,
        from_=settings.TWILIO_PHONE,
        to=to_number
    )
from fastapi import APIRouter
from modules.notifications.sms_service import send_sms

sms_router = APIRouter()

@sms_router.post("/sms")
async def notify_farmer_sms(phone_number: str, message: str):
    send_sms(phone_number, message)
    return {"status": "sent", "to": phone_number}
