# YouTube growth workflow

Use this workflow for every upload and when reviewing existing videos. The portal stores channel observations and uses them to guide later metadata suggestions. It does not publish changes to YouTube automatically.

## Before publishing

- Define one primary viewer intent for the video: coding focus, study, reading, or relaxation.
- Choose one accurate primary phrase that describes what the viewer will listen to. Prefer a phrase observed in YouTube Studio for this intent and format; if none is available, use the channel-intent fallback. An observed query is wording evidence, not search-volume evidence.
- Use the shared Growth and harness contract: title begins with the exact primary phrase, followed by one concise scene or use cue. Keep the title under 100 characters, use no more than one separator, and keep the text after the primary phrase to seven words or fewer. The complete title must read naturally aloud; reject keyword chains and repeated intent. Proofread and correct spelling before approval, and include duration only after the final video duration is measured.
- Write the description in natural English, 450–900 characters, in 2–3 useful paragraphs. Its first sentence repeats the primary phrase naturally, names the specific supported scene, and fulfills the title promise. Follow with accurate music/listening details and a concise viewer invitation when appropriate. Add a tracklist only when verified timestamps and track names are available; do not pad with generic claims.
- Make the specific scene, mood, or use case distinct. Avoid repeating the same generic title pattern across uploads.
- Preserve each video's defining subject, setting, visual direction, and story beats in both the title and opening description when supported by its approved source. Search phrases clarify the video; they do not replace its concept. Growth retrieves approved pilot plans and export-linked creator plans server-side. For videos with a `production_spec`, the harness derives a compact content brief from its scene registry, music direction, weather, time of day, and scheduled actions. This is metadata-grounded context, not a claim of frame-by-frame computer vision or audio recognition.
- Keep title, description, thumbnail, music, and visual aligned. Do not imply a live broadcast, 24/7 availability, exact duration, or benefits that are not true.
- Treat search phrases as wording evidence only. They do not establish search volume or promise reach.

Example for a verified Halloween café scene (primary phrase: “Lo-fi music for coding”):

- Good title: `Lo-fi music for coding | Halloween Café Focus`
- Reject: `Lo-fi music for coding | Hallowen Café Relaxing jazzhop for study and focus`
- The description must mention the Halloween café in its opening and describe only musical details confirmed for that video.

### Growth packaging suggestion

In the publication review, Growth composes an editable title and description from the video's source metadata and harness context, selected intent, ranked Studio search phrases, and comparable channel history. Phrase ranking uses recurrence across snapshots and distinct videos; it is not a search-volume estimate. Historical comparisons are shown only when at least five matching videos exist. The creator enters or copies Studio observations into the portal; the portal does not automatically sync YouTube Analytics. Generating a package requires an explicit confirmation of a maximum US$0.02 cost. The result never publishes by itself and must be reviewed in the title and description fields.

## After publishing

Record actual values from YouTube Studio in the portal: video URL, observation date, window (24h, 7d, 28d, or 90d), age in days, format, intent, impressions, CTR, views, watch time, average view duration, returning viewers, and retention at minutes 15, 30, and 45 when available. Record the Studio search terms exactly as shown. Leave unavailable fields blank; blank is not zero.

Review the upload at comparable ages. Compare only videos with the same intent, format, and observation window. The historical range requires at least five distinct comparable videos and reports the 25th percentile, median, and 75th percentile. It is a descriptive range from the channel's history, not a forecast or an algorithm projection.

## Reference channels

Capture public title, URL, publication date when known, view count, and observation date for selected reference videos. Revisit the same public video on a later date before interpreting velocity. Approximate public views per day is a difference between captures; it is not official views-per-hour, CTR, impressions, or retention. Compare a video's pace only against other captured videos from that same reference channel.

## Proactive channel Growth

The Growth overview turns manually recorded YouTube Studio observations into a short, evidence-linked priority list. Record channel-level views, impressions, CTR, watch time, average view duration, net subscribers, monthly audience, new/casual/regular audience, traffic-source mix, end-screen click rate, and current Studio search/trend phrases with the date and 7/28/90-day window. Record per-video title and approved content theme with each metric snapshot so trend fit is checked against the actual catalog.

Use the signal to propose the next measurable review: track net subscribers per 1,000 views across equivalent windows; compare traffic-source mix and CTR/watch duration by source; inspect end-screen continuity; convert discovery into returning viewers; and compare CTR only within at least three long-form videos with 28-day snapshots and 100+ impressions each. A trend phrase that overlaps a catalog title/theme is editorial fit only, not search volume or a forecast. Missing values stay unknown. The engine does not publish, alter packaging, edit settings, generate Shorts, or claim causality.

## TubeLab platform review and native adaptation (2026-10-27)

The platform separates research (channel/niche discovery, outlier videos, trending title formats, weekly reports), creation (voice-guided scriptwriting), analysis (niche, monetization and termination trackers), and tools (keyword rank tracking/checking and public video metadata extraction). Its outlier search can sort and filter by views-to-channel-average ratio, z-score, format, recency, language, duration, channel size and other estimated attributes. Its trending-format reports look for repeated title patterns and prioritize patterns whose usage is spreading. These are useful research methods; tool scores, revenue estimates and competitor view counts are not first-party Studio Analytics.

Native adaptation: use the existing public-reference capture history to compare a candidate video's approximate views/day against the median of at least three observed videos from that same reference channel, format, and intent. Growth now surfaces a strong relative outlier as a low/medium-priority research lead with its URL and capture interval. Extract the editorial mechanism (viewer intent, setting, duration or title structure), then create an original idea that fits our approved video context. Validate results with our own YouTube Studio impressions, source-specific CTR, viewing time and returning audience. Do not infer competitor impressions, CTR, retention, search demand or causality from public views. The exact TubeLab rank position and estimated RPM cannot be recreated from native Studio, so do not invent a native equivalent.

The TubeLab API separates search/scan requests from public video-data reads. Its current documentation lists credit costs for search/scan endpoints (including 50–100 credits for a scan); this harness remains independent of TubeLab and does not make those requests. The public rank checker can produce a country/keyword position, but a personalized search result is not a replacement for the Studio's actual traffic and query reports. Scriptwriting, extraction and automated reports are separate features and do not belong in the Growth recommendation path. Shorts research and production continue in their own later workflow.

Reference documentation: [Outliers API](https://tubelab.net/docs/api/reference/search-outliers), [Trending Formats API](https://tubelab.net/docs/api/reference/search-trending-formats), [Rank Checker](https://tubelab.net/checker), and [API pricing](https://tubelab.net/docs/api/pricing). Pricing and feature access may change; the review used product screens and docs on the date above.

## Decisions

- Low impressions with a relevant topic: review topic timing and whether the channel has enough comparable history before changing packaging.
- Impressions with weak CTR: test one packaging variable at a time and keep a dated experiment record.
- Good CTR with weak viewing duration or early retention: improve the match between title/thumbnail promise and the opening, audio, and pacing.
- Recheck changes after a comparable observation window. Record what changed so later comparisons remain interpretable.

Do not promise that metadata, tags, or trend phrases will cause recommendations. Use the data to choose experiments, then evaluate the actual YouTube Studio response.

## Publication harness gate

The YouTube publication form loads ranked observed phrases and same-intent, same-format historical context before an upload is queued. Confirm the bounded suggestion cost to compose a title and description, then review and edit both fields. The server blocks queueing unless the selected phrase appears within the first 60 title characters and in the first description sentence. The chosen intent and phrase are stored with the publication record. For exported programs, the publication intent must match the saved program intent; update the program before exporting if the target viewer changes.
