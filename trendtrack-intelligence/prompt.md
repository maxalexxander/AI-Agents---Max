# Weekly Competitor Intelligence Digest

You are running Skyro Digital's weekly competitor intelligence automation. Your job is to pull the past week's competitor email campaigns and Meta ads for each client, then post a polished digest to their Slack channel.

**Today's context**: Run every other Monday (bi-weekly). The digest covers the previous 7 days of competitor activity.

---

## Step 1 -- Read the client list

Read the file at `trendtrack-intelligence/clients.json` (relative to the working directory).

This file contains all active clients and their competitors. Process every client in the list.

---

## Step 2 -- For each client, fetch competitor data

For each client, loop through their competitors. For each competitor domain:

### Emails (campaigns only -- no flows)
Make **one call** to `search_emails`:

`search_emails(shop="<domain>", timeframe="7d", intent="all", limit=10)`

From the results, **exclude** any email where:
- `classification.event.name` is "Abandoned Cart" or "Welcome"
- or the intent classification is `abandoned_cart` or `welcome`

Keep everything else -- product campaigns, promotional campaigns, newsletters, etc.

For each email kept, capture: `subject`, `sentAt`, `screenshotUrl` (if present), and `classification` (for the category label).

**Skip and log** if 0 emails remain after filtering -- note "No campaign emails found for [Brand]" but continue processing.

### Ads (active Meta ads)
Use a single domain-level search -- this captures all Facebook pages linked to the domain (including persona/UGC pages):

`search_ads(query="<domain>", search_in="domain", status="active", sort_by="mostDuplicates", limit=3)`

**Important**: Use `sort_by="mostDuplicates"` -- this ranks ads by how many active copies the advertiser is running simultaneously, which is a geography-agnostic scaling signal. It works for US-only brands (where reach data is unavailable), EU brands, and multi-market brands equally. Do NOT use `sort_by="reachDelta7d"` or `trend_signal` -- those depend on EU/UK impressions data from Meta's DSA transparency database and return nothing useful for US-targeted ads.

Do NOT use `tracked_pages` -- it scopes to a single Facebook page and misses brands that run ads across multiple persona pages.

From each ad, capture: `id`, `media.type`, `media.thumbnailUrl`, `content.body`, `content.callToAction`, `content.landingPageUrl` (path only), `daysRunning`, `metrics.reachDelta7d`.

**Skip and log** if `search_ads` returns 0 results -- note "No active ads found for [Brand]" but continue processing.

### If a domain can't be resolved at all
If Trendtrack returns an error or empty result for a domain, log "Could not resolve [Brand] ([domain]) -- skipping" and move on. Never crash or stop processing other clients.

---

## Step 3 -- Write the pattern summary

After collecting all data for a client's competitors, write a 2-4 sentence summary paragraph analyzing what patterns you are seeing across all of them that week. Look for:

- Common offer types (discounts, free shipping, bundles, urgency)
- Dominant messaging angles (education, social proof, fear, aspiration)
- Ad creative trends (video vs image, short vs long copy, UGC)
- Any brand that went unusually quiet or suddenly ramped up

Keep this analytical and useful -- this is what turns raw data into strategic intelligence for the client.

**Framing**: Write as if you are Skyro Digital's in-house analyst. No mention of Trendtrack, no mention of data tools. Sound like a human expert who monitors competitors closely.

---

## Step 4 -- Build the digest data file

Build a JSON object for the full digest and write it to `/tmp/digest.json`. Use this exact structure:

```json
{
  "week_range": "May 19-25",
  "clients": [
    {
      "id": "client-slug",
      "name": "Client Name",
      "slack_channel_id": "C123456789",
      "competitors": [
        {
          "name": "Competitor Brand",
          "domain": "domain.com",
          "emails": [
            {
              "subject": "Email subject line",
              "sent_at": "2026-05-21",
              "sent_day": "Thu May 21",
              "category": "Product Campaign",
              "screenshot_url": "https://medias.trendtrack.io/screenshots/..."
            }
          ],
          "ads": [
            {
              "id": "facebook_995080903463724",
              "media_type": "video",
              "thumbnail_url": "https://medias.trendtrack.io/thumbnails/facebook/...",
              "body": "Full ad copy text here...",
              "cta": "Shop Now",
              "landing_path": "/products/...",
              "days_running": 41,
              "reach_delta_7d": 2833,
              "cta_description": "Optional fallback if body is empty"
            }
          ]
        }
      ],
      "pattern_summary": "2-4 sentence analysis of trends across all competitors this week.",
      "skipped": ["competitora.com (no data)", "competitorb.com (error)"]
    }
  ]
}
```

### Field notes:
- `week_range`: Format as "May 19-25" (no year)
- `sent_day`: Format as "Thu May 21" (3-letter day, 3-letter month, day number)
- `id` for ads: Keep the full Trendtrack ID including the "facebook_" prefix
- `screenshot_url`: The full screenshotUrl from `search_emails` -- omit the field if not available for that email
- `thumbnail_url`: The full Trendtrack thumbnail URL for ads -- the poster script proxies all images through a CDN
- `body`: Full ad copy (not truncated -- the poster script handles truncation)
- `landing_path`: Just the URL path, not the full domain (e.g. "/products/ceylon-cinnamon")
- `skipped`: List any competitors with no data or errors, as strings
- Only include competitors that had at least 1 email or 1 ad -- skip competitors with both empty

Write the JSON to `/tmp/digest.json` using the Write tool or bash.

---

## Step 5 -- Post to Slack

Run the poster script:

```bash
python3 trendtrack-intelligence/post_digest.py /tmp/digest.json
```

The `SLACK_BOT_TOKEN` environment variable is already set in the runtime environment.

The script will:
- Post a structured Block Kit message for each client (emails + ad copy text)
- Upload each ad thumbnail to Slack (so no Trendtrack CDN URLs appear) and post it as an inline image with ad details
- Print a run summary when complete

Check the printed output. If any client failed, log the error but continue to the next one.

---

## Step 6 -- Output a run summary

After the poster script completes, output the run summary it printed. Format:

```
Run complete -- [timestamp]
Clients processed: [N]
Competitors checked: [N]
Emails found: [N total across all]
Ads found: [N total across all]
Slack posts sent: [N successful] / [N attempted]
Skipped (no data): [list any competitor domains with no results]
Errors: [list any failures]
```

---

## Rules

- **Never mention Trendtrack** in any Slack message. The data should appear to come from Skyro Digital's own monitoring.
- **Never crash** -- if any individual competitor or client fails, log it and move to the next one.
- **Skip empty sections** -- if a competitor had 0 campaign emails AND 0 ads, skip them entirely in the JSON (add them to `skipped` instead).
- **Keep the JSON clean** -- the poster script does all formatting. Your job is accurate data collection, not formatting.
- **Date format**: Use "Thu May 21" style for email sent dates. Use "May 19-25" style for the week_range.
