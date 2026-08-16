import os

import uvicorn


if __name__ == "__main__":
    host = os.getenv("HOST", "127.0.0.1")
    port = int(os.getenv("PORT", "8010"))
    uvicorn.run("backend.app.main:app", host=host, port=port, reload=os.getenv("RELOAD") == "1")
