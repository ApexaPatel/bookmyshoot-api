# BookMyShoot Backend

FastAPI backend for BookMyShoot. It handles authentication, photographer discovery, organizations, portfolio management, profile media updates, admin operations, simulated subscription/membership billing, quotations, reviews, and auction-based booking.

## Tech Stack
- FastAPI
- MongoDB + Motor
- JWT auth
- Cloudinary
- Pydantic

## Implemented Requirements (Current)
### Authentication and user profile
- Email/password signup and login
- JWT session restore via `GET /api/auth/me`
- Photographer and customer roles
- Organization-aware photographer signup
- Profile image update
- Cover image update
- Photographer bio update
- Photographer visibility defaults:
  - new photographers => `private`
  - other users => `public`

### Photographer discovery
- Public photographer listing
- Organization badges and organization lookup in photographer results
- Public photographer details endpoint
- Public photographer event and gallery exploration
- Visibility-aware marketplace listing:
  - only `visibility=public` photographers appear in explore
- Photographer self-visibility control:
  - photographers can switch `private/public`
- Admin visibility override:
  - admins can force `private/public` for any photographer

### Portfolio management
- Photographer-only portfolio CRUD
- Event suggestions API
- Portfolio gallery validation:
  - minimum 3 images
  - maximum 10 images
  - thumbnail fallback to first image
- Plan-aware limits:
  - per-plan photoshoot and gallery limits enforced in app flow

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

### Demo billing (simulated payments — photographers)
| Method | Endpoint | Purpose |
|---|---|---|
| `POST` | `/api/simulate-payment` | Body: `plan` (`pro` \| `premium`), `simulate_success` (bool). Records a row in `subscriptions`, upgrades user plan + 30-day window when successful. |

### Membership and auctions
| Method | Endpoint | Purpose |
|---|---|---|
| `POST` | `/api/membership/purchase` | Simulated membership purchase (price/duration pulled from `membership_config`) |
| `POST` | `/api/auction/create` | Customer creates auction event |
| `GET` | `/api/auction/list` | List auctions (Pro/Premium photographers only for marketplace view) |
| `POST` | `/api/auction/bid` | Place/update bid (Pro/Premium photographers only) |
| `GET` | `/api/auction/{event_id}/bids` | Auction owner views bids |
| `POST` | `/api/auction/select` | Auction owner finalizes winner |
| `POST` | `/api/auction/cancel` | Auction owner cancels open auction |

### Booking lifecycle
| Method | Endpoint | Purpose |
|---|---|---|
| `GET` | `/api/bookings/user` | Customer bookings (upcoming/past) |
| `GET` | `/api/bookings/photographer` | Photographer bookings list |
| `POST` | `/api/booking/cancel` | Cancel booking with role/date-based rules |
| `POST` | `/api/booking/complete` | Photographer marks booking complete on/after start date |

### Admin (requires `role: super_admin` / `admin` / `staff`)
| Method | Endpoint | Purpose |
|---|---|---|
| `GET` | `/api/admin/subscriptions/metrics` | Total / active subscription records and sum of successful demo amounts (INR) |
| `GET` | `/api/admin/subscriptions` | Table data: user, plan, amounts, status, payment id, dates |
| `GET` | `/api/admin/dashboard/summary` | Dashboard KPI summary including monthly memberships purchased |
| `GET` | `/api/admin/dashboard/graph` | 30-day trend graph data |
| `GET` | `/api/admin/users` | User management list |
| `GET` | `/api/admin/photographers` | Photographer management list |
| `PATCH` | `/api/admin/photographers/{user_id}/visibility` | Admin override photographer visibility |
| `GET` | `/api/admin/payments/subscriptions` | Subscription payments list |
| `GET` | `/api/admin/payments/memberships` | Membership payments list with status/filter support |
| `GET` | `/api/admin/payments/photoshoots` | Photoshoot payments list |
| `GET` | `/api/admin/payments/expenses` | Expenses list |
| `GET` | `/api/admin/payments/summary` | Monthly balance/revenue summary (subscription + membership + photoshoots - expenses) |
| `GET` | `/api/admin/revenue-summary` | Lifetime revenue split: subscription vs membership |
| `GET` | `/api/admin/plans` | Photographer plan configuration list (Free/Pro/Premium) |
| `PUT` | `/api/admin/plans/{plan_id}` | Update plan settings/price/activation |
| `GET` | `/api/admin/membership` | Membership config and aggregate metrics |
| `PUT` | `/api/admin/membership` | Update membership config |

To grant admin access, set a user’s `role` to `super_admin`, `admin`, or `staff` in MongoDB.

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
| `PATCH` | `/api/photographers/me/visibility` | Photographer updates own visibility (`private/public`) |

## Setup
### 1. Install
```bash
cd bookmyshoot-api
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
Use the **same Python environment** where you ran `pip install -r requirements.txt`.

```bash
cd bookmyshoot-api
source venv/bin/activate
python3 main.py
```

Or, without activating (venv created in `backend` as in step 1):
```bash
cd bookmyshoot-api
./venv/bin/python main.py
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
  - `visibility` (`private` / `public`)
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

### Visibility flow
1. Photographer signs up with default `visibility=private`
2. Photographer updates visibility from profile/portfolio controls
3. Admin can override visibility from admin panel
4. Explore endpoint returns only `public` photographers

### Booking completion flow
1. Booking exists with assigned photographer
2. Photographer can complete booking on/after event start date
3. Booking status and linked tasks are marked `completed`
4. If payment is pending, customer receives payment reminder email

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
