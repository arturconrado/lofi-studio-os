# YouTube growth workflow

Use this workflow for every upload and when reviewing existing videos. The portal stores channel observations and uses them to guide later metadata suggestions. It does not publish changes to YouTube automatically.

## Before publishing

- Define one primary viewer intent for the video: coding focus, study, reading, or relaxation.
- Choose one accurate primary phrase that describes what the viewer will listen to. Prefer a phrase observed in YouTube Studio for this intent and format; if none is available, use the channel-intent fallback. An observed query is wording evidence, not search-volume evidence.
- Use the shared Growth and harness contract: title begins with the exact primary phrase, followed by one concise scene or use cue. Keep the title under 100 characters, use no more than one separator, and keep the text after the primary phrase to seven words or fewer. The complete title must read naturally aloud; reject keyword chains and repeated intent. Proofread and correct spelling before approval, and include duration only after the final video duration is measured.
- Write the description in natural English, 450–900 characters, in 2–3 useful paragraphs. Its first sentence repeats the primary phrase naturally, names the specific supported scene, and fulfills the title promise. Follow with accurate music/listening details and a concise viewer invitation when appropriate. Add a tracklist only when verified timestamps and track names are available; do not pad with generic claims.
- Make the specific scene, mood, or use case distinct. Avoid repeating the same generic title pattern across uploads.
- Keep title, description, thumbnail, music, and visual aligned. Do not imply a live broadcast, 24/7 availability, exact duration, or benefits that are not true.
- Treat search phrases as wording evidence only. They do not establish search volume or promise reach.

Example for a verified Halloween café scene (primary phrase: “Lo-fi music for coding”):

- Good title: `Lo-fi music for coding | Halloween Café Focus`
- Reject: `Lo-fi music for coding | Hallowen Café Relaxing jazzhop for study and focus`
- The description must mention the Halloween café in its opening and describe only musical details confirmed for that video.

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

The YouTube publication form loads ranked observed phrases and same-intent, same-format historical context before an upload is queued. Confirm the bounded suggestion cost to compose a title and description, then review and edit both fields. The server blocks queueing unless the selected phrase appears within the first 60 title characters and in the first description sentence. The chosen intent and phrase are stored with the publication record. For exported programs, the publication intent must match the saved program intent; update the program before exporting if the target viewer changes.
