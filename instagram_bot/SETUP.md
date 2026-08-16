# Instagram auto-poster setup

This posts real feed photos to Instagram via Meta's official **Instagram API
with Instagram Login** - a token + GitHub Actions secrets, same category of
setup you already did for the Pinterest bot. Meta Business Suite does not
support bulk-scheduling image posts (only Reels), which is why this goes
through the API directly. This flow does **not** require a linked Facebook
Page or a Facebook account at all - you authorize with your Instagram login
only.

## 1. Make sure your Instagram account qualifies

The account must be a **Business** or **Creator** account (not Personal).
In the Instagram app: Settings -> Account type and tools -> switch if
needed. That's the only account-side requirement - no Facebook Page needed.

## 2. Create a Meta App and add the Instagram product

1. Go to https://developers.facebook.com/apps (you still need a free Meta
   developer account to register an app, but nothing here touches Facebook
   Pages or your personal Facebook profile beyond logging in to create it).
2. Create an app -> type "Other" -> "Business" -> name it anything (e.g.
   "DearDariaCo IG Bot").
3. In the app dashboard sidebar, click **Add Product**, find **Instagram**,
   click **Set Up**.
4. In the Instagram product's settings, choose the **Instagram Business
   Login** setup (as opposed to "Business Login for Instagram via
   Facebook"). This page shows an **Instagram App ID** and **Instagram App
   Secret** - copy both, you'll need them below (different from any
   Facebook App ID/Secret shown elsewhere in the dashboard).
5. Add a placeholder **OAuth redirect URI** in that same settings page -
   any HTTPS URL you control works, even one that just 404s, e.g.
   `https://github.com/deardariaco` - you only need it so Instagram has
   somewhere to redirect to; you'll read the result out of the browser's
   address bar, not from that page actually loading anything useful.
6. Under **Roles -> Instagram testers**, add your own Instagram account as
   a tester (this app starts in Development mode, so only added testers can
   authorize it). Then open the Instagram app -> Settings -> Apps and
   websites -> Tester invites, and accept the invite.

## 3. Authorize and get a short-lived token

Build this URL, filling in your Instagram App ID and the redirect URI from
step 2 (URL-encode the redirect URI):

```
https://www.instagram.com/oauth/authorize
  ?client_id=<INSTAGRAM_APP_ID>
  &redirect_uri=<REDIRECT_URI>
  &response_type=code
  &scope=instagram_business_basic,instagram_business_content_publish
```

Paste it into a browser, log in as the Instagram account (if not already),
and approve. You'll land on your redirect URI with `?code=...#_` in the
address bar - copy that `code` value (everything after `code=` and before
the trailing `#_`).

Exchange the code for a short-lived access token:

```
POST https://api.instagram.com/oauth/access_token
  client_id=<INSTAGRAM_APP_ID>
  client_secret=<INSTAGRAM_APP_SECRET>
  grant_type=authorization_code
  redirect_uri=<REDIRECT_URI>
  code=<CODE_FROM_ABOVE>
```

(e.g. via curl: `curl -X POST https://api.instagram.com/oauth/access_token -F client_id=... -F client_secret=... -F grant_type=authorization_code -F redirect_uri=... -F code=...`)

The response has `access_token` (short-lived, ~1 hour) and `user_id`.

## 4. Exchange for a long-lived token (~60 days) and get IG_USER_ID

```
GET https://graph.instagram.com/access_token
    ?grant_type=ig_exchange_token
    &client_secret=<INSTAGRAM_APP_SECRET>
    &access_token=<SHORT_LIVED_TOKEN>
```

The `access_token` in this response is your **`IG_ACCESS_TOKEN`**. It lasts
~60 days and can be refreshed before expiry by calling
`GET https://graph.instagram.com/refresh_access_token?grant_type=ig_refresh_token&access_token=<CURRENT_TOKEN>`
periodically (worth doing every ~50 days if you want this running past two
months).

Confirm the account and get your numeric ID:

```
GET https://graph.instagram.com/v21.0/me?fields=user_id,username&access_token=<LONG_LIVED_TOKEN>
```

The `user_id` in that response is your **`IG_USER_ID`**.

## 5. Add GitHub repo secrets

In the repo: Settings -> Secrets and variables -> Actions -> New repository
secret.

| Secret name | Value |
|---|---|
| `IG_ACCESS_TOKEN` | the long-lived token from step 4 |
| `IG_USER_ID` | the numeric user_id from step 4 |

(`IMAGE_BASE_URL` is not a secret here - the workflow builds it automatically
from the public repo's raw GitHub URL, since `images_instagram/` is already
public in this repo, same trick the Pinterest bot's `IMAGE_BASE_URL`
secret uses.)

## 6. Test before trusting it

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

## 7. Schedule

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
