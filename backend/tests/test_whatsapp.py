import time
import pytest
from httpx import AsyncClient

# These tests require a live PostgreSQL connection.
pytestmark = [pytest.mark.db]

@pytest.mark.asyncio
async def test_whatsapp_simulator_onboarding(async_client: AsyncClient):
    unique_phone = f"9999{int(time.time() * 1000) % 1000000:06d}"
    # 1. Start onboarding
    response = await async_client.post("/v1/whatsapp/simulate", json={"phone": unique_phone, "text": "Hi"})
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert "कृपया अपना नाम बताएं" in data["reply"]

    # 2. Provide name
    response = await async_client.post("/v1/whatsapp/simulate", json={"phone": unique_phone, "text": "Ramesh Kumar"})
    assert response.status_code == 200
    data = response.json()
    assert "आपका गाँव और जिला क्या है" in data["reply"]

    # 3. Provide location
    response = await async_client.post("/v1/whatsapp/simulate", json={"phone": unique_phone, "text": "Biaora, Rajgarh"})
    assert response.status_code == 200
    data = response.json()
    assert "सफलतापूर्वक सेट" in data["reply"]

    # 4. Status query (already onboarded)
    response = await async_client.post("/v1/whatsapp/simulate", json={"phone": unique_phone, "text": "स्थिति दिखाओ"})
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"


@pytest.mark.asyncio
async def test_whatsapp_existing_farmer_hindi(async_client: AsyncClient):
    """
    Test WhatsApp interaction for an existing seeded farmer with preferred_language='hi'.
    Verifies that farmer.user.preferred_language is used and no AttributeError occurs.
    """
    phone = "+919876543210"  # Seeded farmer: Ramesh Kumar (hi)

    # 1. Status query
    resp = await async_client.post("/v1/whatsapp/simulate", json={"phone": phone, "text": "कतार स्थिति क्या है?"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert "लाइव रिपोर्ट" in data["reply"] or "कतार" in data["reply"] or "सक्रिय पास" in data["reply"]

    # 2. Pass query
    resp = await async_client.post("/v1/whatsapp/simulate", json={"phone": phone, "text": "मेरा पास दिखाओ"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert "पास" in data["reply"] or "टोकन" in data["reply"]

    # 3. MSP rates query
    resp = await async_client.post("/v1/whatsapp/simulate", json={"phone": phone, "text": "गेहूं का भाव क्या है?"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert "एमएसपी दरें" in data["reply"]
    assert "₹2,275" in data["reply"]

    # 4. Help menu
    resp = await async_client.post("/v1/whatsapp/simulate", json={"phone": phone, "text": "help"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert "मंडी गेट चेक-इन सहायता" in data["reply"]


@pytest.mark.asyncio
async def test_whatsapp_existing_farmer_english(async_client: AsyncClient):
    """
    Test WhatsApp interaction for an existing farmer with preferred_language='en'.
    Creates a farmer via OTP + profile update with language='en', then sends WhatsApp queries.
    """
    en_phone = f"+9198{int(time.time() * 1000) % 100000000:08d}"

    # Register farmer
    r = await async_client.post("/v1/auth/otp/request", json={"phone": en_phone})
    assert r.status_code == 200
    r = await async_client.post("/v1/auth/otp/verify", json={"phone": en_phone, "otp": "1234"})
    assert r.status_code == 200
    token = r.json()["access_token"]

    # Set profile to English
    headers = {"Authorization": f"Bearer {token}"}
    r = await async_client.post(
        "/v1/farmer/profile",
        headers=headers,
        json={
            "phone": en_phone,
            "name": "John Farmer",
            "language": "en",
            "village": "Model Town",
            "district": "Hisar",
            "state": "Haryana",
            "primary_crop": "Wheat",
            "aadhaar_last4": "1234",
        },
    )
    assert r.status_code == 201

    # WhatsApp status query
    resp = await async_client.post("/v1/whatsapp/simulate", json={"phone": en_phone, "text": "status"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    # Should reply in English
    assert "You have no active queue pass" in data["reply"] or "Live Status" in data["reply"]

    # WhatsApp MSP query
    resp = await async_client.post("/v1/whatsapp/simulate", json={"phone": en_phone, "text": "msp rates"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert "Government MSP Rates" in data["reply"]
    assert "Wheat: **₹2,275 / Quintal**" in data["reply"]

    # WhatsApp Default Help query
    resp = await async_client.post("/v1/whatsapp/simulate", json={"phone": en_phone, "text": "hello"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert "Mandi Gate Check-in Assistance" in data["reply"]
