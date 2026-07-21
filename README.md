---
title: Real Estate Proposal Generator
emoji: 🏢
colorFrom: red
colorTo: gray
sdk: docker
app_port: 7860
pinned: false
---

# Real Estate Proposal Generator (Manafe)
AI-powered Presentation and Investment Proposal Generator platform.

## Google Maps Setup

To enable map slides (location overview, landmarks, access, catchment), you need a Google Cloud project with the following APIs restricted to one API key:

1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Create or select a project and enable billing
3. Enable these 4 APIs only:
   - **Maps Static API**
   - **Places API (New)**
   - **Distance Matrix API**
   - **Street View Static API**
4. Create an API key and restrict it to the 4 APIs above
5. Copy the key into your `.env` file:
   ```
   GOOGLE_MAPS_API_KEY=your-key-here
   ```

## Map-Related API Endpoints

- `POST /api/geocode` — convert address to lat/lng
- `POST /api/nearby-landmarks` — get nearby places
- `POST /api/generate-map-images` — generate all map images for a project
- `POST /api/generate-slides` — automatically generates map images before creating slides

## AI Rules Management

Company admins can manage AI design/content rules from the new **قواعد AI** page. Changes are classified by risk (green/yellow/red) and logged in the `ai_rules_log` table.

## Deploy on Render

The repo includes a `render.yaml` Blueprint that deploys the Flask backend and the single-page frontend as one Docker Web Service, using Render PostgreSQL as the database.

1. Push the latest code to GitHub:
   ```bash
   git add .
   git commit -m "Render deploy config"
   git push origin main
   ```
2. In the Render Dashboard, create a **New Blueprint** and select your `toxichassan22/workflow` repo.
3. Render will detect `render.yaml`. Open the new `manafe` Web Service and set the environment variables:
   - `DATABASE_URL` — copy the **Internal Connection String** from your existing Render Postgres (`dpg-d9fmm13rjlhs73alaau0-a`)
   - `ADMIN_EMAIL` — super-admin email address (e.g. `admin@yourdomain.com`)
   - `ADMIN_PASSWORD` — strong password (12+ characters)
   - `ZAI_KEY` — your Z.ai API key
   - `OPENROUTER_KEY` — your OpenRouter API key
   - `GOOGLE_MAPS_API_KEY` — your Google Maps API key
4. Save the environment variables and trigger a deploy.
5. Once the deploy succeeds, open the service URL. The first request will create all Postgres tables and seed the admin account.

If `DATABASE_URL` is not set, the service will fall back to a local SQLite file inside the container (data is lost on redeploy).
