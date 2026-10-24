# YouTube growth workflow

Use this workflow for every upload and when reviewing existing videos. The portal stores channel observations and uses them to guide later metadata suggestions. It does not publish changes to YouTube automatically.

## Before publishing

- Define one primary viewer intent for the video: coding focus, study, reading, or relaxation.
- Choose one accurate primary phrase that describes what the viewer will listen to. Use it early in the title and naturally in the first sentence of the description when it fits.
- Make the specific scene, mood, or use case distinct. Avoid repeating the same generic title pattern across uploads.
- Keep title, description, thumbnail, music, and visual aligned. Do not imply a live broadcast, 24/7 availability, exact duration, or benefits that are not true.
- Treat search phrases as wording evidence only. They do not establish search volume or promise reach.

### Growth packaging suggestion

In the publication review, Growth can compose an editable title and description from the video's current metadata, selected intent, ranked Studio search phrases, and comparable channel history. Phrase ranking uses recurrence across snapshots and distinct videos; it is not a search-volume estimate. Historical comparisons are shown only when at least five matching videos exist. The creator enters or copies Studio observations into the portal; the portal does not automatically sync YouTube Analytics. Generating a package requires an explicit confirmation of a maximum US$0.02 cost. The result never publishes by itself and must be reviewed in the title and description fields.

## After publishing

Record actual values from YouTube Studio in the portal: video URL, observation date, window (24h, 7d, 28d, or 90d), age in days, format, intent, impressions, CTR, views, watch time, average view duration, returning viewers, and retention at minutes 15, 30, and 45 when available. Record the Studio search terms exactly as shown. Leave unavailable fields blank; blank is not zero.

Review the upload at comparable ages. Compare only videos with the same intent, format, and observation window. The historical range requires at least five distinct comparable videos and reports the 25th percentile, median, and 75th percentile. It is a descriptive range from the channel's history, not a forecast or an algorithm projection.

## Reference channels

Capture public title, URL, publication date when known, view count, and observation date for selected reference videos. Revisit the same public video on a later date before interpreting velocity. Approximate public views per day is a difference between captures; it is not official views-per-hour, CTR, impressions, or retention. Compare a video's pace only against other captured videos from that same reference channel.

## Decisions

- Low impressions with a relevant topic: review topic timing and whether the channel has enough comparable history before changing packaging.
- Impressions with weak CTR: test one packaging variable at a time and keep a dated experiment record.
- Good CTR with weak viewing duration or early retention: improve the match between title/thumbnail promise and the opening, audio, and pacing.
- Recheck changes after a comparable observation window. Record what changed so later comparisons remain interpretable.

Do not promise that metadata, tags, or trend phrases will cause recommendations. Use the data to choose experiments, then evaluate the actual YouTube Studio response.

## Publication harness gate

The YouTube publication form loads the channel's observed phrases and same-intent, same-format historical context before an upload is queued. Select one short, accurate primary phrase, apply it to the title and opening description, and review both fields. The server blocks queueing unless that phrase appears within the first 60 title characters and in the first description sentence. The chosen intent and phrase are stored with the publication record. For exported programs, the publication intent must match the saved program intent; update the program before exporting if the target viewer changes.
