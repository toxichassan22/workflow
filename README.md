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
