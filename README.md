# Eurotrash cloud ticket watch

Monitor Young Vic's public Eurotrash availability without leaving a personal computer on.

## Running status

This source is prepared for deployment. It is **not yet deployed or verified on a GitHub runner**. A successful first cloud run and a delivered test email are required before calling the monitor active.

## Setup

1. Create a dedicated **public** GitHub repository. Standard Linux Actions runners in public repositories are free; do not choose paid large runners. Private repositories have finite included minutes and are not the intended deployment for this five-minute schedule.
2. Upload `monitor.py` and `.github/workflows/watch.yml` to its default branch. Enable Issues and Actions.
3. Set GitHub notification delivery to **Email and On GitHub** for participating conversations. Select the desired verified notification email in GitHub settings. Keep email addresses out of the public source.
4. Run **Actions → Eurotrash ticket watch → Run workflow**, with `test_notification` enabled. The bot will create a clearly marked test issue and assign/mention the repository owner. Verify the email arrives in the intended inbox.
5. For phone alerts, enable **Mentions** and **Assignments** in GitHub Mobile, or enable Gmail notifications.
6. Verify that a run reads the actual Eurotrash performance list. Initially, on 18 October 2026, there were 58 future performances and every one was sold out. A human-verification page or an empty list is an error, never evidence of sold-out inventory.

## Behaviour

- Checks approximately every five minutes on GitHub's servers. GitHub may delay or drop scheduled jobs, so this is not a guaranteed five-minute alert service.
- Reads only the official Eurotrash data: `https://www.youngvic.org/whats-on/eurotrash/` and its own public event-111 performance endpoint.
- Tries the public JSON endpoint first, then the official page using GitHub's preinstalled Chrome/ChromeDriver. It does not solve CAPTCHAs or use a personal browser login.
- Excludes cancelled, sold-out, Access-only and invitation-only/press-night inventory.
- Announces when an official public booking link reopens. It explicitly asks the recipient to confirm actual seat availability and price on the booking page, and never claims tickets have been reserved.
- Deduplicates persistent availability and announces newly returned availability after a successful intervening sold-out check.
- Notifies after three consecutive read errors, and once when reading recovers.
- Uses only GitHub's automatic, repository-scoped workflow token. No Gmail passwords, mail-service API keys, or personal access tokens.
- Stops checking when the production has ended on 9 January 2027.
- Makes a small state commit at least every 14 days, to avoid GitHub's 60-day repository-inactivity schedule expiry.

## Validation

Run `python3 -m unittest discover -s tests -v`. A real cloud run is still required to verify the theatre's site is reachable from the runner, and a real test notification is required to verify delivery.

Official references: [GitHub Actions billing](https://docs.github.com/en/actions/concepts/billing-and-usage), [scheduled event limitations](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule), [email and mobile notifications](https://docs.github.com/en/subscriptions-and-notifications/get-started/configuring-notifications).
