/* Stroke icons, 24-grid, currentColor. */
const P = (d: string) => (props: { class?: string }) => (
  <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" class={props.class}>
    {d.split('|').map(p => <path d={p} />)}
  </svg>
);
export const IconHome = P('M3 11l9-7 9 7|M5 10v10h14V10|M10 20v-6h4v6');
export const IconSpark = P('M12 3v4|M12 17v4|M3 12h4|M17 12h4|M6 6l2.5 2.5|M15.5 15.5L18 18|M6 18l2.5-2.5|M15.5 8.5L18 6');
export const IconInbox = P('M4 13l2.5-7h11L20 13|M4 13v6h16v-6|M4 13h5l1 2h4l1-2h5');
export const IconLibrary = P('M4 5h4v14H4z|M10 5h4v14h-4z|M16 6l3.5-1 3 13.5-3.5 1z');
export const IconLive = P('M12 12m-2 0a2 2 0 1 0 4 0a2 2 0 1 0-4 0|M7.8 7.8a6 6 0 0 0 0 8.4|M16.2 7.8a6 6 0 0 1 0 8.4|M5 5a10 10 0 0 0 0 14|M19 5a10 10 0 0 1 0 14');
export const IconRecipe = P('M6 3h9l3 3v15H6z|M15 3v3h3|M9 11h6|M9 15h6');
export const IconChannel = P('M3 7h18v12H3z|M8 3l4 4 4-4');
export const IconSettings = P('M12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6z|M19.4 15a1.6 1.6 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.6 1.6 0 0 0-1.8-.3 1.6 1.6 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.6 1.6 0 0 0-1-1.5 1.6 1.6 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.6 1.6 0 0 0 .3-1.8 1.6 1.6 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1a1.6 1.6 0 0 0 1.5-1 1.6 1.6 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.6 1.6 0 0 0 1.8.3H9a1.6 1.6 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.6 1.6 0 0 0 1 1.5 1.6 1.6 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.6 1.6 0 0 0-.3 1.8V9a1.6 1.6 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.6 1.6 0 0 0-1.5 1z');
export const IconPulse = P('M3 12h4l3-8 4 16 3-8h4');
export const IconPlay = P('M7 4l13 8-13 8z');
export const IconPause = P('M7 4h3v16H7z|M14 4h3v16h-3z');
export const IconNext = P('M5 4l10 8-10 8z|M19 5v14');
export const IconPrev = P('M19 4L9 12l10 8z|M5 5v14');
export const IconCheck = P('M5 12l5 5 9-10');
export const IconX = P('M6 6l12 12|M18 6L6 18');
export const IconPlus = P('M12 5v14|M5 12h14');
export const IconArrow = P('M5 12h14|M13 6l6 6-6 6');
export const IconMusic = P('M9 18V5l11-2v13|M9 18a3 3 0 1 1-6 0 3 3 0 0 1 6 0z|M20 16a3 3 0 1 1-6 0 3 3 0 0 1 6 0z');
export const IconFilm = P('M3 5h18v14H3z|M7 5v14|M17 5v14|M3 9h4|M3 15h4|M17 9h4|M17 15h4');
export const IconUpload = P('M12 16V4|M7 9l5-5 5 5|M4 20h16');
export const IconLoop = P('M17 2l4 4-4 4|M3 11v-1a4 4 0 0 1 4-4h14|M7 22l-4-4 4-4|M21 13v1a4 4 0 0 1-4 4H3');
export const IconCommand = P('M9 9h6v6H9z|M9 9V6a3 3 0 1 0-3 3h3|M15 9V6a3 3 0 1 1 3 3h-3|M9 15v3a3 3 0 1 1-3-3h3|M15 15v3a3 3 0 1 0 3-3h-3');
