# Instagram auto-poster setup

This posts real feed photos to Instagram via Meta's official Graph API - the
same category of setup you already did for the Pinterest bot (a token +
GitHub Actions secrets), just for Instagram instead. Meta Business Suite
does not support bulk-scheduling image posts (only Reels), which is why this
goes through the API directly.

## 1. Make sure your Instagram account qualifies

- The account must be a **Business** or **Creator** account (not Personal).
  Instagram app -> Settings -> Account type and tools -> switch if needed.
- It must be **linked to a Facebook Page** you administer. Instagram app ->
  Settings -> Linked accounts -> Facebook (or via the Facebook Page's
  Settings -> Linked accounts).

## 2. Create a Meta App

1. Go to https://developers.facebook.com/apps and create an app -> type
   "Other" -> "Business".
2. In the app dashboard, add the **Instagram Graph API** product.
3. Under App Roles -> Roles, make sure your own Facebook account is an Admin
   (it usually is by default since you created the app).

## 3. Get your Instagram Business Account ID and an access token

Easiest path is the Graph API Explorer:

1. Go to https://developers.facebook.com/tools/explorer
2. Pick your app in the top-right dropdown.
3. Click "Generate Access Token" and grant these permissions when prompted:
   `instagram_basic`, `instagram_content_publish`, `pages_show_list`,
   `pages_read_engagement`.
4. Run `GET /me/accounts` - find your Page in the results, note its `id`.
5. Run `GET /<PAGE_ID>?fields=instagram_business_account` - this returns
   your Instagram Business Account ID. That's your `IG_USER_ID`.

The token Graph API Explorer gives you is short-lived (~1 hour). For the
bot to run unattended for a month, exchange it for a long-lived token
(~60 days):

```
GET https://graph.facebook.com/v21.0/oauth/access_token
    ?grant_type=fb_exchange_token
    &client_id=<YOUR_APP_ID>
    &client_secret=<YOUR_APP_SECRET>
    &fb_exchange_token=<SHORT_LIVED_TOKEN>
```

Long-lived tokens still expire after ~60 days - you'll need to repeat this
exchange periodically, or (better, for something running longer-term) set
up a **System User token** in Meta Business Suite -> Business Settings ->
System Users, which doesn't expire on the same clock. Either kind of token
works as `IG_ACCESS_TOKEN`.

## 4. Add GitHub repo secrets

In the repo: Settings -> Secrets and variables -> Actions -> New repository
secret.

| Secret name | Value |
|---|---|
| `IG_ACCESS_TOKEN` | the token from step 3 |
| `IG_USER_ID` | the Instagram Business Account ID from step 3 |

(`IMAGE_BASE_URL` is not a secret here - the workflow builds it automatically
from the public repo's raw GitHub URL, since `images_instagram/` is already
public in this repo, same trick the Pinterest bot's `IMAGE_BASE_URL`
secret uses.)

## 5. Test before trusting it

From your machine, with the repo cloned:

```
IG_ACCESS_TOKEN=... IG_USER_ID=... IMAGE_BASE_URL=https://raw.githubusercontent.com/deardariaco/deardariaco-pinterest-bot/main/images_instagram POSTS_PER_RUN=1 DRY_RUN=1 python instagram_bot/generate_and_post_instagram.py
```

`DRY_RUN=1` prints exactly what would be posted without calling the API.
Drop `DRY_RUN=1` (or set it to `0`) to actually publish one real post as a
manual test before turning on the schedule.

You can also trigger the GitHub Actions workflow manually: repo -> Actions
tab -> "Daily Instagram Posts" -> "Run workflow", instead of waiting for
the cron schedule.

## 6. Schedule

`.github/workflows/daily_instagram_posts.yml` runs 3 times a day (~9am,
1pm, 6pm US Eastern by default - edit the `cron:` lines if you're in a
different timezone; they're in UTC). Each run posts 1 photo, so that's
3 posts/day, cycling through all 65 eligible product photo sets with a
7-day no-repeat window before recycling.

## Notes

- 5 images (`calla_bloom_showpiece_ig_*.jpg`) don't match any catalog item
  and are skipped automatically - they're bonus shots with no corresponding
  entry in `content_bank_v2.json`. Post those manually if you want them up,
  or add a matching item to the content bank.
- Instagram's publish limit is 25 posts per rolling 24 hours per account -
  nowhere close to being hit at 3/day.
- Captions don't include the listing link (Instagram doesn't make caption
  links clickable) - they end with a "link in bio" call-to-action instead.
