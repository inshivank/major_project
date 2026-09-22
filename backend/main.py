from fastapi import FastAPI

app = FastAPI(title="CoreCare", version="0.1.0")


@app.get("/")
async def health_check():
    return {"message": "CoreCare API is running"}
