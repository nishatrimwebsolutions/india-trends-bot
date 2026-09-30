# India X Trends → WhatsApp (free)

Every hour from 9 AM to 11 PM IST, this sends the India Top 10 X/Twitter trends to your WhatsApp.
🆕 marks a trend that's new since the last hour, and ⬆️ marks one that climbed 3 or more places.

Stack (all free): trends24.in (public page) · CallMeBot WhatsApp API · GitHub Actions cron.

## Setup

1. **CallMeBot API key (one time)**
   - Open https://www.callmebot.com/blog/free-api-whatsapp-messages/ and save the WhatsApp number shown there in your contacts.
   - From your WhatsApp, send it this message: `I allow callmebot to send me messages`
   - It replies with your **apikey**.
2. **GitHub repo**: create a new repo (public = unlimited free minutes) and push this folder to it.
3. **Secrets**: repo → Settings → Secrets and variables → Actions → New repository secret
   - `WHATSAPP_PHONE`: your number with country code, e.g. `+919876543210`
   - `CALLMEBOT_APIKEY`: the key from step 1
4. **Test**: repo → Actions → "India X trends to WhatsApp" → **Run workflow**. The message should reach WhatsApp within a minute.

After that it runs on its own every hour.

## Local test

```
python trends_bot.py --dry-run
```

## Good to know

- GitHub's scheduled runs are sometimes a few minutes late (15+ minutes at busy times).
- On a public repo, GitHub disables the schedule after 60 days without a commit. You'll get an email; turn it back on with one click.
- If trends24.in changes its page layout, the run fails with a "layout changed" error, and the regex in `trends_bot.py` needs updating.
- Change the number of trends with the `TOP_N` env var in the workflow. Change the hours with the `cron` line (it's in UTC: IST = UTC + 5:30).
