from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, status
from fastapi.exception_handlers import http_exception_handler, request_validation_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.middleware.cors import CORSMiddleware

from starlette.exceptions import HTTPException as StarletteHTTPException

import controllers

from routers import router


@asynccontextmanager
async def lifespan(_app: FastAPI):
    app.state.controller = controllers.LegalAssistantController()
    yield
    
    
def create_app() -> FastAPI:

    app = FastAPI(
        title="ПСБ - Юридический ИИ-ассистент",
        description="RAG-система с контролем достоверности нормативных документов",
        version="1.0",
        lifespan=lifespan,
        
        docs_url="/api/docs",
        redoc_url="/api/redoc",
        openapi_url="/api/openapi.json"
    )
    
    app.mount("/static", StaticFiles(directory="static"), name="static")
    templates = Jinja2Templates(directory="templates")
    
    app.include_router(router)
    
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    
    # Обработчики ошибок
    @app.exception_handler(StarletteHTTPException)
    async def general_http_exception_handler(request: Request, exception: StarletteHTTPException):
        if request.url.path.startswith("/api"):
            return await http_exception_handler(request, exception)

        message = exception.detail or "An error occurred. Please check your request."
        return templates.TemplateResponse(
            request,
            "error.html",
            {"status_code": exception.status_code, "title": exception.status_code, "message": message},
            status_code=exception.status_code,
        )


    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(request: Request, exception: RequestValidationError):
        if request.url.path.startswith("/api"):
            return await request_validation_exception_handler(request, exception)

        return templates.TemplateResponse(
            request,
            "error.html",
            {
                "status_code": status.HTTP_422_UNPROCESSABLE_CONTENT,
                "title": status.HTTP_422_UNPROCESSABLE_CONTENT,
                "message": "Invalid request parameters.",
            },
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        )
        
    return app

app = create_app()
    
"""
zip -j submit.zip config.py models.py retriever.py llm_client.py views.py controllers.py solution.py requirements.txt

"""
