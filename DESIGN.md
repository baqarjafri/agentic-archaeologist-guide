# DESIGN.md: The Agentic Archaeologist guide

Source of truth: the finalised prototype `design/prototype/finalized.html`, kept in the private repository because its images are museum photographs. The approved direction is "Gallery Glass" (variant A, approved 7 Oct 2026) with three refinements: larger captions and labels, a compact object card while the guide speaks, and a visit trail at the top.

## Principles:
- **The artefact comes first:** a full-bleed live camera, with the interface floating in smoked glass at the edges.
- **One primary action:** a single round button. It reads "Tell me" when idle and "Ask" while the guide speaks.
- **Trust is visible:** every factual sentence carries a citation chip that opens the museum record passage.
- **Memory is visible and owned:** the visit trail stays on screen, and My visit states "Saved only on this phone".
- **Calm motion:** 180 to 260 ms ease-out; nothing pulses when reduced motion is on.

## Tokens:
| Token | Value | Use |
|---|---|---|
| `--glass` | `rgba(14,14,16,0.45)` | Panel fill |
| `--glass-fx` | `blur(18px) saturate(140%) brightness(0.45)` | Backdrop filter; keeps text at 4.5:1 over a white display case |
| `--glass-solid` | `rgba(14,14,16,0.86)` | Fallback where backdrop-filter is unsupported |
| `--hair` | `rgba(255,255,255,0.14)` | Hairline borders |
| `--ink` | `#F6F3EC` | Primary text |
| `--ink-2` | `rgba(246,243,236,0.72)` | Secondary text |
| `--ink-3` | `rgba(246,243,236,0.42)` | Upcoming words in captions, inactive marks |
| `--gilt` | `#D4B06A` | The single accent: button ring, current part, citation chips, links between pieces |
| `--gilt-soft` | `rgba(212,176,106,0.18)` | Accent fills |
| `--serif` | Fraunces (optical sizing) | Artefact names, headings |
| `--sans` | Instrument Sans | Captions, labels, UI |
| `--u` / `--edge` | 8 px / 16 px | Grid unit / screen margin |
| `--r-card` / `--r-chip` | 20 px / 999 px | Radii |
| `--shadow` | `0 8px 24px rgba(0,0,0,0.35)` | Floating glass |
| `--ease` | `cubic-bezier(0.22,0.61,0.36,1)` | All motion |
| `--t1` / `--t2` / `--t3` | 180 / 220 / 260 ms | Motion durations |

## Type scale:
- **Captions:** Instrument Sans 20/28, cycled to 23 and 26 by the Aa control. The previous sentence is 15/22 in `--ink-2`.
- **Spoken word:** shown as a gilt-tinted highlight. Words already spoken are `--ink`, words still to come are `--ink-3`.
- **Artefact name:** Fraunces 500, 24/26 in the expanded card and 19/22 in the compact card.
- **Labels, meta lines and chips:** Instrument Sans 13/18. Nothing is smaller than 13 px.

## Layout (412 × 915 Android reference):
- **Top:** status bar, then the visit trail. The trail is a glass strip of round thumbnails with times, the current piece ringed in gilt, and gilt connectors between linked pieces.
- **Left:** the object card at `--edge`, top 104 px. The expanded card is 240 px wide and shows name, meta and "Not this?". The compact card spans `calc(100% - 92px)` and shows name, "n of 4 · part" and progress segments; tapping it expands the part list.
- **Right:** a rail of three 48 px round glass buttons: My visit (with a count badge), Sources, and text size.
- **Bottom:** the caption card above an 84 px gilt-ringed primary button, with the gesture bar beneath.
- **Connection card:** appears at the top when a new piece links to one in memory. It shows both thumbnails joined by a gilt line, plus the theme and when the earlier piece was seen.
- **Mention overlay:** while a spoken sentence cites another piece, a glass card with that piece's photo (about 96 px), name and "seen 10:38" slides in at the top left, under the visit trail. It slides out when the sentence ends. Tapping it opens that piece's source. Only one overlay shows at a time, and it never covers the caption card or the primary button.

## States:
- **Recognised:** expanded card, "Tell me".
- **Telling:** compact card; captions with the spoken word highlighted; button "Ask" with gilt rings.
- **Listening:** rings expand; the visitor's words appear in a shrink-wrapped bubble.
- **Thinking:** a short shimmer.
- **Answer:** a cited caption, then "Carry on · next part".
- **Connected:** the connection card, then a story that cites both records.
- **Overlays:** the "Not this?" sheet, the source sheet, the My visit drawer, the confirm dialog and toasts.

## Interaction rules:
- Tapping Ask while the guide speaks stops speech at once and starts listening. Tapping Ask again, or releasing after a hold, sends the question. Tapping the camera stops the guide without listening.
- After an answer, "Carry on" resumes at the next part. The guide never repeats a fact the visitor has already heard.
- Swinging to a new piece shows its card. If memory links it to an earlier piece, the connection card appears.
- Whenever the guide cites another piece, its mention overlay appears for that sentence. The overlay is driven by the sentence's citations, not by guessing names in the text.
- "Not this?" lists the best match, close alternatives from the same gallery, the gallery list and object-number entry. It is the recovery path for misidentification.
- The source sheet quotes the record verbatim, highlights the supporting sentence, and links to the online record.
- My visit offers a timeline with a delete control on each entry, "Export visit" (a JSON file) and "Forget everything" (with a confirmation).

## Accessibility:
- Text contrast is at least 4.5:1 over both white display cases and dark galleries.
- Touch targets are at least 48 px.
- Captions use `aria-live="polite"`; sheets and the drawer are `role="dialog"` with `aria-modal`; Esc closes overlays; focus is visible.
- `prefers-reduced-motion` removes pulses and transitions.
- Every voice action has a tap equivalent, and captions are always on.

## Content rules:
- Facts come only from the pack, which is the museum's own record. Every factual sentence cites its source.
- A link the guide draws between two pieces cites both records.
- No em dashes. En dashes appear only inside date ranges.
- Speech may differ from the captions only in pronunciation. For example, the caption shows "Amenhotep III" and the voice says "Amenhotep the Third".
- Image credit: "Images: Glasgow Museums, CC BY-NC 4.0".
