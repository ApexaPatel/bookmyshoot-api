# BookMyShoot - Backend API

A FastAPI-based backend service for the BookMyShoot platform, connecting photographers with clients for booking photoshoots.

## Features

- **User Authentication**: JWT-based authentication with role-based access control
- **User Management**: Registration and profile management for customers and photographers
- **Database**: MongoDB for flexible data storage
- **Async Support**: Built with async/await for better performance
- **RESTful API**: Clean, well-documented API endpoints
- **Environment Configuration**: Easy configuration through environment variables

## Tech Stack

- **Framework**: FastAPI
- **Database**: MongoDB (with Motor for async support)
- **Authentication**: JWT (JSON Web Tokens)
- **Password Hashing**: bcrypt
- **Environment Management**: python-dotenv
- **Testing**: pytest with pytest-asyncio

## Prerequisites

- Python 3.8+
- MongoDB (local or MongoDB Atlas)
- pip (Python package manager)

## Getting Started

### 1. Clone the Repository

```bash
git clone https://github.com/ApexaPatel/bookmyshoot-api.git
cd bookmyshoot-api/backend
```

### 2. Set Up Virtual Environment

```bash
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

### 3. Install Dependencies

```bash
pip install -r requirements.txt
```

### 4. Configure Environment Variables

Copy the example environment file and update the values:

```bash
cp .env.example .env
```

Edit the `.env` file with your configuration:

```
# MongoDB Configuration
MONGODB_URL=your_mongodb_connection_string
MONGODB_NAME=bookmyshoot

# JWT Configuration
SECRET_KEY=your-secret-key-here
ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=1440  # 24 hours

# App Configuration
DEBUG=True
ENVIRONMENT=development
```

### 5. Run the Application

```bash
uvicorn main:app --reload
```

The API will be available at `http://localhost:8000`

## API Documentation

Once the server is running, you can access the interactive API documentation:

- **Swagger UI**: `http://localhost:3001/docs` (or your configured port)
- **OpenAPI JSON**: `http://localhost:3001/api/openapi.json`

### Auth & profile image

| Method | Endpoint | Auth | Description |
|--------|----------|------|-------------|
| POST | `/api/auth/signup` | No | Register; optional `profile_picture` URL (e.g. from Firebase Storage) |
| POST | `/api/auth/login` | No | Login (form-urlencoded `username`, `password`) |
| GET | `/api/auth/me` | Bearer | Current user (session restore) |
| PUT | `/api/auth/profile-image` | Bearer | Update profile image URL only. Body: `{ "profile_picture": "https://..." }` |

Profile images are stored by URL only (e.g. Firebase Storage download URL); the API does not store file blobs.

## Project Structure

```
backend/
├── app/
│   ├── __init__.py
│   ├── core/
│   │   └── security.py       # Authentication and security utilities
│   ├── crud/
│   │   └── user.py           # Database operations for users
│   ├── db/
│   │   └── mongodb.py        # Database connection and utilities
│   └── models/
│       └── user.py           # Pydantic models and schemas
├── .env.example              # Example environment variables
├── .gitignore
├── main.py                   # FastAPI application entry point
├── README.md                 # This file
└── requirements.txt          # Python dependencies
```

## Development

### Running Tests

```bash
pytest
```

### Code Style

This project uses:
- Black for code formatting
- isort for import sorting
- flake8 for linting

### Pre-commit Hooks

Set up pre-commit hooks to ensure code quality:

```bash
pip install pre-commit
pre-commit install
```

## Deployment

For production deployment, consider using:

- **ASGI Server**: Uvicorn with Gunicorn
- **Process Manager**: Systemd, Supervisor, or Docker
- **Reverse Proxy**: Nginx or Traefik

## Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `MONGODB_URL` | MongoDB connection string | `mongodb://localhost:27017/` |
| `MONGODB_NAME` | Database name | `bookmyshoot` |
| `SECRET_KEY` | Secret key for JWT token signing | - |
| `ALGORITHM` | Algorithm for JWT | `HS256` |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | Token expiration time in minutes | `1440` (24h) |
| `DEBUG` | Enable debug mode | `False` in production |
| `ENVIRONMENT` | Application environment | `development` |

## Contributing

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/AmazingFeature`)
3. Commit your changes (`git commit -m 'Add some AmazingFeature'`)
4. Push to the branch (`git push origin feature/AmazingFeature`)
5. Open a Pull Request

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## Acknowledgments

- FastAPI for the awesome framework
- MongoDB for the flexible database solution
- All contributors who have helped improve this project
