import sys
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, Request, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import OAuth2PasswordBearer, OAuth2
from fastapi.openapi.docs import get_swagger_ui_html
from fastapi.openapi.models import OAuthFlows as OAuthFlowsModel
from fastapi.security.utils import get_authorization_scheme_param
from fastapi.openapi.utils import get_openapi
from dotenv import load_dotenv

# Add the parent directory to the Python path
sys.path.append(str(Path(__file__).parent))

from app.core.config import settings
from app.api import api_router
from app.db.mongodb import MongoDB, on_startup as mongodb_startup
from app.services.cloudinary_service import configure_cloudinary
from app.exceptions.plan_limits import PlanLimitError
from fastapi.responses import JSONResponse

# Load environment variables
load_dotenv()

# Initialize FastAPI app with enhanced OpenAPI documentation
app = FastAPI(
    title=settings.PROJECT_NAME,
    openapi_url=f"{settings.API_V1_STR}/openapi.json",
    docs_url=None,  # Disable default docs
    redoc_url=None,  # Disable default redoc
)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # In production, replace with your frontend URL
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include the API router
app.include_router(api_router, prefix=settings.API_V1_STR)
configure_cloudinary()


@app.exception_handler(PlanLimitError)
async def plan_limit_exception_handler(request: Request, exc: PlanLimitError):
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "success": False,
            "errorCode": exc.error_code,
            "message": exc.message,
        },
    )


@app.on_event("startup")
async def app_startup():
    await mongodb_startup()


@app.on_event("shutdown")
async def app_shutdown():
    await MongoDB.close_connection()

# OAuth2 scheme for token authentication
oauth2_scheme = OAuth2PasswordBearer(tokenUrl=f"{settings.API_V1_STR}/auth/token")

class OAuth2PasswordBearerWithCookie(OAuth2):
    def __init__(
        self,
        tokenUrl: str,
        scheme_name: Optional[str] = None,
        scopes: Optional[dict] = None,
        auto_error: bool = True,
    ):
        if not scopes:
            scopes = {}
        flows = OAuthFlowsModel(password={"tokenUrl": tokenUrl, "scopes": scopes})
        super().__init__(flows=flows, scheme_name=scheme_name, auto_error=auto_error)

    async def __call__(self, request: Request) -> Optional[str]:
        authorization: str = request.headers.get("Authorization")
        scheme, param = get_authorization_scheme_param(authorization)
        if not authorization or scheme.lower() != "bearer":
            if self.auto_error:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Not authenticated",
                    headers={"WWW-Authenticate": "Bearer"},
                )
            else:
                return None
        return param

# Custom docs route with OAuth2
@app.get("/docs", include_in_schema=False)
async def get_swagger_documentation():
    return get_swagger_ui_html(
        openapi_url=f"{settings.API_V1_STR}/openapi.json",
        title="BookMyShoot API - Swagger UI",
        oauth2_redirect_url=app.swagger_ui_oauth2_redirect_url,
        swagger_js_url="https://cdn.jsdelivr.net/npm/swagger-ui-dist@3/swagger-ui-bundle.js",
        swagger_css_url="https://cdn.jsdelivr.net/npm/swagger-ui-dist@3/swagger-ui.css",
        swagger_ui_parameters={
            "defaultModelsExpandDepth": -1,
            "persistAuthorization": True,
        }
    )

# Root endpoint
@app.get("/", include_in_schema=False)
async def root():
    return {"message": "Welcome to BookMyShoot API"}

def custom_openapi():
    if app.openapi_schema:
        return app.openapi_schema
    
    openapi_schema = get_openapi(
        title=settings.PROJECT_NAME,
        version="1.0.0",
        description="BookMyShoot API Documentation",
        routes=app.routes,
    )
    
    # Add security definitions
    openapi_schema["components"]["securitySchemes"] = {
        "OAuth2PasswordBearer": {
            "type": "http",
            "scheme": "bearer",
            "bearerFormat": "JWT"
        }
    }
    
    # Add security to all endpoints except auth (login, signup)
    for path_key, path in openapi_schema["paths"].items():
        for method_key, method in path.items():
            if not isinstance(method, dict):
                continue
            op_id = method.get("operationId") or ""
            summary = (method.get("summary") or "").lower()
            if (
                "login" in op_id
                or "login" in summary
                or "signup" in op_id
                or "signup" in summary
                or "upload" in op_id
                or "upload" in summary
                or "webhook" in path_key.lower()
            ):
                continue
            method["security"] = [{"OAuth2PasswordBearer": []}]
    
    app.openapi_schema = openapi_schema
    return app.openapi_schema

app.openapi = custom_openapi

if __name__ == "__main__":
    import uvicorn
    import logging
    
    # Configure logging
    logging.basicConfig(level=logging.INFO)
    logger = logging.getLogger("uvicorn")
    
    # Start the server
    logger.info("Starting BookMyShoot API server on port 3001...")
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=3001,
        reload=True,
        log_level="info"
    )
