from fastapi.testclient import TestClient
import json
from app.main import app, trigger_state

client = TestClient(app)

def test_reset():
    response = client.post("/reset")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    assert not trigger_state["active"]

def test_checkin_physio_only_trigger():
    client.post("/reset")
    
    # Send physio data with HR > 120
    physio_data = {
        "hr": 130,
        "spo2": 98,
        "accel_magnitude": 1.0,
        "acc_x": [0], "acc_y": [0], "acc_z": [0], "bvp": [0], "gsr": [0]
    }
    
    response = client.post("/checkin", data={"physio_json": json.dumps(physio_data)})
    assert response.status_code == 200
    
    resp_json = response.json()
    assert resp_json["action"] == "prompt_user"
    assert resp_json["event"] == "HR_SPIKE"
    
    # Send again within 60s, should be waiting_for_user
    response = client.post("/checkin", data={"physio_json": json.dumps(physio_data)})
    assert response.json()["action"] == "waiting_for_user"

def test_checkin_physio_escalation(monkeypatch):
    client.post("/reset")
    
    physio_data = {
        "hr": 130,
        "spo2": 98,
        "accel_magnitude": 1.0,
        "acc_x": [0], "acc_y": [0], "acc_z": [0], "bvp": [0], "gsr": [0]
    }
    
    # Prompt
    client.post("/checkin", data={"physio_json": json.dumps(physio_data)})
    
    # Mock datetime to simulate > 60s passed
    import datetime
    
    class MockDatetime:
        @classmethod
        def now(cls, tz=None):
            return datetime.datetime.now(tz) + datetime.timedelta(seconds=65)
            
    import app.main
    monkeypatch.setattr(app.main, "datetime", MockDatetime)
    
    response = client.post("/checkin", data={"physio_json": json.dumps(physio_data)})
    assert response.json()["action"] == "escalated"
