import uvicorn

if __name__ == "__main__":
    # This enables running the app directly with "python run.py"
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)
