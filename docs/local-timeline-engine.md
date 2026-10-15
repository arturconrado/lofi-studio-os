# Local timeline assembly

The portal's Production step uses `/api/creator/assembly` and the existing export worker. No provider request is made by this engine.

Inputs are a saved ProductionSpec, full-frame action clips, a measured soundtrack from the same channel and reviewed scene regions. Imports remain private. Clip bytes are hashed and fully decoded before review; approvals bind to the file and creative fingerprint. Only reviewed compatible clips may be reused across plans, and cross-plan reuse requires explicit character and cat references. A reviewed eight-second interaction study is not an action pack.

The worker renders the absolute schedule locally. Idle clips may loop only with loop-seam review. Interaction clips must cover their full event without stretching or repetition. Lighting uses smooth interpolation on the absolute clock, holding the final state after hour one. Reviewed sky/light masks restrict the changes; mountains receive locally composed twinkling stars. Cushion lettering is a local overlay in a user-reviewed rectangle. Boundaries blend from the preceding frame over 0.35 seconds; pose compatibility still requires review.

Queue requests are durable and idempotent for an exact input snapshot. Only one timeline/export job runs at a time. Worker restart marks unfinished jobs interrupted; there is no automatic retry or provider spending. The portal displays progress and can stream/download the private MP4. Changed inputs invalidate final review. Full decoding and measured duration do not replace human checks of identity, anatomy/contact, motion, transitions, time progression, soundtrack style and rights.

Current limits: HD landscape clips, 12–60 fps, 2–120 seconds depending on the action, 64 MB per imported clip; 1 GB input soundtrack. Server rendering uses one encoder thread and requires scratch storage. Long rendering time and resource capacity must be measured on the actual server; a short test does not certify an uninterrupted four/eight-hour run.

This engine does not generate missing articulated action clips or a new original soundtrack. Those provider adapters and a complete real program review remain separate work. It does not register a live-ready program, start broadcasts, enqueue uploads or alter the release calendar. A final artifact review alone does not certify seamless repetition from the end of a night scene back to its initial sunset.
