# Free theatre ticket watch

Cloud monitors for **Young Vic — Eurotrash** and **Almeida — Golden Boy**, using their official ticket sources. A personal computer does not need to remain on. Public code contains no personal email address, passwords or personal access tokens.

## Schedule reliability

**This is not a reliable five-minute service.** Although the workflow requests a five-minute schedule, on 18 October 2026 only five automatic runs were observed between 06:36 and 19:36 UTC, with gaps of roughly **2–5 hours**. These runs did successfully read Eurotrash's public inventory. A brief release can be missed during a scheduling gap. [Automatic run evidence](https://github.com/Scr169/eurotrash-ticket-watch/actions/runs/39159511961).

GitHub can delay/drop schedules. Both monitors run when GitHub starts the workflow; the latest run log is the check timestamp. The schedule has no guaranteed response time.

## Monitored productions

| Production | Official source | End date, London time | State file |
| --- | --- | --- | --- |
| Eurotrash | Young Vic's official Spektrix public Web API | 9 January 2027 | `monitor-state.json` |
| Golden Boy | Almeida's actual filtered calendar query, followed by the official performance booking page for positive signals | 31 October 2026 | `golden-boy-state.json` |

### Golden Boy verification

The [official ticket guide](https://almeida.co.uk/how-to-get-tickets-to-golden-boy/) links to [the Golden Boy calendar](https://almeida.co.uk/calendar/?e=golden-boy). Its actual form and public calendar script identify WordPress event `11278` and the read-only `calendar` AJAX query. The official ticketing site identifies the corresponding production as `8745`. The browser calendar and the same live query both returned **16 future performances, all sold out**, on 18 October 2026.

A [real cloud run](https://github.com/Scr169/eurotrash-ticket-watch/actions/runs/39165022391) at **21:49 Europe/London on 18 October 2026** read the 16 sold-out performances, opened and verified an official Golden Boy performance page, and passed all 27 tests. The clearly labelled [setup test issue](https://github.com/Scr169/eurotrash-ticket-watch/issues/2) was delivered to the configured Gmail inbox. This was a manual setup run; the updated two-production workflow is scheduled but its own first automatic run has not yet been observed.

An enabled calendar booking link alone cannot trigger a ticket alert. The monitor opens only the official link, verifies the production/date/time, and requires a visible selectable public seat or an enabled ticket quantity, price and purchase control. It does not click these controls. Unknown, blocked or unrecognised pages are errors. Actual positive-inventory operation cannot be validated live while every performance is sold out; fixtures test the confirmation rules.

### Eurotrash verification and coverage limit

Manual reading and email delivery were verified, and subsequent **automatic scheduled reads were verified**. The Young Vic website displays 58 entries; the public API returns 55. The absent entries are 19 November Press Night and two 2 December performances. The reason for the latter two absences is unconfirmed. The public list is fetched anew every check, but full parity with the website has not been established.

## Alerts

- A new publicly bookable performance causes one Chinese GitHub issue mentioning the repository owner. GitHub delivers it to the owner's configured email and mobile notifications. Gmail delivery of the original setup test was verified.
- Each production has separate state, duplicate suppression, failure counts and notification markers. A failure for one production does not prevent the other step from running.
- A continuously available performance is not announced repeatedly. After a successful intervening sold-out check it can notify again.
- Three consecutive failed checks cause one clearly labelled **monitor failure** notice, followed by one recovery notice. A blocked, empty or invalid response is never treated as sold out.
- Alerts include London verification time, performance time, evidence of public availability and an official booking link. Unknown prices are explicitly unknown. Tickets may sell at any time.
- Member-only, invitation-only and eligibility-restricted inventory is excluded. Ordinary public tickets to accessible performances are eligible; a performance being relaxed or audio described does not alone make its ordinary seats restricted.
- No seats are selected, reserved or added to a basket; no purchase or theatre login is performed.
- Checks for each production stop after its end date. A small state heartbeat avoids GitHub's inactivity schedule expiry during the run.

## Phone and controls

Enable Gmail new-mail notifications, or GitHub Mobile **Mentions**. GitHub participating/@mention notifications must be enabled for **Email and On GitHub** with the intended verified email selected.

[Workflow controls](https://github.com/Scr169/eurotrash-ticket-watch/actions/workflows/watch.yml): run manually, test either production's notification, or disable the workflow. The Golden Boy test also checks cloud access to one official Golden Boy booking page and is explicitly labelled as a test, never a ticket alert.

Run `python3 -m unittest discover -s tests -v` — **27 tests** cover source identity, real disabled sold-out spans, sale windows, incorrect dates/productions, restricted stock, unconfirmed booking buttons, separate state, notification deduplication and failure/recovery retries. A green job alone is insufficient: inspect each production's actual result in the log/state file.

## Official references

- [Almeida Golden Boy](https://almeida.co.uk/whats-on/golden-boy/)
- [Almeida official return-ticket guide](https://almeida.co.uk/how-to-get-tickets-to-golden-boy/)
- [Young Vic Eurotrash](https://www.youngvic.org/whats-on/eurotrash/)
- [Spektrix public event filtering](https://integrate.spektrix.com/docs/apieventfiltering) and [seat availability](https://integrate.spektrix.com/docs/Availability)
- [GitHub standard public-runner billing](https://docs.github.com/en/actions/concepts/billing-and-usage) and [schedule limitations](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule)
