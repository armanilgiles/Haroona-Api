from fastapi import APIRouter
from app.etl.runner import run_rakuten_etl
from fastapi import APIRouter, BackgroundTasks
from app.etl.background import run_rakuten_etl_background
router = APIRouter(prefix="/etl", tags=["ETL"])

@router.post("/rakuten/test")
def run_rakuten_test_etl():
    # Mock Rakuten-like payload (safe)
    mock_products = [
        {
            "productId": "123",
            "productName": "Mock Jacket",
            "brandName": "Nike",
            "price": "89.99",
            "currency": "USD",
        },
        {
            "productId": "456",
            "productName": "Mock Sneakers",
            "brandName": "Adidas",
            "price": "129.99",
            "currency": "USD",
        },
    ]

    result = run_rakuten_etl(mock_products)

    return {
        "status": "ok",
        "records": len(result),
        "data": result,
    }

@router.post("/rakuten/run")
def trigger_rakuten_etl(background_tasks: BackgroundTasks):
    mock_products = [
        {
            "productId": "123",
            "productName": "Mock Jacket",
            "brandName": "Nike",
            "price": "89.99",
            "currency": "USD",
        },
        {
            "productId": "456",
            "productName": "Mock Sneakers",
            "brandName": "Adidas",
            "price": "129.99",
            "currency": "USD",
        },
    ]

    background_tasks.add_task(
        run_rakuten_etl_background,
        mock_products,
    )

    return {
        "status": "accepted",
        "message": "Rakuten ETL started in background",
    }
