# Legacy portal migration tracker

The legacy portal stays available until every creator workflow has a working equivalent in the new Studio. A screen with a similar name is not enough to count as migrated: the same data, review gates, actions, and recovery paths must be available from the new interface.

## Functional areas

| Legacy area | New Studio destination | Migration status | Remaining work |
|---|---|---|---|
| Início / overview | Estúdio | Parity review needed | Compare channel status, active work, and next actions. |
| Criar | Produzir, Receitas, Criar vídeo | Partial | Compare the legacy creator assistant, planning, text editing, and cost controls with the new flows. |
| Biblioteca / catalog | Biblioteca | In progress | Include approved ambient videos and their publication workflow; verify programs, music, visuals, exports, and uploaded-video management. |
| Lives / Mini OBS | Ao vivo | Parity review needed | Compare channel selection, signal setup, monitoring, playback, and recovery controls. |
| Canais | Canais | Parity review needed | Compare channel CRUD, credentials, YouTube connection scopes, and per-channel isolation. |
| Análises / Growth | No direct destination identified | Gap | Migrate monetization progress, Studio snapshots, experiments, projections, and reference comparisons. |
| Configurações | Ajustes | Parity review needed | Compare generation settings, cost ceilings, policies, and account controls. |
| Composições / audio review | Revisão, Receitas | Parity review needed | Verify audio review, provenance, versions, approvals, and recovery paths. |
| Programas e vídeos / autopilot | Produzir, Revisão, Biblioteca | Partial | Verify audio-batch automation, episode scheduling, pilot review, and approved-video publishing. |
| Tarefas / jobs / audit | Diagnóstico | Partial | Verify all job types, progress, failures, retries, and audit details. |
| Infraestrutura / operations | Diagnóstico | Parity review needed | Compare service health, worker health, and actionable incident details. |

## Current migration slice

- The new Library discovers approved, technically valid ambient videos and gives them a publication record without starting an upload.
- The operator can review the video, generate the Growth package, confirm rights, select visibility and audience designation, then explicitly authorize the YouTube upload.
- Long videos of at least 60 minutes remain eligible when their audio/video durations and technical integrity checks pass. The actual duration is preserved in the publication record.
- The legacy portal remains available during the migration. Do not remove its navigation until the remaining parity reviews are complete and their gaps are migrated.

## Completion rule

Mark an area migrated only after its new interface supports the same authorized actions and protections, its state is visible and recoverable, and the legacy route no longer provides unique functionality. Remove the legacy portal only after every row above has been verified and signed off.
