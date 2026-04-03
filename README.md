# BookMyShoot Backend

FastAPI backend for BookMyShoot. It handles authentication, photographer discovery, organizations, portfolio management, profile media updates, and Cloudinary-based uploads.

## Tech Stack
- FastAPI
- MongoDB + Motor
- JWT auth
- Cloudinary
- Pydantic

## Implemented Requirements
### Authentication and user profile
- Email/password signup and login
- JWT session restore via `GET /api/auth/me`
- Photographer and customer roles
- Organization-aware photographer signup
- Profile image update
- Cover image update
- Photographer bio update

### Photographer discovery
- Public photographer listing
- Organization badges and organization lookup in photographer results
- Public photographer details endpoint
- Public photographer event and gallery exploration

### Portfolio management
- Photographer-only portfolio CRUD
- Event suggestions API
- Portfolio gallery validation:
  - minimum 3 images
  - maximum 10 images
  - thumbnail fallback to first image

### Organizations explorer
- List organizations
- View organization details
- View photographers inside an organization

### Media upload
- Backend `/api/upload` endpoint for multipart image upload
- Cloudinary upload service
- MongoDB stores only image URLs

## Key API Endpoints
### Auth
| Method | Endpoint | Purpose |
|---|---|---|
| `POST` | `/api/auth/signup` | Register user |
| `POST` | `/api/auth/login` | Login |
| `GET` | `/api/auth/me` | Restore current session |
| `PUT` | `/api/auth/profile-image` | Update avatar URL |

### User profile
| Method | Endpoint | Purpose |
|---|---|---|
| `PUT` | `/api/users/cover-image` | Update cover image |
| `PUT` | `/api/users/bio` | Update photographer bio |

### Upload
| Method | Endpoint | Purpose |
|---|---|---|
| `POST` | `/api/upload` | Upload image to Cloudinary and return `secure_url` |

### Portfolio
| Method | Endpoint | Purpose |
|---|---|---|
| `POST` | `/api/portfolio` | Create portfolio |
| `GET` | `/api/portfolio` | List logged-in photographer portfolios |
| `GET` | `/api/portfolio/{id}` | Get one portfolio |
| `PUT` | `/api/portfolio/{id}` | Update portfolio |
| `DELETE` | `/api/portfolio/{id}` | Delete portfolio |

### Events and exploration
| Method | Endpoint | Purpose |
|---|---|---|
| `GET` | `/api/events/suggestions` | Distinct event suggestions |
| `GET` | `/api/organizations` | List organizations |
| `GET` | `/api/organizations/{id}` | Organization details + photographers |
| `GET` | `/api/organizations/{id}/photographers` | Photographers in organization |
| `GET` | `/api/photographers` | Public photographer listing |
| `GET` | `/api/photographers/{id}` | Public photographer details |
| `GET` | `/api/photographers/{id}/portfolios` | Public photographer portfolios |
| `GET` | `/api/photographers/{id}/events` | Distinct photographer events |
| `GET` | `/api/photographers/{id}/gallery?event=...&location=...` | Event/location filtered gallery |

## Setup
### 1. Install
```bash
cd /home/latika/Desktop/Demos/bookmyshoot/backend
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 2. Configure env
```bash
cp .env.example .env
```

Required variables:
```env
MONGODB_URL=mongodb://localhost:27017/
SECRET_KEY=your-secret-key
ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=1440

CLOUD_NAME=your-cloudinary-cloud-name
API_KEY=your-cloudinary-api-key
API_SECRET=your-cloudinary-api-secret
```

### 3. Run
```bash
python3 main.py
```

Backend runs on:
- `http://localhost:3001`
- Swagger: `http://localhost:3001/docs`

## Implementation Notes
### Data model highlights
- Users support:
  - `profile_picture`
  - `cover_image`
  - `bio`
  - `organization_id`
- Portfolios store:
  - `event_name`
  - `shoot_date`
  - `city`
  - `destinations`
  - `days`
  - `props`
  - `thumbnail_url`
  - `gallery[]`

### Upload flow
1. Frontend uploads image to `/api/upload`
2. Backend uploads to Cloudinary
3. Cloudinary `secure_url` is returned
4. URL is saved on user or portfolio documents

### Public photographer gallery flow
1. Load photographer details
2. Load distinct events
3. Filter gallery by event
4. Optionally filter by one or more locations

## Project Structure
```text
backend/
├── app/
│   ├── api/endpoints/
│   │   ├── auth.py
│   │   ├── events.py
│   │   ├── organizations.py
│   │   ├── photographers.py
│   │   ├── portfolio.py
│   │   ├── upload.py
│   │   └── users.py
│   ├── core/
│   ├── crud/
│   ├── db/
│   ├── models/
│   │   ├── organization.py
│   │   ├── portfolio.py
│   │   └── user.py
│   └── services/
│       └── cloudinary_service.py
├── main.py
├── requirements.txt
└── .env.example
```

## Notes
- Do not commit `.env`
- Cloudinary secrets must stay backend-only
- MongoDB connectivity must work for both startup and request-time access
