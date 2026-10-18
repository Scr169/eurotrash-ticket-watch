# Eurotrash cloud ticket watch

Free public-repository GitHub Actions monitor for Young Vic's **Eurotrash**, without leaving a personal computer on. No email address, password or personal access token is stored in this public repository.

## Running status

Deployed at [Scr169/eurotrash-ticket-watch](https://github.com/Scr169/eurotrash-ticket-watch). A [real cloud check](https://github.com/Scr169/eurotrash-ticket-watch/actions/runs/39088151087) at **2026-10-18 02:54:24 Europe/London** successfully read **55 public performances**, with **zero ordinary public seats available**. A separately labelled test notification reached the intended Gmail inbox. The former local Codex check has been paused.

## Behaviour

- GitHub's standard free Linux runner checks approximately every five minutes. Scheduled runs can be delayed or dropped by GitHub; this is not a guaranteed five-minute service.
- Reads the theatre's official **Spektrix public Web-mode API**. Confirms the exact production name and event ID; excludes the similarly named programme merchandise.
- Checks public sale windows and explicit seat counts. A positive event summary requires a second per-performance check of ordinary purchasable seats before an alert.
- Excludes sold-out, cancelled, invitation-only/press-night and restricted seats. Wheelchair seats, companion locks and member-eligible seats do not count as ordinary public availability.
- Combines newly available performances into one Chinese GitHub issue mentioning the repository owner. GitHub delivers the mention to the owner's configured email and mobile notifications. No Gmail credentials or paid mail service are required.
- The alert includes verification time, performance date/time, the observed public seat count and an official booking link. Price is explicitly unknown; seats may sell at any time. It never adds tickets to a basket, reserves or buys.
- Deduplicates continuously available performances. A performance can notify again after an intervening successful sold-out check.
- Three consecutive read failures cause one clearly labelled failure notification, followed by one recovery notification. Invalid/empty responses are errors, never sold-out evidence.
- Each check is timestamped in its Actions log; `monitor-state.json` stores transitions and notification deduplication. A small state commit at least every 14 days avoids GitHub's 60-day inactivity expiry while the show is running.
- Stops reading tickets and sending alerts after 9 January 2027, London time.

## Notifications and phone

In GitHub notification settings, enable **Email and On GitHub** for participating conversations and @mentions, with the desired verified email selected. For phone alerts, enable Gmail new-mail notifications or GitHub Mobile **Mentions**. The monitor can send a clearly labelled connection test via Actions → Eurotrash ticket watch → Run workflow → `test_notification`.

## Validation and controls

`python3 -m unittest discover -s tests -v` — 17 meaningful tests cover merchandise exclusion, sale windows, mismatched data, seat restrictions, duplicate suppression and failure/recovery notification retries.

Run manually or disable the workflow at [Actions](https://github.com/Scr169/eurotrash-ticket-watch/actions/workflows/watch.yml). A green job alone is not proof of stock access: check its log and `monitor-state.json` for `sold_out` or `available`, rather than `unknown`.

## Official references

- [Spektrix public event and instance filtering](https://integrate.spektrix.com/docs/apieventfiltering)
- [Public seat status and availability](https://integrate.spektrix.com/docs/Availability)
- [Official iframe booking links and instance IDs](https://integrate.spektrix.com/docs/standardbookingflow)
- [GitHub Actions billing](https://docs.github.com/en/actions/concepts/billing-and-usage)
- [Scheduled-run limitations](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule)
- [Email and mobile notifications](https://docs.github.com/en/subscriptions-and-notifications/get-started/configuring-notifications)
