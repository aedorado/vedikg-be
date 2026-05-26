# Render Deployment Guide

This FastAPI application is configured for deployment on Render.

## Prerequisites

- Render account (https://render.com)
- PostgreSQL database (Supabase or similar)
- Gemini API key

## Deployment Steps

### 1. Create a Render Web Service

1. Go to [Render Dashboard](https://dashboard.render.com)
2. Click "New +" and select "Web Service"
3. Connect your GitHub repository
4. Configure the service:
   - **Name**: vedikg-be (or your preferred name)
   - **Environment**: Python 3
   - **Build Command**: `pip install -r requirements.txt`
   - **Start Command**: `uvicorn main:app --host 0.0.0.0 --port $PORT`
   - **Plan**: Free (or your preferred plan)

### 2. Set Environment Variables

In the Render dashboard for your service, add the following environment variables:

- `POSTGRES_URL`: Your PostgreSQL connection string (e.g., from Supabase)
  - Format: `postgresql+psycopg://user:password@host:port/database`
- `GEMINI_API_KEY`: Your Google Gemini API key

### 3. Deploy

Once environment variables are set, Render will automatically deploy. Any push to your main branch will trigger a redeploy.

## Environment Variables

### Required
- `POSTGRES_URL`: PostgreSQL database URL
- `GEMINI_API_KEY`: Google Gemini API key

### Optional
- `PORT`: Server port (automatically set by Render, default: 8000)

## Troubleshooting

### Deployment Fails
- Check logs in Render dashboard
- Ensure all dependencies in `requirements.txt` are available
- Verify environment variables are set correctly

### Application Errors
- Check live logs in Render dashboard under "Logs"
- Verify database connectivity with current POSTGRES_URL
- Ensure Gemini API key is valid

## Health Check

The API exposes a health check endpoint at `/health`:

```bash
curl https://your-service-url.onrender.com/health
```

Expected response: `{"status":"ok"}`

## API Documentation

Once deployed, view the auto-generated API docs at:
- Swagger UI: `https://your-service-url.onrender.com/docs`
- ReDoc: `https://your-service-url.onrender.com/redoc`

## Notes

- Free tier services on Render spin down after 15 minutes of inactivity
- For production use, consider upgrading to a paid plan
- The application uses CORS with `allow_origins=["*"]` - adjust in production for security
