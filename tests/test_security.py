import pytest
from fastapi import status
from httpx import AsyncClient
from app.main import app
import app.security as sec

@pytest.mark.asyncio
async def test_auth():
    sec.API_KEY = "secret123"
    async with AsyncClient(app=app, base_url="http://test") as client:
        # no key -> 401
        r = await client.post("/udf/npv", json={"cashflows":[100,100],"rate":0.05})
        assert r.status_code == status.HTTP_401_UNAUTHORIZED
        # with key -> 200
        r = await client.post("/udf/npv",
            headers={"X-API-Key":"secret123"},
            json={"cashflows":[100,100],"rate":0.05})
        assert r.status_code == status.HTTP_200_OK
