import httpx


async def test_financial_report_api(client: httpx.AsyncClient):
    response = await client.post(
        "/api/v1/accounting/financial-report",
        json={
            "start": "2026-07-01",
            "end": "2026-07-31",
            "planned_cash_in": "150000.01",
            "planned_cash_out": "290000.02",
        },
    )
    assert response.status_code == 200, response.text
    report = response.json()
    assert report["current"]["net"] == "-148500.00"
    assert report["profit_and_loss"]["current"]["operating_profit"] == "55000.00"
    assert len(report["payables"]) == 102
    assert report["plan_fact"]["incoming_variance"] == "1499.99"
    assert (
        await client.post(
            "/api/v1/accounting/financial-report",
            json={
                "start": "2026-07-31",
                "end": "2026-07-01",
            },
        )
    ).status_code == 422
